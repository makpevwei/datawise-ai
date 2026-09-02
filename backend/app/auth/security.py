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
    # A real access token never carries a `purpose` claim -- only
    # create_oauth_state_token does. Without this check the rejection below
    # is one-directional: decode_oauth_state_token already refuses a real
    # access token (wrong purpose), but a leaked state token would
    # otherwise decode fine here and work as a bearer token against every
    # get_current_user-gated endpoint for its whole (short) TTL. Reject any
    # token minted for a different purpose, symmetrically.
    if payload.get("purpose") is not None:
        raise TokenError("Token was not issued as an access token.")
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token has no subject.")
    return user_id


# How long a Google OAuth `state` param stays valid -- the whole
# connect -> Google consent screen -> callback round trip should take at
# most a couple of minutes; kept short since this is a bearer credential
# for the duration it's valid.
OAUTH_STATE_TOKEN_TTL_MINUTES = 10


def create_oauth_state_token(user_id: str, settings: Settings) -> str:
    """Signed, short-lived JWT carried through Google's OAuth `state` param
    -- this is what lets /integrations/google/callback know which DataWise
    user is completing the flow, since Google's redirect is a plain browser
    navigation and can't carry our own Authorization header the way
    get_current_user expects. A distinct `purpose` claim (checked on
    decode) keeps this from ever being accepted in place of a real access
    token, or vice versa, even though both are signed with the same key."""
    if not settings.jwt_secret_key:
        raise TokenError("JWT_SECRET_KEY is not configured.")
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "purpose": "oauth_state",
        "nonce": secrets.token_urlsafe(8),
        "iat": now,
        "exp": now + timedelta(minutes=OAUTH_STATE_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_oauth_state_token(token: str, settings: Settings) -> str:
    """Returns the user id encoded in the state token, or raises TokenError
    -- including if it's a well-formed, validly-signed access token that
    simply wasn't issued for this purpose (see create_oauth_state_token)."""
    if not settings.jwt_secret_key:
        raise TokenError("JWT_SECRET_KEY is not configured.")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("purpose") != "oauth_state":
        raise TokenError("Token was not issued as an OAuth state token.")
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token has no subject.")
    return user_id
