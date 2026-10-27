"""Five required validations against the actual serialized transport boundary."""
import copy
import io
import json
import socket
from datetime import timedelta

import pytest

from app import db
from app.models import User
from app.platform_models import (
    AiApplication, ApplicationVersion, TemplateVersion, SkillVersion, SkillPackage,
    ConversationRun, AppConversation, now,
)
from app.platform_resources import initialize_platform, save_template, save_skill, publish_application
from tests.conftest import login
from tests.test_platform_resources import package_bytes, MAIN


@pytest.fixture
def platform(app, client, seed_users, monkeypatch):
    app.config.update(AI_PLATFORM_ENABLED=True, AI_MODEL_CAPABILITIES={app.config["ZHIPU_MODEL"]: {"tools": True}})
    with app.app_context():
        initialize_platform()
    # No real network is permitted in this verification suite, including regressions.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected real network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    login(client, "teacher_a", "teacher-password")
    return app, client, seed_users


def response(content="测试答案", calls=None, **extra):
    return 200, json.dumps({"id": "fake-provider", "model": "fake", "choices": [{
        "message": {"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})},
        "finish_reason": "tool_calls" if calls else "stop"}], **extra}, ensure_ascii=False).encode()


def call(name, arguments, ident="call-1"):
    return {"id": ident, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def setup_conversation(client, slug="chat"):
    apps = client.get("/api/apps").get_json()["apps"]
    selected = next(a for a in apps if a["slug"] == slug)
    created = client.post("/api/app-conversations", json={"application_id": selected["id"]})
    assert created.status_code == 201, created.get_json()
    return selected, created.get_json()["id"]


def send(client, conversation_id, **extra):
    return client.post(f"/api/app-conversations/{conversation_id}/messages", json={"content": "A班笔记", "api_key": "private-llm-key", "request_id": "request-1", **extra})


def test_validation_1_actual_request_template_response_and_trace(platform):
    app, client, users = platform
    _, conv = setup_conversation(client)
    with app.app_context():
        teacher = db.session.get(User, users["teacher_a_id"])
        application = AiApplication.query.filter_by(class_id=teacher.class_id, slug="chat").one()
        _, template = save_template(teacher, {"name": "verification", "body": "template-marker {{topic}}", "variables": ["topic"]})
        application.draft = {"template_version_id": template.id}
        publish_application(teacher, application); db.session.commit()
    captured = []
    def transport(url, body, headers, timeout):
        captured.append((body, headers))
        assert headers["Authorization"] == "Bearer private-llm-key"
        assert b"private-llm-key" not in body
        return response("可见答案", usage={"total_tokens": 22})
    app.config["AI_LLM_TRANSPORT"] = transport
    result = send(client, conv, variables={"topic": "topic-marker"})
    assert result.status_code == 200, result.get_json()
    evidence = client.get("/api/conversation-runs/" + result.get_json()["run_id"])
    assert evidence.headers["Cache-Control"] == "no-store"
    trace = evidence.get_json()
    actual = json.loads(captured[0][0])
    assert trace["calls"][0]["request"]["body"]["json"] == actual
    assert set(actual) == {"model", "messages", "stream", "temperature", "max_tokens"}
    assert "template-marker topic-marker" in actual["messages"][1]["content"]
    assert trace["calls"][0]["parsed"]["usage"] == {"total_tokens": 22}
    assert "可见答案" in trace["calls"][0]["response"]["raw"]
    assert "private-llm-key" not in json.dumps(trace)
    assert result.get_json()["answer"] == "可见答案"


def test_validation_2_knowledge_only_selected_sources_and_no_hit(platform):
    app, client, users = platform
    _, conv = setup_conversation(client, "knowledge")
    captured = []
    app.config["AI_LLM_TRANSPORT"] = lambda url, body, headers, timeout: (captured.append(json.loads(body)) or response("依据本班笔记。[1]"))
    result = send(client, conv)
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["sources"][0]["material_id"] == users["material_a_id"]
    assert "B班" not in json.dumps(captured, ensure_ascii=False)
    assert len(captured) == 1
    result = send(client, conv, content="completely-unmatched-zzzz", request_id="request-2")
    assert result.status_code == 200 and result.get_json()["generated"] is False
    trace = client.get("/api/conversation-runs/" + result.get_json()["run_id"]).get_json()
    assert trace["calls"] == [] and len(captured) == 1


def bind_uploaded_skills(app, users):
    with app.app_context():
        teacher = db.session.get(User, users["teacher_a_id"])
        _, version = save_skill(teacher, "demo.zip", package_bytes([
            ("SKILL.md", MAIN), ("references/a.md", "selected-ref-a"), ("references/b.md", "unselected-ref-b")]))
        application = AiApplication.query.filter_by(class_id=teacher.class_id, slug="chat").one()
        application.draft = {**application.draft, "skill_version_ids": [version.id]}
        publish_application(teacher, application); db.session.commit()
        return version.id


def test_validation_3_bound_skill_summary_only_and_explicit_loading(platform):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    captured = []
    def transport(_url, body, _headers, _timeout):
        captured.append(json.loads(body))
        if len(captured) == 2:
            return response(calls=[call("read_skill_reference", {"skill_version_id": skill_id, "path": "references/a.md"})])
        return response()
    app.config["AI_LLM_TRANSPORT"] = transport
    assert send(client, conv).status_code == 200
    assert "示例" in json.dumps(captured[0], ensure_ascii=False)
    assert "unique-main" not in json.dumps(captured[0])
    result = send(client, conv, skill_version_id=skill_id, request_id="explicit")
    assert result.status_code == 200, result.get_json()
    assert "unique-main" in json.dumps(captured[1])
    assert "selected-ref-a" in json.dumps(captured[2])
    assert "unselected-ref-b" not in json.dumps(captured)
    assert "selected-ref-a" not in json.dumps(captured[1])


def test_validation_4_automatic_skill_execution_chain(platform):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    captured = []
    def transport(_url, body, _headers, _timeout):
        captured.append(json.loads(body))
        if len(captured) == 1:
            return response(calls=[call("load_skill", {"skill_version_id": skill_id})])
        if len(captured) == 2:
            return response(calls=[call("read_skill_reference", {"skill_version_id": skill_id, "path": "references/a.md"}, "call-2")])
        return response()
    app.config["AI_LLM_TRANSPORT"] = transport
    result = send(client, conv)
    assert result.status_code == 200, result.get_json()
    trace = client.get("/api/conversation-runs/" + result.get_json()["run_id"]).get_json()
    kinds = [e["kind"] for e in trace["events"]]
    assert kinds.index("skill_loaded") < kinds.index("skill_reference") < kinds.index("skill_completed")
    assert len(trace["calls"]) == 3
    assert "unique-main" not in json.dumps(captured[0])
    assert "unique-main" in json.dumps(captured[1])
    assert "selected-ref-a" in json.dumps(captured[2])


def test_permissions_duplicate_request_and_history_not_replayed(platform):
    app, client, users = platform
    _, conv = setup_conversation(client)
    bodies = []
    app.config["AI_LLM_TRANSPORT"] = lambda u, b, h, t: (bodies.append(b) or response())
    first = send(client, conv, content="prior-turn-private-marker")
    assert first.status_code == 200
    assert send(client, conv).get_json() == first.get_json()
    assert len(bodies) == 1
    second = send(client, conv, request_id="second", content="new question")
    assert second.status_code == 200
    assert b"prior-turn-private-marker" not in bodies[-1]
    run_id = first.get_json()["run_id"]
    login(client, "student_a", "student-password")
    assert client.get(f"/api/app-conversations/{conv}").status_code == 404
    assert client.get(f"/api/conversation-runs/{run_id}").status_code == 404
    assert client.post("/api/prompt-templates", json={}).status_code == 403
    login(client, "teacher_b", "teacher-password")
    assert client.get(f"/api/app-conversations/{conv}").status_code == 404


@pytest.mark.parametrize("provider", [lambda: (200, b"not-json"), lambda: response(calls=[call("shell", {"cmd": "bad"})]), lambda: (401, b"upstream private-llm-key"), lambda: response("")])
def test_provider_errors_never_create_success_and_trace_redacts(platform, provider):
    app, client, users = platform
    _, conv = setup_conversation(client)
    app.config["AI_LLM_TRANSPORT"] = lambda *_args: provider()
    result = send(client, conv)
    assert result.status_code in {403, 422, 503}, result.get_json()
    assert client.get(f"/api/app-conversations/{conv}").get_json()["messages"] == []
    runs = client.get("/api/conversation-runs").get_json()["runs"]
    trace = client.get("/api/conversation-runs/" + runs[0]["id"]).get_json()
    assert trace["status"] == "failed" and "private-llm-key" not in json.dumps(trace)


def test_expiry_delete_and_cleanup_preserve_messages(platform):
    app, client, users = platform
    _, conv = setup_conversation(client)
    app.config["AI_LLM_TRANSPORT"] = lambda *_: response()
    result = send(client, conv).get_json()
    run_id = result["run_id"]
    assert client.get(f"/api/conversation-runs/{run_id}/export").status_code == 200
    with app.app_context():
        run = db.session.get(ConversationRun, run_id)
        run.expires_at = now() - timedelta(seconds=1); db.session.commit()
    assert client.get(f"/api/conversation-runs/{run_id}").status_code == 404
    out = app.test_cli_runner().invoke(args=["cleanup-platform-traces"])
    assert out.exit_code == 0, out.output
    assert len(client.get(f"/api/app-conversations/{conv}").get_json()["messages"]) == 2
