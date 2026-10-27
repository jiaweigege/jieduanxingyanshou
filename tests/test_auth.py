from werkzeug.security import check_password_hash

from app import db
from app.models import User
from tests.conftest import login


def test_valid_teacher_login(client, seed_users):
    response = login(client, "teacher_a", "teacher-password")
    assert response.status_code == 200
    assert response.get_json()["token_type"] == "Bearer"
    assert response.get_json()["expires_in"] == 1800
    assert response.get_json()["access_token"]


def test_valid_student_login(client, seed_users):
    response = login(client, "student_a", "student-password")
    assert response.status_code == 200
    assert response.get_json()["token_type"] == "Bearer"


def test_invalid_login(client, seed_users):
    response = login(client, "teacher_a", "wrong-password")
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid_credentials"}
    assert "teacher" not in response.get_data(as_text=True)


def test_logout(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.get_json() == {"status": "logged_out"}

    protected = client.get("/api/me")
    assert protected.status_code == 401
    assert protected.get_json() == {"error": "invalid_token"}


def test_unauthenticated_materials_returns_public_shell(client):
    response = client.get("/materials")
    assert response.status_code == 200
    assert b"authenticated-content" in response.data
    assert b"teacher_a" not in response.data


def test_passwords_are_hashed(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["teacher_a_id"])
        assert user.password_hash != "teacher-password"
        assert check_password_hash(user.password_hash, "teacher-password")
