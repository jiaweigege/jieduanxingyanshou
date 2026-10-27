from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from flask import current_app

from app import db
from app.models import AuthToken, User


ALGORITHM = "HS256"
REQUIRED_CLAIMS = ("sub", "jti", "iat", "nbf", "exp", "iss", "aud", "type")


class AuthError(ValueError):
    code = "invalid_token"


class MissingToken(AuthError):
    code = "missing_token"


class InvalidToken(AuthError):
    code = "invalid_token"


def utc_now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def cleanup_expired_auth_tokens(now=None):
    current = _as_utc(now or utc_now())
    result = db.session.execute(
        db.delete(AuthToken).where(AuthToken.expires_at <= current)
    )
    return result.rowcount or 0


def issue_access_token(user, now=None):
    current = _as_utc(now or utc_now())
    expires = current + timedelta(
        seconds=current_app.config["ACCESS_TOKEN_TTL_SECONDS"]
    )
    jti = uuid4().hex
    cleanup_expired_auth_tokens(current)
    grant = AuthToken(
        jti=jti,
        user_id=user.id,
        issued_at=current,
        expires_at=expires,
    )
    db.session.add(grant)
    db.session.flush()

    payload = {
        "sub": str(user.id),
        "jti": jti,
        "iat": current,
        "nbf": current,
        "exp": expires,
        "iss": current_app.config["TOKEN_ISSUER"],
        "aud": current_app.config["TOKEN_AUDIENCE"],
        "type": "access",
    }
    encoded = jwt.encode(
        payload,
        current_app.config["TOKEN_SIGNING_KEY"],
        algorithm=ALGORITHM,
    )
    return encoded, grant


def parse_bearer_header(value):
    if value is None or not value.strip():
        raise MissingToken("Bearer token is required")
    if "," in value:
        raise InvalidToken("Authorization header is malformed")
    parts = value.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise InvalidToken("Authorization header is malformed")
    return parts[1]


def _numeric_claim(payload, name):
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidToken("Token claim is invalid")
    return float(value)


def decode_access_token(encoded, now=None):
    try:
        payload = jwt.decode(
            encoded,
            current_app.config["TOKEN_SIGNING_KEY"],
            algorithms=[ALGORITHM],
            issuer=current_app.config["TOKEN_ISSUER"],
            audience=current_app.config["TOKEN_AUDIENCE"],
            options={
                "require": list(REQUIRED_CLAIMS),
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken("Token is invalid") from exc

    current_timestamp = _as_utc(now or utc_now()).timestamp()
    issued_at = _numeric_claim(payload, "iat")
    not_before = _numeric_claim(payload, "nbf")
    expires_at = _numeric_claim(payload, "exp")
    if issued_at > current_timestamp or not_before > current_timestamp:
        raise InvalidToken("Token is invalid")
    if expires_at <= current_timestamp:
        raise InvalidToken("Token is invalid")
    if payload.get("type") != "access":
        raise InvalidToken("Token is invalid")
    if not isinstance(payload.get("jti"), str) or not payload["jti"]:
        raise InvalidToken("Token is invalid")
    if not isinstance(payload.get("sub"), str) or not payload["sub"].isdigit():
        raise InvalidToken("Token is invalid")
    return payload


def authenticate_access_token(encoded, now=None):
    current = _as_utc(now or utc_now())
    payload = decode_access_token(encoded, now=current)
    user_id = int(payload["sub"])
    grant = db.session.execute(
        db.select(AuthToken).where(
            AuthToken.jti == payload["jti"],
            AuthToken.user_id == user_id,
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at > current,
        )
    ).scalar_one_or_none()
    if grant is None:
        raise InvalidToken("Token is invalid")
    user = db.session.get(User, user_id)
    if user is None:
        raise InvalidToken("Token is invalid")
    return user, grant


def revoke_auth_token(grant, now=None):
    if grant.revoked_at is None:
        grant.revoked_at = _as_utc(now or utc_now())
    return grant
