"""Uploading the exact same file content twice (as the same user) should
not reparse/reprofile it again -- Phase 4 continuation section 9."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_store, get_document_store
from app.auth.dependencies import get_current_user
from app.db.models import Dataset, Document, User
from app.db.session import get_session_factory
from app.documents.store import DocumentStore
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import customers_df, orders_df, to_csv_bytes


@pytest.fixture
def raw_client(tmp_path):
    """No auth override -- real register/login, for tests that need two
    distinct real users. Only the file stores are swapped for temp dirs."""
    app.dependency_overrides[get_dataset_store] = lambda: DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_document_store] = lambda: DocumentStore(storage_dir=tmp_path / "documents")
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client(tmp_path, auth_override):
    app.dependency_overrides[get_dataset_store] = lambda: DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_document_store] = lambda: DocumentStore(storage_dir=tmp_path / "documents")
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_uploading_the_same_dataset_twice_reuses_the_cached_version(client, fake_user):
    files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]

    first = client.post("/api/v1/datasets/upload", files=files)
    assert first.status_code == 200
    assert first.json()["warnings"] == []
    first_dataset_id = first.json()["datasets"][0]["id"]

    second = client.post("/api/v1/datasets/upload", files=files)
    assert second.status_code == 200
    assert any("already exists" in w["message"].lower() for w in second.json()["warnings"])
    second_dataset_id = second.json()["datasets"][0]["id"]

    # Same underlying dataset reused, not reprocessed into a second one.
    assert first_dataset_id == second_dataset_id

    db = get_session_factory()()
    count = db.query(Dataset).filter(Dataset.user_id == fake_user.id).count()
    db.close()
    assert count == 1


def test_uploading_a_different_dataset_does_not_hit_the_cache(client):
    files_a = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    files_b = [("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]

    first = client.post("/api/v1/datasets/upload", files=files_a)
    second = client.post("/api/v1/datasets/upload", files=files_b)

    assert second.json()["warnings"] == []
    assert first.json()["datasets"][0]["id"] != second.json()["datasets"][0]["id"]


def test_uploading_the_same_document_twice_reuses_the_cached_version(client, fake_user):
    files = [("files", ("notes.md", b"# Shared notes\nSame content every time.\n", "text/markdown"))]

    first = client.post("/api/v1/documents/upload", files=files)
    assert first.status_code == 200
    first_id = first.json()["documents"][0]["id"]

    second = client.post("/api/v1/documents/upload", files=files)
    assert second.status_code == 200
    second_id = second.json()["documents"][0]["id"]

    assert first_id == second_id

    db = get_session_factory()()
    count = db.query(Document).filter(Document.user_id == fake_user.id).count()
    db.close()
    assert count == 1


def test_two_different_users_uploading_identical_content_each_get_their_own_row(raw_client):
    session = get_session_factory()()
    tokens = {}
    ids = {}
    for who in ("alice", "bob"):
        email = f"{who}-{uuid.uuid4().hex}@example.com"
        resp = raw_client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "correct horse battery staple", "full_name": who.title()},
        )
        tokens[who] = resp.json()["access_token"]
        ids[who] = resp.json()["user"]["id"]

    try:
        files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
        alice = raw_client.post("/api/v1/datasets/upload", files=files, headers={"Authorization": f"Bearer {tokens['alice']}"})
        bob = raw_client.post("/api/v1/datasets/upload", files=files, headers={"Authorization": f"Bearer {tokens['bob']}"})

        assert alice.json()["warnings"] == []
        assert bob.json()["warnings"] == []  # bob's cache is independent of alice's
        assert alice.json()["datasets"][0]["id"] != bob.json()["datasets"][0]["id"]
    finally:
        for who in ("alice", "bob"):
            user = session.get(User, ids[who])
            if user:
                session.delete(user)
        session.commit()
        session.close()
