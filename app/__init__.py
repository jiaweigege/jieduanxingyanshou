from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if dbapi_connection.__class__.__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is required and must be set in the environment")

    token_key = app.config.get("TOKEN_SIGNING_KEY")
    placeholder_prefixes = ("change-me", "replace-", "your-")
    if (
        not isinstance(token_key, str)
        or len(token_key) < 32
        or token_key.strip().lower().startswith(placeholder_prefixes)
    ):
        raise RuntimeError(
            "TOKEN_SIGNING_KEY is required and must be at least 32 non-placeholder characters"
        )

    try:
        token_ttl = int(app.config.get("ACCESS_TOKEN_TTL_SECONDS", 1800))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("ACCESS_TOKEN_TTL_SECONDS must be a positive integer") from exc
    if token_ttl <= 0:
        raise RuntimeError("ACCESS_TOKEN_TTL_SECONDS must be a positive integer")
    app.config["ACCESS_TOKEN_TTL_SECONDS"] = token_ttl

    if not app.config.get("TOKEN_ISSUER") or not app.config.get("TOKEN_AUDIENCE"):
        raise RuntimeError("TOKEN_ISSUER and TOKEN_AUDIENCE are required")

    api_url = app.config.get("ZHIPU_API_URL")
    if not isinstance(api_url, str) or not api_url.startswith("https://"):
        raise RuntimeError("ZHIPU_API_URL must be an HTTPS URL")
    if not isinstance(app.config.get("ZHIPU_MODEL"), str) or not app.config[
        "ZHIPU_MODEL"
    ].strip():
        raise RuntimeError("ZHIPU_MODEL must be a non-empty string")

    try:
        timeout = float(app.config.get("ZHIPU_TIMEOUT_SECONDS", 20))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("ZHIPU_TIMEOUT_SECONDS must be positive") from exc
    if timeout <= 0:
        raise RuntimeError("ZHIPU_TIMEOUT_SECONDS must be positive")
    app.config["ZHIPU_TIMEOUT_SECONDS"] = timeout

    for key, default in (
        ("KNOWLEDGE_QA_MAX_QUESTION_CHARS", 500),
        ("KNOWLEDGE_QA_MAX_CONTEXT_CHARS", 6000),
        ("KNOWLEDGE_QA_MAX_OUTPUT_TOKENS", 512),
    ):
        try:
            value = int(app.config.get(key, default))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{key} must be a positive integer") from exc
        if value <= 0:
            raise RuntimeError(f"{key} must be a positive integer")
        app.config[key] = value

    from app.platform_config import configure_platform
    configure_platform(app)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from app.cli import register_commands
    from app.routes import main_bp

    app.register_blueprint(main_bp)
    from app.platform_routes import platform_bp
    app.register_blueprint(platform_bp)
    register_commands(app)

    return app
