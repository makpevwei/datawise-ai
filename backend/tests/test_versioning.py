"""Dataset/document duplicate detection and versioning -- Phase 4
continuation sections 5-9. Content (not filename alone) determines exact
duplicate vs. changed vs. new; changed content creates a new version and
deactivates (never deletes) the old one; unchanged re-uploads skip
reprocessing entirely.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_dataset_store, get_document_store
from app.auth.dependencies import get_current_user
from app.db.models import Dataset, Document
from app.db.session import get_session_factory
from app.documents.store import DocumentStore
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import customers_df, orders_df, to_csv_bytes


@pytest.fixture
def client(tmp_path, auth_override):
    app.dependency_overrides[get_dataset_store] = lambda: DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_document_store] = lambda: DocumentStore(storage_dir=tmp_path / "documents")
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---- Datasets ----


def test_check_duplicate_reports_new_for_a_never_seen_filename(client):
    files = {"file": ("customers.csv", to_csv_bytes(customers_df()), "text/csv")}
    response = client.post("/api/v1/datasets/check-duplicate", files=files)
    assert response.status_code == 200
    assert response.json()["status"] == "new"


def test_check_duplicate_reports_exact_duplicate_for_identical_content(client):
    content = to_csv_bytes(customers_df())
    client.post("/api/v1/datasets/upload", files=[("files", ("customers.csv", content, "text/csv"))])

    response = client.post("/api/v1/datasets/check-duplicate", files={"file": ("customers.csv", content, "text/csv")})
    body = response.json()
    assert body["status"] == "exact_duplicate"
    assert body["existing"]["version"] == 1
    assert body["existing"]["is_active"] is True


def test_check_duplicate_reports_changed_version_for_same_filename_different_content(client):
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(customers_df()), "text/csv"))])

    changed = to_csv_bytes(orders_df())
    response = client.post("/api/v1/datasets/check-duplicate", files={"file": ("sales.csv", changed, "text/csv")})
    body = response.json()
    assert body["status"] == "changed_version"
    assert body["next_version"] == 2


def test_exact_duplicate_upload_reuses_existing_and_does_not_create_a_second_row(client, fake_user):
    content = to_csv_bytes(customers_df())
    first = client.post("/api/v1/datasets/upload", files=[("files", ("customers.csv", content, "text/csv"))])
    second = client.post("/api/v1/datasets/upload", files=[("files", ("customers.csv", content, "text/csv"))])

    assert first.json()["datasets"][0]["id"] == second.json()["datasets"][0]["id"]
    assert "already exists" in second.json()["warnings"][0]["message"].lower()

    db = get_session_factory()()
    count = db.query(Dataset).filter(Dataset.user_id == fake_user.id, Dataset.original_filename == "customers.csv").count()
    db.close()
    assert count == 1


def test_changed_content_creates_a_new_active_version_and_deactivates_the_old_one(client, fake_user):
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(customers_df()), "text/csv"))])
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(orders_df()), "text/csv"))])

    db = get_session_factory()()
    rows = (
        db.query(Dataset)
        .filter(Dataset.user_id == fake_user.id, Dataset.original_filename == "sales.csv")
        .order_by(Dataset.version)
        .all()
    )
    db.close()
    assert [r.version for r in rows] == [1, 2]
    assert [r.is_active for r in rows] == [False, True]


def test_old_versions_are_never_deleted_automatically(client, fake_user):
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(customers_df()), "text/csv"))])
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(orders_df()), "text/csv"))])

    library = client.get("/api/v1/datasets/library", params={"include_inactive": True}).json()
    versions = [d for d in library if d["original_filename"] == "sales.csv"]
    assert len(versions) == 2

    active_only = client.get("/api/v1/datasets/library").json()
    assert len([d for d in active_only if d["original_filename"] == "sales.csv"]) == 1


def test_activating_an_older_version_makes_it_active_again(client):
    v1 = client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(customers_df()), "text/csv"))])
    v1_id = v1.json()["datasets"][0]["id"]
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(orders_df()), "text/csv"))])

    reactivate = client.post(f"/api/v1/datasets/{v1_id}/activate")
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True

    active_only = client.get("/api/v1/datasets/library").json()
    active_ids = {d["id"] for d in active_only if d["original_filename"] == "sales.csv"}
    assert active_ids == {v1_id}


def test_force_new_version_creates_a_fresh_version_even_for_identical_content(client, fake_user):
    content = to_csv_bytes(customers_df())
    client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", content, "text/csv"))])
    client.post(
        "/api/v1/datasets/upload",
        files=[("files", ("sales.csv", content, "text/csv"))],
        data={"force_new_version": "true"},
    )

    db = get_session_factory()()
    rows = db.query(Dataset).filter(Dataset.user_id == fake_user.id, Dataset.original_filename == "sales.csv").all()
    db.close()
    assert len(rows) == 2
    assert {r.version for r in rows} == {1, 2}


def test_a_different_filename_is_a_completely_new_logical_dataset(client):
    client.post("/api/v1/datasets/upload", files=[("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))])
    response = client.post("/api/v1/datasets/upload", files=[("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))])
    assert response.json()["datasets"][0]["name"] == "orders.csv"

    library = client.get("/api/v1/datasets/library").json()
    assert {d["original_filename"] for d in library} == {"customers.csv", "orders.csv"}


def test_deleting_the_active_version_promotes_the_next_newest_version(client):
    v1 = client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(customers_df()), "text/csv"))])
    v1_id = v1.json()["datasets"][0]["id"]
    v2 = client.post("/api/v1/datasets/upload", files=[("files", ("sales.csv", to_csv_bytes(orders_df()), "text/csv"))])
    v2_id = v2.json()["datasets"][0]["id"]

    delete = client.delete(f"/api/v1/datasets/{v2_id}")
    assert delete.status_code == 204

    active_only = client.get("/api/v1/datasets/library").json()
    active = [d for d in active_only if d["original_filename"] == "sales.csv"]
    assert len(active) == 1
    assert active[0]["id"] == v1_id
    assert active[0]["is_active"] is True


# ---- Documents (same contract) ----


def test_document_exact_duplicate_is_reused(client, fake_user):
    content = b"# Notes\n\nReal content here, not just a heading.\n"
    first = client.post("/api/v1/documents/upload", files=[("files", ("notes.md", content, "text/markdown"))])
    second = client.post("/api/v1/documents/upload", files=[("files", ("notes.md", content, "text/markdown"))])
    assert first.json()["documents"][0]["id"] == second.json()["documents"][0]["id"]

    db = get_session_factory()()
    count = db.query(Document).filter(Document.user_id == fake_user.id, Document.filename == "notes.md").count()
    db.close()
    assert count == 1


def test_document_changed_content_creates_a_new_version(client, fake_user):
    client.post(
        "/api/v1/documents/upload",
        files=[("files", ("notes.md", b"# V1\n\nOriginal content paragraph here.\n", "text/markdown"))],
    )
    client.post(
        "/api/v1/documents/upload",
        files=[("files", ("notes.md", b"# V2\n\nCompletely different content paragraph.\n", "text/markdown"))],
    )

    db = get_session_factory()()
    rows = (
        db.query(Document)
        .filter(Document.user_id == fake_user.id, Document.filename == "notes.md")
        .order_by(Document.version)
        .all()
    )
    db.close()
    assert [r.version for r in rows] == [1, 2]
    assert [r.is_active for r in rows] == [False, True]


def test_document_check_duplicate_endpoint(client):
    content = b"# Notes\n\nSome real body text so extraction succeeds.\n"
    client.post("/api/v1/documents/upload", files=[("files", ("notes.md", content, "text/markdown"))])

    exact = client.post("/api/v1/documents/check-duplicate", files={"file": ("notes.md", content, "text/markdown")})
    assert exact.json()["status"] == "exact_duplicate"

    changed = client.post(
        "/api/v1/documents/check-duplicate",
        files={"file": ("notes.md", b"# Notes\n\nDifferent body text entirely now.\n", "text/markdown")},
    )
    assert changed.json()["status"] == "changed_version"
