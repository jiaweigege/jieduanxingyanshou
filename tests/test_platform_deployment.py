import sqlite3

from app import db, create_app
from app.models import Material, User
from app.platform_models import AiApplication
from app.platform_resources import initialize_platform
from tests.conftest import login


def test_backup_initialize_toggle_and_rollback_on_database_copy(app, client, seed_users, tmp_path):
    backup = tmp_path / "before-platform.db"
    with app.app_context():
        database_path = db.engine.url.database
        before_users, before_materials = User.query.count(), Material.query.count()
        with sqlite3.connect(database_path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        initialize_platform(); initialize_platform()
        assert User.query.count() == before_users and Material.query.count() == before_materials
        assert AiApplication.query.count() == 6
    app.config["AI_PLATFORM_ENABLED"] = False
    login(client, "teacher_a", "teacher-password")
    assert client.get("/api/materials").status_code == 200
    assert client.get("/apps").status_code == 404
    app.config["AI_PLATFORM_ENABLED"] = True
    assert client.get("/api/apps").status_code == 200
    # A rollback copy retains original accounts/materials and old endpoints.
    restored = create_app({"SECRET_KEY": "rollback-test", "TOKEN_SIGNING_KEY": "rollback-test-signing-key-long-enough",
                           "SQLALCHEMY_DATABASE_URI": f"sqlite:///{backup}", "UPLOAD_FOLDER": str(tmp_path / "restored-uploads")})
    with restored.app_context():
        assert User.query.count() == before_users and Material.query.count() == before_materials
    restored_client = restored.test_client()
    login(restored_client, "teacher_a", "teacher-password")
    assert restored_client.get("/api/materials").status_code == 200


def test_init_platform_cli_is_repeatable(app, seed_users):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-platform"]).exit_code == 0
    assert runner.invoke(args=["init-platform"]).exit_code == 0
    with app.app_context():
        assert AiApplication.query.count() == 6
