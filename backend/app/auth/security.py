"""Password hashing and JWT issuance/verification.

Stateless bearer tokens (no server-side session table): the JWT's `sub`
claim is the user id, verified against the DB on every request by
get_current_user (app/auth/dependencies.py). "Logout" is therefore a
client-side token discard, not a server-side revocation -- see the
/auth/logout endpoint's docstring.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import Settings


class TokenError(Exception):
    """Raised for any invalid/expired/malformed token -- callers turn this into a 401."""


# How long a forgot-password link stays valid before the user has to
# request a new one.
PASSWORD_RESET_TOKEN_TTL_MINUTES = 60


def generate_password_reset_token() -> str:
    """The raw token emailed to the user -- never stored anywhere as-is,
    see hash_password_reset_token()."""
    return secrets.token_urlsafe(32)


def hash_password_reset_token(token: str) -> str:
    """SHA-256, not bcrypt -- this hashes a high-entropy random token, not a
    human-chosen password, so it doesn't need bcrypt's slow work factor;
    it needs to be a fast, deterministic lookup key for the DB query in
    reset_password() instead."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str, settings: Settings) -> str:
    if not settings.jwt_secret_key:
        raise TokenError("JWT_SECRET_KEY is not configured.")
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> str:
    """Returns the user id encoded in the token, or raises TokenError."""
    if not settings.jwt_secret_key:
        raise TokenError("JWT_SECRET_KEY is not configured.")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token has no subject.")
    return user_id
