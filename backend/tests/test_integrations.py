"""Google Drive/Sheets connector tests:
  - OAuth state-JWT round trip, and that it can't be substituted for a
    real access token (or vice versa) even though both share a signing key.
  - Refresh-token-at-rest encryption round trip.
  - Per-user isolation on Integration/ConnectedItem, mirroring the exact
    pattern tests/test_user_isolation.py already uses for datasets/documents.
  - A sync test using a mocked Google client (no real network call) that
    confirms a synced Sheet lands as a real Dataset row (DatasetKind.CONNECTED)
    with zero changes needed to the agent/RAG layer.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_store, get_document_store
from app.auth.security import (
    TokenError,
    create_access_token,
    create_oauth_state_token,
    decode_access_token,
    decode_oauth_state_token,
)
from app.config import Settings
from app.db.models import ConnectedItem, Integration, User
from app.db.session import get_session_factory
from app.documents.store import DocumentStore
from app.integrations import service
from app.integrations.crypto import TokenDecryptionError, decrypt_refresh_token, encrypt_refresh_token
from app.main import app
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore

_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")


def _settings(**overrides) -> Settings:
    """A fixed encryption key by default (not a fresh one per call) so a
    token encrypted in one fixture and decrypted in another test function
    round-trips correctly -- pass token_encryption_key=... to override for
    a test that specifically needs a *different* key (e.g. the
    wrong-key-fails-loudly test)."""
    fields = {"jwt_secret_key": "test-jwt-secret-not-used-in-production", "token_encryption_key": _TEST_ENCRYPTION_KEY}
    fields.update(overrides)
    return Settings(_env_file=None, **fields)


# ---------------------------------------------------------------------------
# OAuth state-JWT round trip
# ---------------------------------------------------------------------------


def test_oauth_state_token_round_trips_to_the_same_user_id():
    settings = _settings()
    token = create_oauth_state_token("user-123", settings)
    assert decode_oauth_state_token(token, settings) == "user-123"


def test_oauth_state_token_is_rejected_by_decode_access_token():
    """A leaked state token (10 min TTL) must not work as a bearer access
    token against get_current_user-gated endpoints -- see the `purpose`
    check added to decode_access_token."""
    settings = _settings()
    state_token = create_oauth_state_token("user-123", settings)
    with pytest.raises(TokenError):
        decode_access_token(state_token, settings)


def test_real_access_token_is_rejected_by_decode_oauth_state_token():
    """The reverse direction: a real bearer token must not be usable as the
    OAuth `state` param -- decode_oauth_state_token already checked this,
    confirmed here alongside the new symmetric check above."""
    settings = _settings()
    access_token = create_access_token("user-123", settings)
    with pytest.raises(TokenError):
        decode_oauth_state_token(access_token, settings)


def test_expired_oauth_state_token_is_rejected():
    import jwt as pyjwt

    settings = _settings()
    now = datetime.now(UTC)
    expired_payload = {
        "sub": "user-123",
        "purpose": "oauth_state",
        "nonce": "x",
        "iat": now - timedelta(minutes=20),
        "exp": now - timedelta(minutes=10),
    }
    expired_token = pyjwt.encode(expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_oauth_state_token(expired_token, settings)


# ---------------------------------------------------------------------------
# Refresh-token-at-rest encryption round trip
# ---------------------------------------------------------------------------


def test_refresh_token_encryption_round_trips():
    settings = _settings()
    encrypted = encrypt_refresh_token("1//fake-google-refresh-token", settings)
    assert encrypted != "1//fake-google-refresh-token"  # actually encrypted, not stored raw
    assert decrypt_refresh_token(encrypted, settings) == "1//fake-google-refresh-token"


def test_refresh_token_decryption_fails_loudly_with_the_wrong_key():
    settings_a = _settings()
    settings_b = _settings(token_encryption_key=Fernet.generate_key().decode("utf-8"))
    encrypted = encrypt_refresh_token("1//fake-google-refresh-token", settings_a)
    with pytest.raises(TokenDecryptionError):
        decrypt_refresh_token(encrypted, settings_b)


# ---------------------------------------------------------------------------
# Per-user isolation -- mirrors tests/test_user_isolation.py exactly
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_dataset_store] = lambda: DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_document_store] = lambda: DocumentStore(storage_dir=tmp_path / "documents")
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def two_users(client):
    session = get_session_factory()()
    tokens = {}
    ids = {}
    for who in ("alice", "bob"):
        email = f"{who}-{uuid.uuid4().hex}@example.com"
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "correct horse battery staple", "full_name": who.title()},
        )
        tokens[who] = resp.json()["access_token"]
        ids[who] = resp.json()["user"]["id"]
    yield tokens, ids
    for who in ("alice", "bob"):
        user = session.get(User, ids[who])
        if user:
            session.delete(user)
    session.commit()
    session.close()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice_integration(two_users):
    _, ids = two_users
    settings = _settings()
    db = get_session_factory()()
    integration = Integration(
        user_id=ids["alice"],
        provider="google",
        status="connected",
        scopes_granted="https://www.googleapis.com/auth/drive.readonly",
        encrypted_refresh_token=encrypt_refresh_token("1//alice-fake-refresh-token", settings),
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    yield integration
    db.close()


def test_integration_listing_is_isolated_per_user(client, two_users, alice_integration):
    tokens, _ = two_users
    alice_list = client.get("/api/v1/integrations", headers=_auth(tokens["alice"])).json()
    assert any(i["id"] == alice_integration.id for i in alice_list)

    bob_list = client.get("/api/v1/integrations", headers=_auth(tokens["bob"])).json()
    assert not any(i["id"] == alice_integration.id for i in bob_list)


def test_bob_cannot_browse_alices_integration(client, two_users, alice_integration):
    tokens, _ = two_users
    resp = client.get(f"/api/v1/integrations/{alice_integration.id}/browse", headers=_auth(tokens["bob"]))
    assert resp.status_code == 404


def test_bob_cannot_select_items_on_alices_integration(client, two_users, alice_integration):
    tokens, _ = two_users
    resp = client.post(
        f"/api/v1/integrations/{alice_integration.id}/items",
        json={"items": []},
        headers=_auth(tokens["bob"]),
    )
    assert resp.status_code == 404


def test_bob_cannot_sync_alices_integration(client, two_users, alice_integration):
    tokens, _ = two_users
    resp = client.post(f"/api/v1/integrations/{alice_integration.id}/sync", headers=_auth(tokens["bob"]))
    assert resp.status_code == 404


def test_bob_cannot_disconnect_alices_integration(client, two_users, alice_integration):
    tokens, _ = two_users
    resp = client.delete(f"/api/v1/integrations/{alice_integration.id}", headers=_auth(tokens["bob"]))
    assert resp.status_code == 404

    # still there -- bob's attempt did not delete it
    db = get_session_factory()()
    assert db.get(Integration, alice_integration.id) is not None
    db.close()


def test_alice_can_manage_her_own_integration(client, two_users, alice_integration):
    tokens, _ = two_users
    resp = client.delete(f"/api/v1/integrations/{alice_integration.id}", headers=_auth(tokens["alice"]))
    assert resp.status_code == 200

    db = get_session_factory()()
    assert db.get(Integration, alice_integration.id) is None
    db.close()


# ---------------------------------------------------------------------------
# Sync, with a mocked Google client -- no real network call
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_fixture(two_users, alice_integration, tmp_path):
    _, ids = two_users
    db = get_session_factory()()
    item = ConnectedItem(
        integration_id=alice_integration.id,
        user_id=ids["alice"],
        external_id="fake-sheet-id",
        external_kind="sheet",
        display_name="Q1 Revenue",
        external_modified_at=datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    integration = db.get(Integration, alice_integration.id)
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    yield db, item, integration, dataset_store, document_store
    db.close()


def test_sync_connected_sheet_lands_as_a_connected_dataset(monkeypatch, sync_fixture):
    db, item, integration, dataset_store, document_store = sync_fixture
    settings = _settings()

    def fake_refresh(refresh_token, settings):
        class FakeCreds:
            pass

        return FakeCreds()

    def fake_metadata(creds, file_id):
        assert file_id == "fake-sheet-id"
        return {"id": file_id, "name": "Q1 Revenue", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "2026-01-15T10:00:00.000Z"}

    def fake_values(creds, spreadsheet_id, range_):
        assert spreadsheet_id == "fake-sheet-id"
        return {"values": [["region", "revenue"], ["west", "1000"], ["east", "2000"]]}

    monkeypatch.setattr(service.oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(service.google_client, "get_drive_file_metadata", fake_metadata)
    monkeypatch.setattr(service.google_client, "get_spreadsheet_values", fake_values)

    service.sync_connected_item(item, integration, db, dataset_store, document_store, settings)

    assert item.sync_status == "synced"
    assert item.last_error is None
    assert item.dataset_id is not None

    from app.db.models import Dataset

    row = db.get(Dataset, item.dataset_id)
    assert row is not None
    assert row.is_active is True
    assert row.user_id == item.user_id

    summaries = dataset_store.list_summaries()
    matching = [s for s in summaries if s.id == row.storage_reference]
    assert len(matching) == 1
    assert matching[0].kind == DatasetKind.CONNECTED
    assert matching[0].row_count == 2  # header row excluded


def test_sync_skips_unchanged_items(monkeypatch, sync_fixture):
    """Second sync of an item whose modifiedTime hasn't advanced should be a
    no-op -- confirmed by never calling get_spreadsheet_values."""
    db, item, integration, dataset_store, document_store = sync_fixture
    settings = _settings()

    from app.db.models import Dataset

    already_synced = Dataset(
        user_id=item.user_id,
        original_filename="Q1 Revenue.csv",
        display_name="Q1 Revenue",
        file_type="csv",
        file_size=10,
        row_count=2,
        column_count=2,
        content_hash="fake-hash",
        storage_reference="fake-storage-ref",
    )
    db.add(already_synced)
    db.commit()
    db.refresh(already_synced)

    item.dataset_id = already_synced.id
    item.external_modified_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    db.commit()

    called = {"values": False}

    def fake_refresh(refresh_token, settings):
        class FakeCreds:
            pass

        return FakeCreds()

    def fake_metadata(creds, file_id):
        return {"id": file_id, "name": "Q1 Revenue", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "2026-01-15T10:00:00.000Z"}

    def fake_values(creds, spreadsheet_id, range_):
        called["values"] = True
        return {"values": []}

    monkeypatch.setattr(service.oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(service.google_client, "get_drive_file_metadata", fake_metadata)
    monkeypatch.setattr(service.google_client, "get_spreadsheet_values", fake_values)

    service.sync_connected_item(item, integration, db, dataset_store, document_store, settings)

    assert called["values"] is False
    assert item.sync_status == "synced"


def test_sync_records_the_error_and_does_not_raise_when_google_fails(monkeypatch, sync_fixture):
    """One bad item must never blow up a batch sync -- see
    app/integrations/service.py's own docstring."""
    db, item, integration, dataset_store, document_store = sync_fixture
    settings = _settings()

    def fake_refresh(refresh_token, settings):
        raise RuntimeError("Google said no.")

    monkeypatch.setattr(service.oauth, "refresh_access_token", fake_refresh)

    service.sync_connected_item(item, integration, db, dataset_store, document_store, settings)  # must not raise

    assert item.sync_status == "error"
    assert item.last_error is not None
    assert "Google said no" in item.last_error
