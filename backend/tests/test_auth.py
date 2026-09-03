"""Registration, login, current-user, logout, and enforcement of auth on a
protected route. Runs against the real configured DataWise database (see
tests/conftest.py) -- users created here are real rows, cleaned up via the
fake_user-style pattern (each test creates and deletes its own)."""

import uuid
from unittest.mock import patch

from email_validator import EmailNotValidError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.schemas import UserCreate
from app.config import Settings
from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


def test_register_creates_account_and_returns_token():
    email = _unique_email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Ada Lovelace"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["user"]["full_name"] == "Ada Lovelace"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]

    # cleanup
    token = body["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_duplicate_email_is_rejected():
    email = _unique_email()
    payload = {"email": email, "password": "correct horse battery staple", "full_name": "Grace Hopper"}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


def test_password_is_hashed_not_stored_plaintext():
    from app.auth.security import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2")  # bcrypt hash prefix
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_login_succeeds_with_correct_credentials_and_fails_with_wrong_password():
    email = _unique_email()
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Alan Turing"},
    )

    good = client.post("/api/v1/auth/login", json={"email": email, "password": "correct horse battery staple"})
    assert good.status_code == 200
    assert good.json()["access_token"]

    bad = client.post("/api/v1/auth/login", json={"email": email, "password": "not the password"})
    assert bad.status_code == 401


def test_login_with_unknown_email_fails_honestly():
    response = client.post("/api/v1/auth/login", json={"email": _unique_email(), "password": "whatever"})
    assert response.status_code == 401


def test_me_requires_a_valid_token():
    no_token = client.get("/api/v1/auth/me")
    assert no_token.status_code == 401

    bad_token = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert bad_token.status_code == 401


def test_logout_is_reachable_and_requires_auth():
    email = _unique_email()
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Radia Perlman"},
    )
    token = register.json()["access_token"]

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200

    unauthenticated_logout = client.post("/api/v1/auth/logout")
    assert unauthenticated_logout.status_code == 401


def test_protected_endpoint_rejects_missing_and_invalid_tokens():
    response = client.get("/api/v1/datasets")
    assert response.status_code == 401

    response = client.get("/api/v1/datasets", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


def test_new_user_defaults_to_ngn_and_two_decimal_places():
    # NGN, not USD -- DataWise AI's primary market (see User.currency's
    # own docstring in app/db/models.py). Still changeable in Settings.
    email = _unique_email()
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Hedy Lamarr"},
    )
    assert register.json()["user"]["currency"] == "NGN"
    assert register.json()["user"]["decimal_places"] == 2


def test_settings_update_persists_and_survives_a_fresh_login():
    email = _unique_email()
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Katherine Johnson"},
    )
    token = register.json()["access_token"]

    updated = client.patch(
        "/api/v1/auth/me/settings",
        json={"currency": "NGN", "decimal_places": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["currency"] == "NGN"
    assert updated.json()["decimal_places"] == 0

    # Persists across a fresh login (not just in-memory on this request).
    relogin = client.post("/api/v1/auth/login", json={"email": email, "password": "correct horse battery staple"})
    assert relogin.json()["user"]["currency"] == "NGN"
    assert relogin.json()["user"]["decimal_places"] == 0


def test_settings_update_rejects_unsupported_currency():
    email = _unique_email()
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "full_name": "Mary Jackson"},
    )
    token = register.json()["access_token"]

    response = client.patch(
        "/api/v1/auth/me/settings",
        json={"currency": "ZZZ"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_email_deliverability_check_is_skipped_outside_production():
    # The default dev/CI environment must never depend on a live DNS
    # lookup -- this is what keeps every other test in this file free to
    # register against the reserved, deliberately mail-less "@example.com"
    # domain without depending on network access.
    with (
        patch("app.auth.schemas.get_settings", return_value=Settings(_env_file=None, environment="development")),
        patch("app.auth.schemas.validate_email") as mock_validate,
    ):
        user = UserCreate(email="whoever@example.com", password="correct horse battery staple", full_name="Test")
        assert user.email == "whoever@example.com"
        mock_validate.assert_not_called()


def test_email_deliverability_check_rejects_an_undeliverable_domain_in_production():
    with (
        patch("app.auth.schemas.get_settings", return_value=Settings(_env_file=None, environment="production")),
        patch("app.auth.schemas.validate_email", side_effect=EmailNotValidError("no mail servers for this domain")),
    ):
        try:
            UserCreate(email="whoever@example.com", password="correct horse battery staple", full_name="Test")
            raise AssertionError("expected a ValidationError for an undeliverable domain")
        except ValidationError as exc:
            assert "reachable" in str(exc)


def test_email_deliverability_check_accepts_a_real_domain_in_production():
    with (
        patch("app.auth.schemas.get_settings", return_value=Settings(_env_file=None, environment="production")),
        patch("app.auth.schemas.validate_email") as mock_validate,
    ):
        user = UserCreate(email="whoever@gmail.com", password="correct horse battery staple", full_name="Test")
        assert user.email == "whoever@gmail.com"
        mock_validate.assert_called_once()
