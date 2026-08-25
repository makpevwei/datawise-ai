"""ScopedDatasetStore/ScopedDocumentStore.narrowed() -- backs the Ask
DataWise dataset-selection UI (the user picks a subset of their own
datasets; the agent should only see that subset). The critical property
is that narrowing can never widen access: intersecting with an id the
caller doesn't actually own must never expose it.
"""

import pandas as pd

from app.api.scoped_stores import ScopedDatasetStore, ScopedDocumentStore
from app.documents.models import DocumentSummary
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore


def _store_with_two_datasets(tmp_path):
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    for name in ("orders", "products"):
        df = pd.DataFrame({"id": [1, 2, 3], "value": [10.0, 20.0, 30.0]})
        store.put(name, df, profile_dataframe(df, name, name, f"{name}.csv", None, DatasetKind.UPLOADED))
    return store


def test_narrowed_restricts_to_the_intersection(tmp_path):
    store = _store_with_two_datasets(tmp_path)
    scoped = ScopedDatasetStore(_store=store, _owned_ids={"orders", "products"})

    narrowed = scoped.narrowed({"orders"})

    ids = {s.id for s in narrowed.list_summaries()}
    assert ids == {"orders"}
    assert narrowed.get("products") is None
    assert narrowed.get("orders") is not None


def test_narrowed_cannot_widen_access_beyond_what_was_already_owned(tmp_path):
    store = _store_with_two_datasets(tmp_path)
    # This user only owns 'orders' -- 'products' belongs to someone else,
    # but happens to exist in the same underlying file-backed store.
    scoped = ScopedDatasetStore(_store=store, _owned_ids={"orders"})

    # Requesting an id outside the owned set (as if a compromised/forged
    # request tried to smuggle another user's dataset id into dataset_ids)
    # must not grant access to it.
    narrowed = scoped.narrowed({"orders", "products"})

    ids = {s.id for s in narrowed.list_summaries()}
    assert ids == {"orders"}
    assert narrowed.get("products") is None


def test_narrowed_to_an_empty_set_yields_no_datasets(tmp_path):
    store = _store_with_two_datasets(tmp_path)
    scoped = ScopedDatasetStore(_store=store, _owned_ids={"orders", "products"})

    narrowed = scoped.narrowed(set())

    assert narrowed.list_summaries() == []
    assert narrowed.all_records() == []


def test_document_store_narrowed_restricts_to_the_intersection(tmp_path):
    store = DocumentStore(storage_dir=tmp_path / "documents")
    for doc_id in ("doc-a", "doc-b"):
        store.put(
            DocumentSummary(
                id=doc_id, filename=f"{doc_id}.md", document_type="md",
                chunk_count=0, char_count=10, created_at="2024-01-01T00:00:00",
            ),
            [],
        )
    scoped = ScopedDocumentStore(_store=store, _owned_ids={"doc-a", "doc-b"})

    narrowed = scoped.narrowed({"doc-a"})

    ids = {s.id for s in narrowed.list_summaries()}
    assert ids == {"doc-a"}
    assert narrowed.get("doc-b") is None
