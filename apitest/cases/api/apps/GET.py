from app.platform_resources import initialize_platform


def run(ctx):
    ctx.app.config["AI_PLATFORM_ENABLED"] = True
    with ctx.app.app_context():
        initialize_platform()
    ctx.login("student_a", "test-password")
    response = ctx.client.get("/api/apps")
    assert response.status_code == 200
    assert len(response.get_json()["apps"]) == 3
    assert {a["kind"] for a in response.get_json()["apps"]} == {"chat", "knowledge", "solver"}
