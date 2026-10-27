import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app import create_app, db
from app.models import ClassRoom, KnowledgeEntry, Material, User
from app.retrieval import initialize_search_index, replace_entry_index


def stream_transport(_url, _payload, _headers, _timeout):
    for content in ("先列出已知条件并标出关键词，", "再考虑资料里的下一步思路。[1]"):
        yield b"data: " + json.dumps(
            {"choices": [{"delta": {"content": content}}]}, ensure_ascii=False
        ).encode() + b"\n\n"
    yield b"data: [DONE]\n\n"


class CaseContext:
    def __init__(self, app, ids):
        self.app = app
        self.client = app.test_client()
        self.ids = ids

    def login(self, username, password):
        response = self.client.post(
            "/api/auth/token", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.get_json()
        token = response.get_json()["access_token"]
        self.client.environ_base["HTTP_AUTHORIZATION"] = "Bearer " + token
        return token

    def logout(self):
        self.client.environ_base.pop("HTTP_AUTHORIZATION", None)

    def events(self, response):
        blocks = response.get_data(as_text=True).strip().split("\n\n")
        result = []
        for block in blocks:
            lines = block.split("\n")
            result.append((lines[0][7:], json.loads(lines[1][6:])))
        return result


@contextmanager
def isolated_case():
    with tempfile.TemporaryDirectory(prefix="campusclaw-apitest-") as temp:
        root = Path(temp)
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "apitest-secret",
            "TOKEN_SIGNING_KEY": "apitest-signing-key-long-enough-for-jwt",
            "TOKEN_ISSUER": "campusclaw-apitest",
            "TOKEN_AUDIENCE": "campusclaw-apitest-client",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(root / "case.db"),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "ZHIPU_STREAM_TRANSPORT": stream_transport,
        })
        with app.app_context():
            db.create_all()
            initialize_search_index()
            classes = [ClassRoom(name="A班"), ClassRoom(name="B班")]
            db.session.add_all(classes)
            db.session.flush()
            users = []
            for name, role, class_id in (
                ("teacher_a", "teacher", classes[0].id),
                ("student_a", "student", classes[0].id),
                ("student_a2", "student", classes[0].id),
                ("student_b", "student", classes[1].id),
            ):
                user = User(username=name, role=role, class_id=class_id)
                user.password = "test-password"
                users.append(user)
            db.session.add_all(users)
            db.session.flush()
            materials = []
            for class_id, title, filename, body, uploader in (
                (classes[0].id, "A班公式", "a.txt", "三角形面积公式：底乘高除以二。\n", users[0]),
                (classes[1].id, "B班秘密", "b.txt", "仅B班可见的独特短语。\n", users[0]),
            ):
                material = Material(
                    title=title, filename=filename, stored_filename=filename,
                    content_type="text/plain", size_bytes=len(body.encode()),
                    class_id=class_id, uploader_id=uploader.id,
                )
                db.session.add(material)
                db.session.flush()
                entry = KnowledgeEntry(
                    material_id=material.id, class_id=class_id, body=body
                )
                db.session.add(entry)
                db.session.flush()
                replace_entry_index(entry)
                materials.append(material)
                (root / "uploads" / filename).write_text(body, encoding="utf-8")
            db.session.commit()
            ids = {
                "class_a": classes[0].id, "class_b": classes[1].id,
                "teacher_a": users[0].id, "student_a": users[1].id,
                "student_a2": users[2].id, "student_b": users[3].id,
                "material_a": materials[0].id, "material_b": materials[1].id,
            }
            try:
                yield CaseContext(app, ids)
            finally:
                db.session.remove()
                db.engine.dispose()
