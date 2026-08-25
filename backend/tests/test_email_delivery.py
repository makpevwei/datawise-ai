"""Report email delivery -- Phase 4 continuation section 33. No SMTP
credentials are configured in this environment (verified: DataWise-AI/.env
has no SMTP_* keys set), so these tests confirm the honest "not configured"
path and the pure send-logic unit behavior; they cannot and do not claim to
test an actual delivered email.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.memory import ConversationMemory
from app.ai.types import LLMTurn
from app.api.deps import get_conversation_memory, get_dataset_store, get_llm_provider, get_scoped_dataset_store
from app.auth.dependencies import get_current_user
from app.config import Settings
from app.main import app
from app.notifications.email import EmailNotConfiguredError, is_email_configured, send_report_email
from app.semantic.store import DatasetStore
from tests.fakes import FakeLLMProvider


@pytest.fixture
def client(tmp_path, auth_override):
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_scoped_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_report(client) -> str:
    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "Summary.", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider([route_turn, turn1, turn2])

    ask = client.post("/api/v1/agent/ask", json={"question": "How did we do?"})
    message_id = ask.json()["message_id"]
    create = client.post("/api/v1/reports", json={"message_id": message_id, "title": "Test report"})
    return create.json()["id"]


def test_is_email_configured_is_false_with_no_smtp_settings():
    assert is_email_configured(Settings(_env_file=None)) is False


def test_is_email_configured_is_true_when_all_fields_present():
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.example.com",
        smtp_username="user",
        smtp_password="pass",
        smtp_from_email="reports@example.com",
    )
    assert is_email_configured(settings) is True


def test_send_report_email_raises_not_configured_without_smtp_settings():
    with pytest.raises(EmailNotConfiguredError):
        send_report_email(
            settings=Settings(_env_file=None),
            to_email="someone@example.com",
            subject="Test",
            body_text="Body",
            attachment_bytes=b"%PDF-1.4",
            attachment_filename="report.pdf",
        )


def test_email_endpoint_reports_503_when_smtp_not_configured(client):
    report_id = _create_report(client)
    response = client.post(f"/api/v1/reports/{report_id}/email", json={"recipient": "someone@example.com"})
    assert response.status_code == 503
    # The message may name the missing SETTING (e.g. "SMTP_PASSWORD" as a
    # config key), which is fine and necessary for a useful error -- but
    # since nothing is configured, no actual secret VALUE exists to leak in
    # the first place. The real credential-safety guarantee (a value never
    # appearing) is enforced in send_report_email's except block instead.
    assert response.json()["detail"]


def test_email_endpoint_requires_a_valid_email_address(client):
    report_id = _create_report(client)
    response = client.post(f"/api/v1/reports/{report_id}/email", json={"recipient": "not-an-email"})
    assert response.status_code == 422


def test_email_endpoint_rejects_another_users_report(client, two_isolated_users_tokens):
    report_id = _create_report(client)
    other_token = two_isolated_users_tokens

    # `client`'s fixture overrides get_current_user for the whole app for
    # its lifetime (dependency_overrides is global mutable state, not
    # per-request) -- a real Bearer token from a different user would be
    # silently ignored while that override is active. Lift it just for this
    # one request so the real second user's token is what actually decides
    # who "the current user" is, proving ownership is genuinely enforced.
    saved_override = app.dependency_overrides.pop(get_current_user)
    try:
        response = client.post(
            f"/api/v1/reports/{report_id}/email",
            json={"recipient": "someone@example.com"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
    finally:
        app.dependency_overrides[get_current_user] = saved_override
    assert response.status_code == 404


def test_new_reports_default_to_not_sent_status(client):
    report_id = _create_report(client)
    listing = client.get("/api/v1/reports").json()
    report = next(r for r in listing if r["id"] == report_id)
    assert report["email_status"] == "not_sent"
    assert report["email_recipient"] is None


@pytest.fixture
def two_isolated_users_tokens():
    """A second, real, different user (not the fixture's fake_user) so the
    ownership-rejection test is genuine -- not just the same user twice.
    /auth/register and /auth/login are public, so no dependency override is
    needed here regardless of what the main `client` fixture has set."""
    import uuid
    from fastapi.testclient import TestClient as _TC
    from app.db.models import User
    from app.db.session import get_session_factory

    raw_client = _TC(app)
    email = f"other-{uuid.uuid4().hex}@example.com"
    register = raw_client.post(
        "/api/v1/auth/register", json={"email": email, "password": "whatever12345", "full_name": "Other User"}
    )
    token = register.json()["access_token"]

    yield token

    db = get_session_factory()()
    user = db.query(User).filter(User.email == email).first()
    if user:
        db.delete(user)
        db.commit()
    db.close()
