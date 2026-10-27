import pytest

from app import create_app


BASE = {"SECRET_KEY": "test", "TOKEN_SIGNING_KEY": "t" * 40,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}


def test_platform_off_by_default_keeps_old_shell():
    app = create_app(BASE)
    assert app.config["AI_PLATFORM_ENABLED"] is False
    assert app.test_client().get("/materials").status_code == 200
    assert app.config["AI_MAX_MODEL_CALLS"] == 6
    assert app.config["AI_MODEL_CAPABILITIES"][app.config["ZHIPU_MODEL"]] == {"tools": False}


@pytest.mark.parametrize("override", [
    {"AI_PLATFORM_ENABLED": "yes"}, {"AI_INPUT_BUDGET": 0},
    {"AI_TOOL_TIMEOUT": "nan"}, {"AI_TRACE_DAYS": True},
    {"AI_MODEL_CAPABILITIES": {"glm": {"tools": "yes"}}},
    {"AI_MODEL_CAPABILITIES": {"glm": {"tools": True, "unknown": True}}},
    {"AI_TOOL_ALLOWED_HOSTS": ["https://example.com"]},
    {"AI_CREDENTIAL_REFERENCES": {"x": {"value": "not-allowed"}}},
])
def test_bad_platform_configuration_fails(override):
    with pytest.raises(RuntimeError, match="AI_"):
        create_app({**BASE, **override})
