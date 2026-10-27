from app import db
from app.models import AuthToken, User


def run(context):
    response = context.client.post("/api/auth/token", json={
        "username": "student_a", "password": "test-password",
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["token_type"] == "Bearer"
    assert isinstance(data["access_token"], str) and data["access_token"]
    assert data["expires_in"] > 0
    with context.app.app_context():
        student = User.query.filter_by(username="student_a").one()
        grant = AuthToken.query.filter_by(user_id=student.id).one()
        assert grant.revoked_at is None
    invalid = context.client.post("/api/auth/token", json={
        "username": "student_a", "password": "wrong",
    })
    assert invalid.status_code == 401
    assert invalid.get_json() == {"error": "invalid_credentials"}
