import json
import re


def test_openapi_covers_api_routes_and_security(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.get_json()
    assert spec["openapi"].startswith("3.1.")
    assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert spec["paths"]["/api/auth/token"]["post"]["security"] == []
    for rule in client.application.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        documented = re.sub(r"<(?:int:)?([^>]+)>", r"{\1}", rule.rule)
        assert documented in spec["paths"], rule.rule
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            operation = spec["paths"][documented][method.lower()]
            assert operation["responses"], (rule.rule, method)
            assert operation["security"] == [{"BearerAuth": []}] or documented == "/api/auth/token"
            if documented != "/api/auth/token":
                assert "401" in operation["responses"]
    stream = spec["paths"]["/api/solver/sessions/{session_id}/messages"]["post"]
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    assert all(name in stream["description"] for name in ("sources", "delta", "done", "error"))


def test_swagger_is_public_and_self_hosted(client):
    response = client.get("/docs")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'url: "/openapi.json"' in html
    assert "/static/swagger-ui/swagger-ui-bundle.js" in html
    assert "cdn." not in html
    assert client.get("/static/swagger-ui/swagger-ui-bundle.js").status_code == 200
    assert client.get("/static/swagger-ui/swagger-ui.css").status_code == 200
