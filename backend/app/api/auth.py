"""Registration, login, current-user, and logout.

Tokens are stateless JWTs (see app/auth/security.py) -- there is no
server-side session to revoke, so /auth/logout is a 200 the client uses as
a signal to discard its stored token, not a real server-side invalidation.
A future phase could add a token-blocklist table if that matters before
a token's natural expiry; not built here per the "don't overengineer"
scope of this phase.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    SUPPORTED_CURRENCIES,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserLogin,
    UserPublic,
    UserSettingsUpdate,
)
from app.auth.security import (
    PASSWORD_RESET_TOKEN_TTL_MINUTES,
    create_access_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
)
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.notifications.email import EmailNotConfiguredError, EmailSendError, send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.") from exc
    db.refresh(user)

    settings = get_settings()
    token = create_access_token(user.id, settings)
    return Token(access_token=token, user=UserPublic.model_validate(user))


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is inactive.")

    settings = get_settings()
    token = create_access_token(user.id, settings)
    return Token(access_token=token, user=UserPublic.model_validate(user))


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.patch("/me/settings", response_model=UserPublic)
def update_settings(
    payload: UserSettingsUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserPublic:
    if payload.currency is not None:
        if payload.currency not in SUPPORTED_CURRENCIES:
            raise HTTPException(status_code=422, detail=f"Unsupported currency '{payload.currency}'.")
        current_user.currency = payload.currency
    if payload.decimal_places is not None:
        current_user.decimal_places = payload.decimal_places
    db.commit()
    db.refresh(current_user)
    return UserPublic.model_validate(current_user)


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)) -> dict:
    return {"status": "ok", "detail": "Token discarded client-side. No server-side session to end."}


_GENERIC_FORGOT_PASSWORD_RESPONSE = {
    "status": "ok",
    "detail": "If an account exists for that email, a password reset link has been sent.",
}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """Always returns the same generic response whether or not the email is
    registered, and whether or not sending the email actually succeeded --
    letting either leak through the response would tell a caller which
    emails have accounts (a real information-disclosure issue), so a send
    failure is only ever visible server-side (Cloud Run logs), never in
    the API response."""
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None or not user.is_active:
        return _GENERIC_FORGOT_PASSWORD_RESPONSE

    settings = get_settings()
    raw_token = generate_password_reset_token()
    user.reset_token_hash = hash_password_reset_token(raw_token)
    user.reset_token_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=PASSWORD_RESET_TOKEN_TTL_MINUTES
    )
    db.commit()

    frontend_base = settings.frontend_base_url or (settings.cors_origins[0] if settings.cors_origins else "")
    reset_url = f"{frontend_base.rstrip('/')}/reset-password?token={raw_token}"

    try:
        send_password_reset_email(settings=settings, to_email=user.email, reset_url=reset_url)
    except (EmailNotConfiguredError, EmailSendError) as exc:
        print(f"[forgot-password] email send failed for user {user.id}: {exc}")  # noqa: T201 -- Cloud Run log, not a client-visible response

    return _GENERIC_FORGOT_PASSWORD_RESPONSE


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    token_hash = hash_password_reset_token(payload.token)
    user = db.query(User).filter(User.reset_token_hash == token_hash).first()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if user is None or user.reset_token_expires_at is None or user.reset_token_expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.reset_token_hash = None
    user.reset_token_expires_at = None
    db.commit()

    return {"status": "ok", "detail": "Password updated. You can now sign in with your new password."}
