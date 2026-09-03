"""get_scoped_dataset_store / get_scoped_document_store (app/api/deps.py):
the owned_ids query that decides which of a user's own Dataset/Document
rows the agent can even see.

Found live: re-uploading a document to fix an unrelated bug had the agent
keep citing the OLD, already-superseded version of it by name -- the
owned_ids query had no is_active filter, so a deactivated version stayed
permanently visible right alongside its replacement, and
_resolve_document_id's plain name-match picked whichever one it found
first. Same query shape backs datasets too, so the same bug applies there.
"""

import uuid

import pytest

from app.api.deps import get_scoped_dataset_store, get_scoped_document_store
from app.db.models import Dataset, Document, User
from app.db.session import get_session_factory
from app.documents.models import DocumentSummary
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from tests.factories import orders_df


@pytest.fixture
def db_session():
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def fake_user(db_session):
    user = User(email=f"scoped-deps-{uuid.uuid4().hex}@example.com", password_hash="not-a-real-hash", full_name="Test")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    db_session.delete(user)
    db_session.commit()


def test_scoped_dataset_store_excludes_a_deactivated_version(db_session, fake_user, tmp_path):
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    df = orders_df(5)
    profile_old = profile_dataframe(df, "old-storage-ref", "orders", "orders.csv", None, DatasetKind.UPLOADED)
    profile_new = profile_dataframe(df, "new-storage-ref", "orders", "orders.csv", None, DatasetKind.UPLOADED)
    store.put("old-storage-ref", df, profile_old)
    store.put("new-storage-ref", df, profile_new)

    # Two versions of the same logical (user, filename) dataset -- v1
    # deactivated, v2 active, exactly what a real re-upload produces.
    db_session.add(
        Dataset(
            user_id=fake_user.id, original_filename="orders.csv", display_name="orders.csv", file_type="csv",
            file_size=100, content_hash="hash-v1", version=1, is_active=False, storage_reference="old-storage-ref",
        )
    )
    db_session.add(
        Dataset(
            user_id=fake_user.id, original_filename="orders.csv", display_name="orders.csv", file_type="csv",
            file_size=100, content_hash="hash-v2", version=2, is_active=True, storage_reference="new-storage-ref",
        )
    )
    db_session.commit()

    scoped = get_scoped_dataset_store(store=store, db=db_session, user=fake_user)

    ids = {s.id for s in scoped.list_summaries()}
    assert ids == {"new-storage-ref"}
    assert scoped.get("old-storage-ref") is None
    assert scoped.get("new-storage-ref") is not None


def test_scoped_document_store_excludes_a_deactivated_version(db_session, fake_user, tmp_path):
    store = DocumentStore(storage_dir=tmp_path / "documents")
    for ref in ("old-storage-ref", "new-storage-ref"):
        store.put(
            DocumentSummary(id=ref, filename="report.pdf", document_type="pdf", chunk_count=1, char_count=10, created_at="2024-01-01T00:00:00"),
            [],
        )

    db_session.add(
        Document(
            user_id=fake_user.id, filename="report.pdf", file_type="pdf", file_size=100,
            content_hash="hash-v1", version=1, is_active=False, storage_reference="old-storage-ref",
        )
    )
    db_session.add(
        Document(
            user_id=fake_user.id, filename="report.pdf", file_type="pdf", file_size=100,
            content_hash="hash-v2", version=2, is_active=True, storage_reference="new-storage-ref",
        )
    )
    db_session.commit()

    scoped = get_scoped_document_store(store=store, db=db_session, user=fake_user)

    ids = {s.id for s in scoped.list_summaries()}
    assert ids == {"new-storage-ref"}
    assert scoped.get("old-storage-ref") is None
    assert scoped.get("new-storage-ref") is not None
