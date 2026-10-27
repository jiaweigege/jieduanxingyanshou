from io import BytesIO
from pathlib import Path

import pytest

from app import db
from app.models import KnowledgeEntry, Material
from tests.conftest import login


def _upload(client, title, filename, content, content_type="text/markdown"):
    return client.post(
        "/api/materials/upload",
        data={
            "title": title,
            "file": (BytesIO(content), filename, content_type),
        },
        content_type="multipart/form-data",
    )


def test_knowledge_entry_is_linked_to_material(app, seed_users):
    with app.app_context():
        material = db.session.get(Material, seed_users["material_a_id"])
        assert material.knowledge_entry is not None
        assert material.knowledge_entry.class_id == seed_users["class_a_id"]
        assert material.knowledge_entry.material_id == material.id


def test_upload_creates_material_and_knowledge_entry(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = _upload(client, "New notes", "new.md", b"# New notes\n")
    assert response.status_code == 201

    with client.application.app_context():
        material = Material.query.filter_by(title="New notes").one()
        assert material.knowledge_entry is not None
        assert material.knowledge_entry.body == "# New notes\n"
        assert material.knowledge_entry.class_id == seed_users["class_a_id"]


def test_unsupported_extension_is_rejected(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = _upload(client, "Bad file", "bad.pdf", b"%PDF", "application/pdf")
    assert response.status_code == 400
    assert response.get_json()["error"] == "仅支持 .txt 和 .md 文件"

    with client.application.app_context():
        assert Material.query.filter_by(title="Bad file").count() == 0
        assert KnowledgeEntry.query.count() == 2


def test_oversized_file_is_rejected(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    content = b"x" * (1024 * 1024 + 1)
    response = _upload(client, "Too large", "large.md", content)
    assert response.status_code == 413

    with client.application.app_context():
        assert Material.query.filter_by(title="Too large").count() == 0
        assert KnowledgeEntry.query.count() == 2


def test_invalid_utf8_leaves_no_residue(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = _upload(client, "Binary", "binary.md", b"\xff\xfe\x00")
    assert response.status_code == 400
    assert response.get_json()["error"] == "文件必须是有效的 UTF-8 文本"

    with client.application.app_context():
        assert Material.query.filter_by(title="Binary").count() == 0
        assert KnowledgeEntry.query.count() == 2
        upload_dir = Path(client.application.config["UPLOAD_FOLDER"])
        assert not any(upload_dir.glob("*binary*"))


def test_persistence_failure_rolls_back_and_removes_file(client, seed_users, monkeypatch):
    login(client, "teacher_a", "teacher-password")

    original_commit = db.session.commit

    def fail_commit():
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = _upload(client, "Fail", "fail.md", b"# Fail\n")
    monkeypatch.setattr(db.session, "commit", original_commit)

    assert response.status_code == 500
    with client.application.app_context():
        db.session.rollback()
        assert Material.query.filter_by(title="Fail").count() == 0
        assert KnowledgeEntry.query.count() == 2
        upload_dir = Path(client.application.config["UPLOAD_FOLDER"])
        assert not any(upload_dir.glob("*fail*"))
