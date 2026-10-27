import pytest

from app import create_app, db
from app.models import ClassRoom, KnowledgeEntry, Material, User
from app.retrieval import initialize_search_index
from app.retrieval import replace_entry_index


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "TOKEN_SIGNING_KEY": "test-token-signing-key-that-is-long-enough",
            "TOKEN_ISSUER": "campusclaw-test",
            "TOKEN_AUDIENCE": "campusclaw-test-client",
            "ACCESS_TOKEN_TTL_SECONDS": 1800,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test.db",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "MAX_CONTENT_LENGTH": 1024 * 1024,
        }
    )

    with app.app_context():
        db.create_all()
        initialize_search_index()
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_users(app):
    with app.app_context():
        class_a = ClassRoom(name="A班")
        class_b = ClassRoom(name="B班")
        db.session.add_all([class_a, class_b])
        db.session.commit()

        teacher_a = User(
            username="teacher_a",
            role="teacher",
            class_id=class_a.id,
            password_hash="not-used",
        )
        teacher_a.password = "teacher-password"
        student_a = User(
            username="student_a",
            role="student",
            class_id=class_a.id,
            password_hash="not-used",
        )
        student_a.password = "student-password"
        teacher_b = User(
            username="teacher_b",
            role="teacher",
            class_id=class_b.id,
            password_hash="not-used",
        )
        teacher_b.password = "teacher-password"
        student_b = User(
            username="student_b",
            role="student",
            class_id=class_b.id,
            password_hash="not-used",
        )
        student_b.password = "student-password"
        db.session.add_all([teacher_a, student_a, teacher_b, student_b])
        db.session.commit()

        material_a = Material(
            title="A班笔记",
            filename="class-a.md",
            stored_filename="class-a.md",
            content_type="text/markdown",
            size_bytes=32,
            class_id=class_a.id,
            uploader_id=teacher_a.id,
        )
        material_b = Material(
            title="B班笔记",
            filename="class-b.txt",
            stored_filename="class-b.txt",
            content_type="text/plain",
            size_bytes=32,
            class_id=class_b.id,
            uploader_id=teacher_b.id,
        )
        db.session.add_all([material_a, material_b])
        db.session.commit()

        entry_a = KnowledgeEntry(
            material_id=material_a.id,
            class_id=class_a.id,
            body="# A班笔记\n\n- 甲\n- 乙\n",
        )
        entry_b = KnowledgeEntry(
            material_id=material_b.id,
            class_id=class_b.id,
            body="B班笔记\n",
        )
        db.session.add_all([entry_a, entry_b])
        db.session.commit()
        replace_entry_index(entry_a)
        replace_entry_index(entry_b)
        db.session.commit()

        result = {
            "class_a_id": class_a.id,
            "class_b_id": class_b.id,
            "teacher_a_id": teacher_a.id,
            "student_a_id": student_a.id,
            "teacher_b_id": teacher_b.id,
            "student_b_id": student_b.id,
            "material_a_id": material_a.id,
            "material_b_id": material_b.id,
        }

    return result


def login(client, username, password):
    response = client.post(
        "/api/auth/token", json={"username": username, "password": password}
    )
    if response.status_code == 200:
        token = response.get_json()["access_token"]
        client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return response
