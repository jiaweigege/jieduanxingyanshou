import json

from app.platform_resources import initialize_platform


def run(ctx):
    ctx.app.config["AI_PLATFORM_ENABLED"] = True
    with ctx.app.app_context():
        initialize_platform()
    ctx.login("student_a", "test-password")
    apps = ctx.client.get("/api/apps").get_json()["apps"]
    application = next(a for a in apps if a["kind"] == "chat")
    response = ctx.client.post("/api/app-conversations", json={"application_id": application["id"], "class_id": ctx.ids["class_b"]})
    assert response.status_code == 201
    conversation_id = response.get_json()["id"]
    def model(_url, body, headers, _timeout):
        assert "messages" in json.loads(body)
        assert headers["Authorization"] == "Bearer temporary-test-key"
        return 200, json.dumps({"choices": [{"message": {"role": "assistant", "content": "离线验证答案"}, "finish_reason": "stop"}]}).encode()
    ctx.app.config["AI_LLM_TRANSPORT"] = model
    result = ctx.client.post(f"/api/app-conversations/{conversation_id}/messages", json={"content": "测试", "api_key": "temporary-test-key", "request_id": "apitest-message"})
    assert result.status_code == 200, result.get_json()
    trace = ctx.client.get("/api/conversation-runs/" + result.get_json()["run_id"]).get_json()
    assert len(trace["calls"]) == 1 and "temporary-test-key" not in json.dumps(trace)
    ctx.login("student_a2", "test-password")
    assert ctx.client.get(f"/api/app-conversations/{conversation_id}").status_code == 404
