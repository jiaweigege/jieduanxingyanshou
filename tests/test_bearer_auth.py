from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.auth import (
    InvalidToken,
    MissingToken,
    authenticate_access_token,
    cleanup_expired_auth_tokens,
    decode_access_token,
    issue_access_token,
    parse_bearer_header,
    revoke_auth_token,
)
from app.models import AuthToken, ClassRoom, User
from tests.conftest import login


TEST_KEY = "test-token-signing-key-that-is-long-enough"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"TOKEN_SIGNING_KEY": None}, "TOKEN_SIGNING_KEY"),
        ({"TOKEN_SIGNING_KEY": "change-me"}, "TOKEN_SIGNING_KEY"),
        ({"TOKEN_SIGNING_KEY": "short"}, "TOKEN_SIGNING_KEY"),
        ({"ACCESS_TOKEN_TTL_SECONDS": 0}, "ACCESS_TOKEN_TTL_SECONDS"),
        ({"ACCESS_TOKEN_TTL_SECONDS": "invalid"}, "ACCESS_TOKEN_TTL_SECONDS"),
    ],
)
def test_token_configuration_is_validated(overrides, message):
    config = {
        "SECRET_KEY": "test-secret",
        "TOKEN_SIGNING_KEY": TEST_KEY,
        "TOKEN_ISSUER": "issuer",
        "TOKEN_AUDIENCE": "audience",
    }
    config.update(overrides)
    with pytest.raises(RuntimeError, match=message):
        create_app(config)


def test_auth_token_schema_has_required_indexes(app):
    with app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("auth_tokens")}
        assert {"jti", "user_id", "issued_at", "expires_at", "revoked_at"} <= columns
        indexes = {item["name"] for item in inspect(db.engine).get_indexes("auth_tokens")}
        assert {
            "ix_auth_tokens_user_id",
            "ix_auth_tokens_expires_at",
            "ix_auth_tokens_revoked_at",
        } <= indexes


def test_auth_token_jti_is_unique(app, seed_users):
    with app.app_context():
        now = datetime.now(timezone.utc)
        first = AuthToken(
            jti="duplicate",
            user_id=seed_users["teacher_a_id"],
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        second = AuthToken(
            jti="duplicate",
            user_id=seed_users["student_a_id"],
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        db.session.add_all([first, second])
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_cleanup_removes_only_expired_grants(app, seed_users):
    with app.app_context():
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        records = [
            AuthToken(
                jti="expired",
                user_id=seed_users["teacher_a_id"],
                issued_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            ),
            AuthToken(
                jti="expired-revoked",
                user_id=seed_users["teacher_a_id"],
                issued_at=now - timedelta(hours=2),
                expires_at=now - timedelta(seconds=1),
                revoked_at=now - timedelta(minutes=30),
            ),
            AuthToken(
                jti="future-revoked",
                user_id=seed_users["teacher_a_id"],
                issued_at=now,
                expires_at=now + timedelta(hours=1),
                revoked_at=now,
            ),
            AuthToken(
                jti="future-active",
                user_id=seed_users["teacher_a_id"],
                issued_at=now,
                expires_at=now + timedelta(hours=1),
            ),
        ]
        db.session.add_all(records)
        db.session.commit()
        assert cleanup_expired_auth_tokens(now) == 2
        db.session.commit()
        assert {record.jti for record in AuthToken.query.all()} == {
            "future-revoked",
            "future-active",
        }


def test_issue_access_token_has_deterministic_claims_and_grant(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["teacher_a_id"])
        now = datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
        encoded, grant = issue_access_token(user, now=now)
        db.session.commit()
        payload = jwt.decode(
            encoded,
            TEST_KEY,
            algorithms=["HS256"],
            issuer="campusclaw-test",
            audience="campusclaw-test-client",
            options={"verify_exp": False, "verify_nbf": False, "verify_iat": False},
        )
        assert payload["sub"] == str(user.id)
        assert payload["jti"] == grant.jti
        assert payload["type"] == "access"
        assert payload["exp"] - payload["iat"] == 1800
        assert grant.user_id == user.id


@pytest.mark.parametrize(
    ("value", "exception"),
    [
        (None, MissingToken),
        ("", MissingToken),
        ("Basic abc", InvalidToken),
        ("Bearer", InvalidToken),
        ("Bearer one two", InvalidToken),
        ("Bearer one,Bearer two", InvalidToken),
        ("Bearer ", InvalidToken),
    ],
)
def test_bearer_parser_rejects_missing_and_malformed_values(value, exception):
    with pytest.raises(exception):
        parse_bearer_header(value)


def test_bearer_parser_accepts_case_insensitive_scheme():
    assert parse_bearer_header("bEaReR abc.def.ghi") == "abc.def.ghi"


def _registered_token(app, user_id, payload_overrides=None, algorithm="HS256", key=TEST_KEY):
    now = datetime.now(timezone.utc)
    jti = f"test-{datetime.now().timestamp()}-{len(AuthToken.query.all())}"
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "iss": app.config["TOKEN_ISSUER"],
        "aud": app.config["TOKEN_AUDIENCE"],
        "type": "access",
    }
    payload.update(payload_overrides or {})
    grant = AuthToken(
        jti=jti,
        user_id=user_id,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    db.session.add(grant)
    db.session.commit()
    return jwt.encode(payload, key, algorithm=algorithm), grant


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "wrong"},
        {"aud": "wrong"},
        {"type": "refresh"},
        {"nbf": datetime.now(timezone.utc) + timedelta(minutes=5)},
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ],
)
def test_invalid_claims_are_rejected(app, seed_users, overrides):
    with app.app_context():
        encoded, _ = _registered_token(app, seed_users["teacher_a_id"], overrides)
        with pytest.raises(InvalidToken, match="Token is invalid"):
            decode_access_token(encoded)


def test_missing_required_claim_wrong_algorithm_and_tampering_are_rejected(
    app, seed_users
):
    with app.app_context():
        encoded, _ = _registered_token(app, seed_users["teacher_a_id"], {"exp": None})
        with pytest.raises(InvalidToken):
            decode_access_token(encoded)

        encoded, _ = _registered_token(
            app,
            seed_users["teacher_a_id"],
            algorithm="HS512",
            key=TEST_KEY * 2,
        )
        with pytest.raises(InvalidToken):
            decode_access_token(encoded)

        valid, _ = _registered_token(app, seed_users["teacher_a_id"])
        head, body, signature = valid.split(".")
        tampered = f"{head}.{body[:-1]}A.{signature}"
        with pytest.raises(InvalidToken):
            decode_access_token(tampered)


def test_authentication_requires_matching_active_grant(app, seed_users):
    with app.app_context():
        encoded, grant = _registered_token(app, seed_users["teacher_a_id"])
        user, active = authenticate_access_token(encoded)
        assert user.id == seed_users["teacher_a_id"]
        assert active.id == grant.id

        revoke_auth_token(active)
        db.session.commit()
        with pytest.raises(InvalidToken):
            authenticate_access_token(encoded)


def test_missing_grant_and_deleted_user_invalidate_tokens(app, seed_users):
    with app.app_context():
        encoded, grant = _registered_token(app, seed_users["teacher_a_id"])
        db.session.delete(grant)
        db.session.commit()
        with pytest.raises(InvalidToken):
            authenticate_access_token(encoded)

        class_room = db.session.get(ClassRoom, seed_users["class_a_id"])
        disposable = User(
            username="disposable",
            role="student",
            class_id=class_room.id,
            password_hash="unused",
        )
        disposable.password = "password"
        db.session.add(disposable)
        db.session.commit()
        encoded, _ = issue_access_token(disposable)
        db.session.commit()
        db.session.delete(disposable)
        db.session.commit()
        with pytest.raises(InvalidToken):
            authenticate_access_token(encoded)


def test_expiry_is_deterministic_without_waiting(app, seed_users):
    with app.app_context():
        now = datetime.now(timezone.utc)
        user = db.session.get(User, seed_users["teacher_a_id"])
        encoded, _ = issue_access_token(user, now=now)
        db.session.commit()
        with pytest.raises(InvalidToken):
            authenticate_access_token(
                encoded,
                now=now + timedelta(seconds=app.config["ACCESS_TOKEN_TTL_SECONDS"] + 1),
            )


def test_two_tokens_are_revoked_independently(client, seed_users):
    first = login(client, "teacher_a", "teacher-password").get_json()["access_token"]
    second = login(client, "teacher_a", "teacher-password").get_json()["access_token"]

    response = client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {first}"}
    )
    assert response.status_code == 200
    assert client.get(
        "/api/me", headers={"Authorization": f"Bearer {first}"}
    ).status_code == 401
    assert client.get(
        "/api/me", headers={"Authorization": f"Bearer {second}"}
    ).status_code == 200


def test_token_endpoint_contract_and_invalid_credentials(client, seed_users):
    response = client.post(
        "/api/auth/token",
        json={"username": "teacher_a", "password": "teacher-password"},
    )
    assert response.status_code == 200
    assert set(response.get_json()) == {"access_token", "token_type", "expires_in"}
    assert "refresh_token" not in response.get_json()

    for payload in (
        {},
        {"username": "teacher_a"},
        {"username": "unknown", "password": "wrong"},
        {"username": "teacher_a", "password": "wrong"},
    ):
        rejected = client.post("/api/auth/token", json=payload)
        assert rejected.status_code == 401
        assert rejected.get_json() == {"error": "invalid_credentials"}


@pytest.mark.parametrize(
    "header",
    ["Basic abc", "Bearer", "Bearer one two", "Bearer one,Bearer two"],
)
def test_api_rejects_malformed_authorization(client, header):
    response = client.get("/api/me", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid_token"}


def test_api_ignores_session_cookie_and_tokens_outside_header(client, seed_users):
    token = login(client, "teacher_a", "teacher-password").get_json()["access_token"]
    client.environ_base.pop("HTTP_AUTHORIZATION", None)
    with client.session_transaction() as session:
        session["user_id"] = seed_users["teacher_a_id"]

    for response in (
        client.get("/api/me"),
        client.get(f"/api/me?access_token={token}"),
        client.get("/api/me", headers={"X-Access-Token": token}),
        client.get("/api/me", json={"access_token": token}),
    ):
        assert response.status_code == 401
        assert response.get_json() == {"error": "missing_token"}


def test_database_identity_overrides_extra_token_claims(client, app, seed_users):
    with app.app_context():
        encoded, _ = _registered_token(
            app,
            seed_users["student_a_id"],
            {"role": "teacher", "class_id": seed_users["class_b_id"]},
        )
    response = client.get(
        "/api/me", headers={"Authorization": f"Bearer {encoded}"}
    )
    assert response.status_code == 200
    assert response.get_json()["role"] == "student"
    assert response.get_json()["class"]["id"] == seed_users["class_a_id"]


def test_database_role_change_applies_to_existing_token(client, app, seed_users):
    token = login(client, "teacher_a", "teacher-password").get_json()["access_token"]
    with app.app_context():
        user = db.session.get(User, seed_users["teacher_a_id"])
        user.role = "student"
        db.session.commit()
    response = client.post(
        "/api/materials/upload",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_public_shell_and_login_do_not_expose_identity_or_token(client, seed_users):
    token = login(client, "teacher_a", "teacher-password").get_json()["access_token"]
    for path in ("/login", "/materials"):
        response = client.get(path)
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "teacher_a" not in body
        assert "A班" not in body
        assert token not in body
    assert client.post("/login").status_code == 405


def test_token_response_does_not_set_authentication_cookie(client, seed_users):
    response = client.post(
        "/api/auth/token",
        json={"username": "teacher_a", "password": "teacher-password"},
    )
    assert response.status_code == 200
    assert "Set-Cookie" not in response.headers


def test_invalid_token_response_and_logs_do_not_echo_secrets(
    client, seed_users, caplog
):
    valid = login(client, "teacher_a", "teacher-password").get_json()["access_token"]
    bad = valid[:-4] + "xxxx"
    response = client.get(
        "/api/me", headers={"Authorization": f"Bearer {bad}"}
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid_token"}
    assert valid not in response.get_data(as_text=True)
    assert bad not in response.get_data(as_text=True)
    assert TEST_KEY not in response.get_data(as_text=True)
    assert valid not in caplog.text
    assert bad not in caplog.text
    assert TEST_KEY not in caplog.text


def test_token_grant_survives_application_restart(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["teacher_a_id"])
        encoded, _ = issue_access_token(user)
        db.session.commit()

    restarted = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "TOKEN_SIGNING_KEY": TEST_KEY,
            "TOKEN_ISSUER": "campusclaw-test",
            "TOKEN_AUDIENCE": "campusclaw-test-client",
            "ACCESS_TOKEN_TTL_SECONDS": 1800,
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"],
            "UPLOAD_FOLDER": app.config["UPLOAD_FOLDER"],
        }
    )
    with restarted.app_context():
        user, grant = authenticate_access_token(encoded)
        assert user.id == seed_users["teacher_a_id"]
        assert grant.revoked_at is None
        db.session.remove()
        db.engine.dispose()


def test_frontend_uses_session_storage_and_bearer_requests(app):
    static = Path(app.root_path) / "static" / "js"
    auth_js = (static / "auth.js").read_text()
    app_js = (static / "app.js").read_text()
    assert "sessionStorage" in auth_js
    assert "localStorage" not in auth_js
    assert "document.cookie" not in auth_js
    assert 'headers.set("Authorization", `Bearer ${token}`)' in auth_js
    assert 'xhr.setRequestHeader("Authorization", `Bearer ${token}`)' in app_js
    assert "URL.createObjectURL" in app_js
    assert "URL.revokeObjectURL" in app_js
    assert 'href="/api/materials/' not in app_js
