import io
import json
from pathlib import Path

import httpx
import pytest

from app import db
from app.models import User
from app.platform_models import AiApplication, ApplicationVersion, KnowledgeBaseMaterial
from tests.test_platform_runtime import platform, setup_conversation, send, response
from tests.test_platform_resources import MAIN
from tests.test_platform_tools import FakeMcp, add_connection
from tests.conftest import login


def test_teacher_can_create_resources_upload_publish_and_student_cannot(platform):
    app, client, users = platform
    t = client.post("/api/prompt-templates", json={"name": "模板", "body": "请说明 {{topic}}", "variables": ["topic"]})
    assert t.status_code == 201
    b = client.post("/api/knowledge-bases", json={"name": "自选", "material_ids": [users["material_a_id"]]})
    assert b.status_code == 201
    assert client.patch(f"/api/knowledge-bases/{b.get_json()['id']}", json={"material_ids": [users["material_b_id"]]}).status_code == 404
    s = client.post("/api/skill-packages", data={"file": (io.BytesIO(MAIN.encode()), "SKILL.md")})
    assert s.status_code == 201
    config = {"template_version_id": t.get_json()["versions"][-1]["id"], "skill_version_ids": [s.get_json()["versions"][-1]["id"]], "knowledge_base_ids": [b.get_json()["id"]]}
    a = client.post("/api/apps", json={"name": "自定义", "slug": "custom", "purpose": "test", "config": config})
    assert a.status_code == 201
    app_id = a.get_json()["id"]
    app.config["AI_MODEL_CAPABILITIES"][app.config["ZHIPU_MODEL"]]["tools"] = False
    assert client.post(f"/api/apps/{app_id}/publish").get_json()["error"] == "model_tools_unsupported"
    app.config["AI_MODEL_CAPABILITIES"][app.config["ZHIPU_MODEL"]]["tools"] = True
    assert client.post(f"/api/apps/{app_id}/publish").status_code == 201
    login(client, "student_a", "student-password")
    assert any(a["id"] == app_id for a in client.get("/api/apps").get_json()["apps"])
    assert client.patch(f"/api/apps/{app_id}", json={"name": "x"}).status_code == 403
    assert client.post("/api/skill-packages", data={"file": (io.BytesIO(MAIN.encode()), "SKILL.md")}).status_code == 403
    assert client.post("/api/tool-connections", json={}).status_code == 403
    login(client, "teacher_b", "teacher-password")
    assert client.get(f"/api/apps/{app_id}").status_code == 404


def test_new_upload_joins_default_knowledge_base(platform):
    app, client, users = platform
    result = client.post("/api/materials/upload", data={"title": "new", "file": (io.BytesIO(b"newbody"), "new.txt")})
    assert result.status_code == 201, result.get_json()
    material_id = result.get_json()["id"]
    bases = client.get("/api/knowledge-bases").get_json()["knowledge_bases"]
    assert material_id in next(b for b in bases if b["is_default"])["material_ids"]


def test_platform_shell_and_safe_dom(platform):
    app, client, users = platform
    html = client.get("/apps").get_data(as_text=True)
    assert "apps-management" in html and "apps-trace-dialog" in html
    assert "teacher_a" not in html and "private-llm-key" not in html
    assert 'id="apps-key" type="password" autocomplete="off"' in html
    source = (Path(app.root_path) / "static/js/platform.js").read_text()
    assert "innerHTML" not in source and "textContent" in source
    assert "sessionStorage" not in source and "localStorage" not in source
    app.config["AI_PLATFORM_ENABLED"] = False
    assert client.get("/apps").status_code == 404
    assert client.get("/materials").status_code == 200


def test_sdk_accepts_sse_and_session_expiry_does_not_replay(platform, monkeypatch):
    app, client, users = platform
    fake = FakeMcp()
    connection_id = add_connection(platform, monkeypatch)
    def sse(request):
        original = fake.handler(request)
        if original.status_code != 200:
            return original
        data = original.json()
        return httpx.Response(200, headers={"content-type": "text/event-stream", "MCP-Session-Id": "session"},
                              content=("event: message\ndata: " + json.dumps(data) + "\n\n").encode())
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(sse)
    result = client.post(f"/api/tool-connections/{connection_id}/discover")
    assert result.status_code == 200, result.get_json()
    attempts = []
    def expired(request):
        if request.method == "POST" and json.loads(request.content)["method"] == "tools/list":
            attempts.append(1)
            return httpx.Response(404)
        return fake.handler(request)
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(expired)
    assert client.post(f"/api/tool-connections/{connection_id}/discover").status_code == 503
    assert len(attempts) == 1
