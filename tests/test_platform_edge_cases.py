import copy
import io
import json
import stat
import zipfile
from datetime import timedelta

import httpx
import pytest

from app import db
from app.models import User, Material, KnowledgeEntry, SolverSkill
from app.platform_models import (
    AiApplication, ApplicationVersion, AppConversation, AppMessage,
    ConversationRun, LlmCall, RunEvent, SkillPackage, ToolConnection,
    ToolDefinitionVersion, KnowledgeBase, now,
)
from app.platform_resources import save_template, publish_application, PlatformError, parse_skill
from app.platform_trace import Trace, Redactor
from app.platform_tools import BoundedAsyncStream, mcp_operation
from app.retrieval import replace_entry_index
from tests.conftest import login
from tests.test_platform_runtime import platform, setup_conversation, send, response, call, bind_uploaded_skills
from tests.test_platform_tools import FakeMcp, add_connection, bind_tool, TOOL
from tests.test_platform_resources import MAIN, package_bytes


def test_running_lock_and_recovery_never_replays(platform):
    app, client, users = platform
    _, conv = setup_conversation(client)
    with app.app_context():
        obj = db.session.get(AppConversation, conv)
        run = ConversationRun(class_id=obj.class_id, owner_id=obj.owner_id, conversation_id=conv, request_id="interrupted",
                              expires_at=now() + timedelta(days=1), created_at=now() - timedelta(hours=1))
        db.session.add(run); db.session.flush(); obj.active_run_id = run.id; db.session.commit()
    app.config["AI_LLM_TRANSPORT"] = lambda *_: pytest.fail("locked or stale run cannot be replayed")
    assert send(client, conv).status_code == 409
    out = app.test_cli_runner().invoke(args=["recover-platform-runs"])
    assert out.exit_code == 0, out.output
    assert send(client, conv, request_id="interrupted").get_json()["error"] == "run_interrupted"
    with app.app_context():
        assert db.session.get(AppConversation, conv).active_run_id is None


def test_template_version_is_pinned_during_tool_cycle(platform):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    bodies = []
    def model(_url, body, _headers, _timeout):
        bodies.append(json.loads(body))
        if len(bodies) == 1:
            teacher = db.session.get(User, users["teacher_a_id"])
            application = AiApplication.query.filter_by(class_id=teacher.class_id, slug="chat").one()
            _, version = save_template(teacher, {"name": "changed", "body": "new-template-marker"})
            application.draft = {**application.draft, "template_version_id": version.id}
            publish_application(teacher, application); db.session.commit()
            return response(calls=[call("load_skill", {"skill_version_id": skill_id})])
        return response()
    app.config["AI_LLM_TRANSPORT"] = model
    assert send(client, conv).status_code == 200
    assert "new-template-marker" not in json.dumps(bodies)
    assert send(client, conv, request_id="next").status_code == 200
    assert "new-template-marker" in json.dumps(bodies[-1])


def test_skill_revocation_before_next_model_call_stops_execution(platform):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    seen = []
    def model(*_):
        seen.append(1)
        SkillPackage.query.filter_by(name="demo", class_id=users["class_a_id"]).one().enabled = False
        db.session.commit()
        return response(calls=[call("load_skill", {"skill_version_id": skill_id})])
    app.config["AI_LLM_TRANSPORT"] = model
    assert send(client, conv).status_code == 404
    assert len(seen) == 1


def test_budget_limit_and_context_limit_are_bounded(platform):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    app.config["AI_MAX_MODEL_CALLS"] = 2
    app.config["AI_LLM_TRANSPORT"] = lambda *_: response(calls=[call("load_skill", {"skill_version_id": skill_id})])
    result = send(client, conv)
    assert result.status_code == 503 and result.get_json()["error"] == "tool_budget_exceeded"
    app.config["AI_INPUT_BUDGET"] = 100
    app.config["AI_LLM_TRANSPORT"] = lambda *_: pytest.fail("oversized mandatory context cannot call model")
    assert send(client, conv, request_id="small").get_json()["error"] == "context_budget_exceeded"


def test_trace_failure_before_transport_sends_nothing(platform, monkeypatch):
    app, client, users = platform
    _, conv = setup_conversation(client)
    app.config["AI_LLM_TRANSPORT"] = lambda *_: pytest.fail("no transport without evidence")
    original = Trace.begin_call
    def failed(*args, **kwargs):
        raise PlatformError("trace_unavailable", 503)
    monkeypatch.setattr(Trace, "begin_call", failed)
    result = send(client, conv)
    assert result.status_code == 503 and result.get_json()["error"] == "trace_unavailable"
    with app.app_context():
        assert LlmCall.query.count() == 0
        assert ConversationRun.query.one().status == "failed"


def test_large_bound_library_skips_unbound_candidates_before_top_k(platform):
    app, client, users = platform
    with app.app_context():
        teacher = db.session.get(User, users["teacher_a_id"])
        base = KnowledgeBase(class_id=teacher.class_id, name="subset")
        db.session.add(base); db.session.flush()
        from app.platform_models import KnowledgeBaseMaterial
        db.session.add(KnowledgeBaseMaterial(class_id=teacher.class_id, base_id=base.id, material_id=users["material_a_id"]))
        wanted = db.session.get(Material, users["material_a_id"])
        wanted.knowledge_entry.body = "matchword selected-marker\n" + "irrelevant-tail-marker " * 500
        replace_entry_index(wanted.knowledge_entry)
        # >200 higher-ranked candidates exist but belong to an unbound material.
        material = Material(class_id=teacher.class_id, uploader_id=teacher.id, title="unbound", filename="u.txt", stored_filename="u.txt", content_type="text/plain", size_bytes=1)
        entry = KnowledgeEntry(class_id=teacher.class_id, material=material, body=("matchword unbound-marker " * 200 + "\n") * 230)
        db.session.add_all([material, entry]); db.session.flush(); replace_entry_index(entry)
        application = AiApplication.query.filter_by(class_id=teacher.class_id, slug="knowledge").one()
        application.draft = {**application.draft, "knowledge_base_ids": [base.id]}
        publish_application(teacher, application); db.session.commit()
    app.config["KNOWLEDGE_QA_MAX_CONTEXT_CHARS"] = 35
    captured = []
    app.config["AI_LLM_TRANSPORT"] = lambda u, b, h, t: (captured.append(b) or response("依据。[1]"))
    _, conv = setup_conversation(client, "knowledge")
    result = send(client, conv, content="matchword")
    assert result.status_code == 200, result.get_json()
    assert b"selected-marker" in captured[0] and b"unbound-marker" not in captured[0]
    assert b"irrelevant-tail-marker" not in captured[0]
    assert sum(len(s["passage"]) for s in result.get_json()["sources"]) <= 35


def test_multiple_mcp_tool_calls_have_matching_results(platform, monkeypatch):
    app, client, users = platform
    fake = FakeMcp(); app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(fake.handler)
    connection_id = add_connection(platform, monkeypatch)
    definition = client.post(f"/api/tool-connections/{connection_id}/discover").get_json()["definitions"][0]
    bind_tool(app, users, definition["id"])
    _, conv = setup_conversation(client)
    bodies = []
    name = f"ext_{connection_id}_{definition['id']}"
    def model(_u, body, _h, _t):
        bodies.append(json.loads(body))
        return response(calls=[call(name, {"query": "a"}, "a"), call(name, {"query": "b"}, "b")]) if len(bodies) == 1 else response()
    app.config["AI_LLM_TRANSPORT"] = model
    assert send(client, conv).status_code == 200
    assert [m["tool_call_id"] for m in bodies[1]["messages"] if m["role"] == "tool"] == ["a", "b"]


def test_mcp_protocol_and_redirect_failure_are_not_retried(platform, monkeypatch):
    app, client, users = platform
    connection_id = add_connection(platform, monkeypatch)
    fake = FakeMcp(); fake.protocol = "unknown"
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(fake.handler)
    result = client.post(f"/api/tool-connections/{connection_id}/discover")
    assert result.status_code == 503
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://forbidden.example/mcp"})
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(redirect)
    result = client.post(f"/api/tool-connections/{connection_id}/discover")
    assert result.status_code == 503 and len(calls) == 1


def test_http_result_redacts_before_truncation_and_does_not_fetch_links(platform, monkeypatch):
    app, client, users = platform
    connection_id = add_connection(platform, monkeypatch, "http")
    definition = client.post(f"/api/tool-connections/{connection_id}/discover").get_json()["definitions"][0]
    bind_tool(app, users, definition["id"])
    app.config["AI_TOOL_RESULT_CHARS"] = 100
    requests = []
    app.config["AI_HTTP_TOOL_TRANSPORT"] = lambda: httpx.MockTransport(lambda req: (requests.append(req) or httpx.Response(200, json={"answer": "private-tool-key " * 100, "url": "http://169.254.169.254"})))
    _, conv = setup_conversation(client)
    bodies = []
    def model(_u, b, _h, _t):
        bodies.append(json.loads(b))
        return response(calls=[call(f"ext_{connection_id}_{definition['id']}", {"query": "a"})]) if len(bodies) == 1 else response()
    app.config["AI_LLM_TRANSPORT"] = model
    result = send(client, conv)
    assert result.status_code == 200, result.get_json()
    assert len(requests) == 1
    assert "private-tool" not in json.dumps(bodies)
    assert json.loads(bodies[-1]["messages"][-1]["content"])["truncated"] is True


def test_legacy_json_and_sse_capture_preserve_original_protocol(platform):
    app, client, users = platform
    seen = []
    app.config["ZHIPU_TRANSPORT"] = lambda u, p, h, t: (seen.append(copy.deepcopy(p)) or response("原单轮答案。[1]"))
    result = client.post("/api/knowledge/answer", json={"question": "A班笔记", "api_key": "private-llm-key"})
    assert result.status_code == 200 and result.get_json()["answer"] == "原单轮答案。[1]"
    login(client, "student_a", "student-password")
    skill = client.get("/api/solver/skills").get_json()["skills"][0]
    conv = client.post("/api/solver/sessions", json={"skill_id": skill["id"]}).get_json()["id"]
    def stream(_u, p, _h, _t):
        seen.append(copy.deepcopy(p))
        raw = b"data: " + json.dumps({"choices": [{"delta": {"content": "先观察资料再思考下一步。[1]"}}]}, ensure_ascii=False).encode() + b"\n\ndata: [DONE]\n\n"
        for offset in range(0, len(raw), 7):
            yield raw[offset:offset + 7]
    app.config["ZHIPU_STREAM_TRANSPORT"] = stream
    result = client.post(f"/api/solver/sessions/{conv}/messages", json={"content": "A班笔记", "api_key": "private-llm-key"})
    assert result.status_code == 200 and b"event: done" in result.data
    assert seen[0]["stream"] is False and seen[1]["stream"] is True
    assert skill["prompt"] in seen[1]["messages"][1]["content"]
    rows = client.get("/api/conversation-runs").get_json()["runs"]
    evidence = client.get("/api/conversation-runs/" + rows[0]["id"]).get_json()
    assert "data:" in evidence["calls"][0]["response"]["raw"]
    assert evidence["calls"][0]["parsed"]["completed"] is True


def test_trace_capture_truncation_and_cross_chunk_secret_redaction(app):
    with app.app_context():
        redactor = Redactor(["long-secret-marker"])
        raw = b'{"message":"' + b"long-sec" + b"ret-marker" + b'","password":"unknown-secret"}'
        evidence = redactor.capture(raw, limit=35)
        assert evidence["truncated"] is True and evidence["total_bytes"] == len(raw)
        assert "long-sec" not in evidence["raw"] and "unknown-secret" not in evidence["raw"]


def test_sse_redacts_secret_split_across_distinct_delta_events(app):
    with app.app_context():
        redactor = Redactor(["private-llm-key"])
        raw = b"".join(b"data: " + json.dumps({"choices": [{"delta": {"content": fragment}}]}).encode() + b"\n\n"
                       for fragment in ("prefix ", "private-", "llm-key", " suffix"))
        sanitized = redactor.sse(raw)
        assert "private-" not in sanitized and "llm-key" not in sanitized
        assert "prefix " in sanitized and " suffix" in sanitized


def test_trace_response_write_failure_cannot_commit_success_messages(platform, monkeypatch):
    app, client, users = platform
    skill_id = bind_uploaded_skills(app, users)
    _, conv = setup_conversation(client)
    app.config["AI_LLM_TRANSPORT"] = lambda *_: response()
    original = Trace.finish
    def failed_success(self, result=None, error=None):
        if result is not None:
            db.session.rollback()
            raise PlatformError("trace_unavailable", 503)
        return original(self, result, error)
    monkeypatch.setattr(Trace, "finish", failed_success)
    assert send(client, conv, skill_version_id=skill_id).status_code == 503
    assert client.get(f"/api/app-conversations/{conv}").get_json()["messages"] == []


def test_tool_timeout_is_absolute_even_for_trickled_http_body(platform, monkeypatch):
    import anyio
    app, client, users = platform
    connection_id = add_connection(platform, monkeypatch, "http")
    definition = client.post(f"/api/tool-connections/{connection_id}/discover").get_json()["definitions"][0]
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await anyio.sleep(.01)
                yield b"x"
    app.config["AI_HTTP_TOOL_TRANSPORT"] = lambda: httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowStream()))
    from app.platform_tools import execute_external
    with app.app_context(), pytest.raises(PlatformError, match="tool_unavailable"):
        execute_external(db.session.get(ToolDefinitionVersion, definition["id"]), {"query": "a"}, .03)


def test_skill_symlinks_duplicate_paths_and_directory_entries(app):
    with app.app_context():
        for bad in ("link", "duplicate"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("SKILL.md", MAIN)
                if bad == "link":
                    info = zipfile.ZipInfo("references/a.md"); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, "/etc/passwd")
                else:
                    archive.writestr("references/a.md", "a")
                    with pytest.warns(UserWarning):
                        archive.writestr("references/a.md", "b")
            with pytest.raises(PlatformError, match="invalid_skill_package"):
                parse_skill("demo.zip", stream.getvalue())
        name, *_ = parse_skill("demo.zip", package_bytes([("SKILL.md", MAIN), ("references/", ""), ("references/a.md", "a")]))
        assert name == "demo"
