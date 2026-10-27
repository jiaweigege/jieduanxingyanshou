from io import BytesIO

from app import db
from app.models import Material
from tests.conftest import login


def _upload(client, title="新资料", filename="new.md", content=b"hello"):
    data = {
        "title": title,
        "file": (BytesIO(content), filename, "text/markdown"),
    }
    return client.post(
        "/api/materials/upload",
        data=data,
        content_type="multipart/form-data",
    )


def test_student_upload_returns_403(client, seed_users):
    login(client, "student_a", "student-password")
    response = _upload(client)
    assert response.status_code == 403

    with client.application.app_context():
        assert Material.query.count() == 2


def test_teacher_upload_persists_material(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = _upload(client)
    assert response.status_code == 201

    with client.application.app_context():
        material = Material.query.filter_by(title="新资料").one()
        assert material.class_id == seed_users["class_a_id"]
        assert material.uploader_id == seed_users["teacher_a_id"]
        assert material.filename == "new.md"
        assert material.size_bytes == 5


def test_material_list_is_class_scoped(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get("/api/materials")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["materials"]) == 1
    assert data["materials"][0]["title"] == "A班笔记"


def test_cross_class_direct_access_is_forbidden(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get(f"/api/materials/{seed_users['material_b_id']}")
    assert response.status_code == 404


def test_client_supplied_class_cannot_override_boundary(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get("/api/materials?class_id=999")
    assert response.status_code == 200
    data = response.get_json()
    assert all(item["class"] == "A班" for item in data["materials"])


def test_uploaded_material_is_visible_in_same_class_list(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    upload_response = _upload(client, title="新上传资料")
    assert upload_response.status_code == 201

    list_response = client.get("/api/materials")
    assert list_response.status_code == 200
    titles = [item["title"] for item in list_response.get_json()["materials"]]
    assert "新上传资料" in titles
