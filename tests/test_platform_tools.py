import copy
import json

import httpcore
import httpx
import pytest

from app import db
from app.models import User
from app.platform_models import AiApplication, ToolConnection, ToolDefinitionVersion
from app.platform_resources import publish_application, PlatformError
from app.platform_tools import (
    validate_target, validate_schema, PinnedSyncBackend, PinnedAsyncBackend,
    execute_external,
)
from tests.test_platform_runtime import platform, setup_conversation, send, response, call


TOOL = {"name": "lookup", "description": "检索授权资料", "inputSchema": {
    "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
    "outputSchema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}


class FakeMcp:
    def __init__(self):
        self.requests = []
        self.tool = copy.deepcopy(TOOL)
        self.is_error = False
        self.protocol = "2025-11-25"

    def handler(self, request):
        if request.method == "DELETE":
            return httpx.Response(204)
        rpc = json.loads(request.content)
        self.requests.append({"rpc": rpc, "headers": dict(request.headers)})
        method = rpc["method"]
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": self.protocol, "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}
        elif method == "tools/list":
            if rpc.get("params", {}).get("cursor") == "page-2":
                result = {"tools": [{**self.tool, "name": "unbound"}]}
            else:
                result = {"tools": [self.tool], "nextCursor": "page-2"}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "MCP-result-marker"}], "structuredContent": {"answer": "MCP-result-marker"}, "isError": self.is_error}
        else:
            raise AssertionError(method)
        return httpx.Response(200, headers={"MCP-Session-Id": "private-session"}, json={"jsonrpc": "2.0", "id": rpc["id"], "result": result})


def add_connection(platform, monkeypatch, kind="mcp", sensitive=None):
    app, client, users = platform
    app.config.update(AI_TOOL_ALLOWED_HOSTS=["tools.example.test"], AI_DNS_RESOLVER=lambda host: ["93.184.216.34"],
                      AI_CREDENTIAL_REFERENCES={"demo": {"env": "PLATFORM_TEST_TOOL_KEY", "class_ids": [users["class_a_id"]]}})
    monkeypatch.setenv("PLATFORM_TEST_TOOL_KEY", "private-tool-key")
    payload = {"name": "demo", "kind": kind, "url": "https://tools.example.test/mcp", "credential_ref": "demo"}
    if kind == "http":
        payload["http_config"] = {"method": "POST", "parameter_map": {"query": "q"}, "tool": {**TOOL, "sensitive_parameters": sensitive or []}}
    created = client.post("/api/tool-connections", json=payload)
    assert created.status_code == 201, created.get_json()
    connection_id = created.get_json()["id"]
    return connection_id


def bind_tool(app, users, definition_id):
    with app.app_context():
        teacher = db.session.get(User, users["teacher_a_id"])
        application = AiApplication.query.filter_by(class_id=teacher.class_id, slug="chat").one()
        application.draft = {**application.draft, "tool_definition_ids": [definition_id]}
        publish_application(teacher, application); db.session.commit()


def test_validation_5_mcp_sdk_discovery_call_and_llm_backfill(platform, monkeypatch):
    app, client, users = platform
    fake = FakeMcp()
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(fake.handler)
    connection_id = add_connection(platform, monkeypatch)
    discovered = client.post(f"/api/tool-connections/{connection_id}/discover")
    assert discovered.status_code == 200, discovered.get_json()
    definitions = discovered.get_json()["definitions"]
    assert len(definitions) == 2  # The official SDK follows real JSON-RPC pagination.
    bound = next(d for d in definitions if d["name"] == "lookup")
    bind_tool(app, users, bound["id"])
    _, conversation_id = setup_conversation(client)
    captured = []
    name = f"ext_{connection_id}_{bound['id']}"
    def model(_url, body, _headers, _timeout):
        captured.append(json.loads(body))
        if len(captured) == 1:
            return response(calls=[call(name, {"query": "question"})])
        return response("完成")
    app.config["AI_LLM_TRANSPORT"] = model
    result = send(client, conversation_id)
    assert result.status_code == 200, result.get_json()
    assert captured[0]["tool_choice"] == "auto"
    assert len(captured[0]["tools"]) == 1
    assert captured[0]["tools"][0]["function"]["parameters"] == TOOL["inputSchema"]
    assert "unbound" not in json.dumps(captured)
    assert "private-tool-key" not in json.dumps(captured)
    assert "tools.example.test" not in json.dumps(captured)
    assert captured[1]["messages"][-2]["tool_calls"][0]["id"] == "call-1"
    assert captured[1]["messages"][-1]["tool_call_id"] == "call-1"
    assert "MCP-result-marker" in captured[1]["messages"][-1]["content"]
    remote_calls = [r for r in fake.requests if r["rpc"]["method"] == "tools/call"]
    assert len(remote_calls) == 1
    assert remote_calls[0]["rpc"]["params"]["arguments"] == {"query": "question"}
    assert remote_calls[0]["headers"]["authorization"] == "Bearer private-tool-key"
    assert remote_calls[0]["headers"]["mcp-protocol-version"] == "2025-11-25"
    trace = client.get("/api/conversation-runs/" + result.get_json()["run_id"]).get_json()
    assert len(trace["calls"]) == 2
    assert len([e for e in trace["events"] if e["kind"] == "tool_result"]) == 1
    assert "private-tool-key" not in json.dumps(trace)


def test_http_parameter_mapping_sensitive_redaction_and_invalid_arguments(platform, monkeypatch):
    app, client, users = platform
    connection_id = add_connection(platform, monkeypatch, "http", sensitive=["query"])
    discovered = client.post(f"/api/tool-connections/{connection_id}/discover").get_json()
    definition_id = discovered["definitions"][0]["id"]
    bind_tool(app, users, definition_id)
    _, conv = setup_conversation(client)
    requests = []
    def handler(request):
        requests.append(request)
        assert json.loads(request.content) == {"q": "private-sensitive-query"}
        return httpx.Response(200, json={"answer": "private-sensitive-query private-tool-key"})
    app.config["AI_HTTP_TOOL_TRANSPORT"] = lambda: httpx.MockTransport(handler)
    counter = []
    def model(*_args):
        counter.append(1)
        return response(calls=[call(f"ext_{connection_id}_{definition_id}", {"query": "private-sensitive-query"})]) if len(counter) == 1 else response()
    app.config["AI_LLM_TRANSPORT"] = model
    result = send(client, conv)
    assert result.status_code == 200, result.get_json()
    trace = client.get("/api/conversation-runs/" + result.get_json()["run_id"]).get_json()
    encoded = json.dumps(trace)
    assert "private-sensitive-query" not in encoded and "private-tool-key" not in encoded
    with app.app_context():
        definition = db.session.get(ToolDefinitionVersion, definition_id)
        with pytest.raises(PlatformError, match="invalid_tool_arguments"):
            execute_external(definition, {"unknown": "x"}, 1)
    assert len(requests) == 1


def test_mcp_definition_change_invalidates_existing_binding(platform, monkeypatch):
    app, client, users = platform
    fake = FakeMcp()
    app.config["AI_MCP_HTTP_TRANSPORT"] = lambda: httpx.MockTransport(fake.handler)
    connection_id = add_connection(platform, monkeypatch)
    defs = client.post(f"/api/tool-connections/{connection_id}/discover").get_json()["definitions"]
    bind_tool(app, users, defs[0]["id"])
    fake.tool["description"] = "changed"
    client.post(f"/api/tool-connections/{connection_id}/discover")
    _, conv = setup_conversation(client)
    app.config["AI_LLM_TRANSPORT"] = lambda *_: pytest.fail("must not call model for stale binding")
    assert send(client, conv).get_json()["error"] == "stale_tool_binding"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "0.0.0.0"])
def test_forbidden_target_addresses(app, address):
    app.config.update(AI_TOOL_ALLOWED_HOSTS=["tools.example.test"], AI_DNS_RESOLVER=lambda _: [address])
    with app.app_context(), pytest.raises(PlatformError, match="tool_target_forbidden"):
        validate_target("https://tools.example.test/mcp")


def test_no_remote_schema_references_or_unallowed_host(app):
    with app.app_context():
        with pytest.raises(PlatformError, match="invalid_tool_schema"):
            validate_schema({"$ref": "https://internal/secret"})
        with pytest.raises(PlatformError, match="tool_target_forbidden"):
            validate_target("https://unlisted.example/mcp")


def test_pinned_backend_uses_validated_address_not_second_dns_lookup(monkeypatch):
    received = []
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", lambda self, host, port, *args: received.append(host) or "stream")
    assert PinnedSyncBackend("tools.example.test", ["93.184.216.34"]).connect_tcp("tools.example.test", 443) == "stream"
    assert received == ["93.184.216.34"]
    with pytest.raises(PlatformError):
        PinnedSyncBackend("tools.example.test", ["93.184.216.34"]).connect_tcp("other", 443)
