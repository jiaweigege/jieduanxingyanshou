from app import db
from app.models import Material
from tests.conftest import login


def test_api_me_requires_authentication(client):
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.get_json() == {"error": "missing_token"}


def test_api_me_returns_current_user(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = client.get("/api/me")
    assert response.status_code == 200
    data = response.get_json()
    assert data["username"] == "teacher_a"
    assert data["role"] == "teacher"
    assert data["class"]["name"] == "A班"


def test_api_material_list_is_class_scoped(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get("/api/materials")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["materials"]) == 1
    assert data["materials"][0]["title"] == "A班笔记"


def test_api_material_detail_is_class_scoped(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get(f"/api/materials/{seed_users['material_b_id']}")
    assert response.status_code == 404


def test_api_material_file_is_class_scoped(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get(f"/api/materials/{seed_users['material_b_id']}/file")
    assert response.status_code == 404


def test_static_uploads_is_not_exposed(client, seed_users):
    response = client.get("/uploads/class-a.md")
    assert response.status_code == 404


def test_material_search_is_class_scoped(client, seed_users):
    login(client, "student_a", "student-password")
    response = client.get("/api/materials?q=A班")
    assert response.status_code == 200
    data = response.get_json()
    assert all(item["class"] == "A班" for item in data["materials"])
