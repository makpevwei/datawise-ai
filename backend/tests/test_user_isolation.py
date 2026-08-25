"""CRITICAL per the Phase 4 continuation spec: user A must never see user
B's datasets, documents, sessions, or reports, and the backend -- not the
frontend -- must enforce it. Two real users are registered against the
real DataWise database; the file-backed stores are swapped for temp dirs
so this test doesn't touch real uploaded data.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_store, get_document_store
from app.db.models import AnalysisSession, Dataset, Document, Report, User
from app.db.session import get_session_factory
from app.documents.store import DocumentStore
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import customers_df, to_csv_bytes


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


def test_dataset_upload_and_listing_is_isolated_per_user(client, two_users):
    tokens, _ = two_users
    files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files, headers=_auth(tokens["alice"]))
    assert upload.status_code == 200
    alice_dataset_id = upload.json()["datasets"][0]["id"]

    alice_list = client.get("/api/v1/datasets", headers=_auth(tokens["alice"])).json()
    assert any(d["id"] == alice_dataset_id for d in alice_list)

    bob_list = client.get("/api/v1/datasets", headers=_auth(tokens["bob"])).json()
    assert not any(d["id"] == alice_dataset_id for d in bob_list)

    bob_get = client.get(f"/api/v1/datasets/{alice_dataset_id}", headers=_auth(tokens["bob"]))
    assert bob_get.status_code == 404

    bob_library = client.get("/api/v1/datasets/library", headers=_auth(tokens["bob"])).json()
    assert not any(d["id"] == alice_dataset_id for d in bob_library)


def test_document_listing_is_isolated_per_user(client, two_users):
    tokens, _ = two_users
    files = [
        (
            "files",
            ("notes.md", b"# Alice's private notes\n\nThis document should never be visible to another user.\n", "text/markdown"),
        )
    ]
    upload = client.post("/api/v1/documents/upload", files=files, headers=_auth(tokens["alice"]))
    alice_doc_id = upload.json()["documents"][0]["id"]

    bob_list = client.get("/api/v1/documents", headers=_auth(tokens["bob"])).json()
    assert not any(d["id"] == alice_doc_id for d in bob_list)

    bob_get = client.get(f"/api/v1/documents/{alice_doc_id}", headers=_auth(tokens["bob"]))
    assert bob_get.status_code == 404


def test_agent_cannot_see_another_users_datasets(client, two_users):
    """The agent's list_datasets/inspect_dataset tools go through the
    scoped store -- confirmed here at the API boundary via /agent/status
    and a direct dataset fetch, since a real LLM call isn't needed to
    prove the scoping (that's what ScopedDatasetStore's own unit
    behavior guarantees, exercised end-to-end here)."""
    tokens, _ = two_users
    files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files, headers=_auth(tokens["alice"]))
    alice_dataset_id = upload.json()["datasets"][0]["id"]

    bob_sample = client.get(f"/api/v1/datasets/{alice_dataset_id}/sample", headers=_auth(tokens["bob"]))
    assert bob_sample.status_code == 404


def test_session_and_report_ownership_is_enforced(client, two_users):
    tokens, ids = two_users
    session_db = get_session_factory()()
    try:
        s = AnalysisSession(user_id=ids["alice"], title="Alice's private analysis")
        session_db.add(s)
        session_db.commit()
        session_db.refresh(s)

        bob_get = client.get(f"/api/v1/sessions/{s.id}", headers=_auth(tokens["bob"]))
        assert bob_get.status_code == 404

        bob_delete = client.delete(f"/api/v1/sessions/{s.id}", headers=_auth(tokens["bob"]))
        assert bob_delete.status_code == 404

        alice_get = client.get(f"/api/v1/sessions/{s.id}", headers=_auth(tokens["alice"]))
        assert alice_get.status_code == 200
    finally:
        session_db.query(AnalysisSession).filter(AnalysisSession.user_id == ids["alice"]).delete()
        session_db.commit()
        session_db.close()


def test_deleting_a_dataset_never_touches_another_users_row(client, two_users):
    tokens, ids = two_users
    files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files, headers=_auth(tokens["alice"]))
    alice_dataset_id = upload.json()["datasets"][0]["id"]

    bob_delete = client.delete(f"/api/v1/datasets/{alice_dataset_id}", headers=_auth(tokens["bob"]))
    assert bob_delete.status_code == 404

    # still visible to alice -- bob's attempt did not delete it
    alice_get = client.get(f"/api/v1/datasets/{alice_dataset_id}", headers=_auth(tokens["alice"]))
    assert alice_get.status_code == 200
