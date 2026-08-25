"""Per-user views over the shared file-backed stores.

DatasetStore and DocumentStore (app/semantic/store.py, app/documents/store.py)
are process-global and have no user concept -- Phase 2/3/4's agent, tools,
and analysis engine were all written against that global store and must
stay that way (rebuilding them per-user would duplicate a lot of working
code). Instead, these wrappers implement the exact same read methods the
rest of the app already calls, but filtered to one user's owned ids, and
get threaded into the SAME FastAPI dependencies (get_dataset_store /
get_document_store) via override -- so every existing caller (tools.py,
the analysis engine, the agent loop) is automatically scoped without any
of that code knowing users exist at all.

Writes (`put`, `delete`, `new_id`) pass straight through: a freshly
uploaded dataset/document has no owner conflict to resolve, and delete is
only ever called after the caller has already checked ownership in
Postgres (see app/api/datasets.py / documents.py).
"""

from dataclasses import dataclass

from app.documents.models import DocumentChunk, DocumentSummary
from app.documents.store import DocumentRecord, DocumentStore
from app.semantic.models import DatasetSummary
from app.semantic.store import DatasetRecord, DatasetStore


@dataclass
class ScopedDatasetStore:
    _store: DatasetStore
    _owned_ids: set[str]

    def get(self, dataset_id: str) -> DatasetRecord | None:
        if dataset_id not in self._owned_ids:
            return None
        return self._store.get(dataset_id)

    def list_summaries(self) -> list[DatasetSummary]:
        return [s for s in self._store.list_summaries() if s.id in self._owned_ids]

    def all_records(self) -> list[DatasetRecord]:
        return [r for r in self._store.all_records() if r.profile.id in self._owned_ids]

    def new_id(self) -> str:
        return self._store.new_id()

    def put(self, dataset_id: str, df, profile) -> None:
        self._store.put(dataset_id, df, profile)

    def delete(self, dataset_id: str) -> bool:
        return self._store.delete(dataset_id)

    def narrowed(self, ids: set[str]) -> "ScopedDatasetStore":
        """A further-restricted view over the same underlying store, for
        when the caller explicitly selected a subset of their own datasets
        (e.g. Ask DataWise's dataset-selection UI). Intersects with the ids
        this store is already scoped to, so it can only ever narrow access,
        never grant access to a dataset the user doesn't own."""
        return ScopedDatasetStore(_store=self._store, _owned_ids=self._owned_ids & ids)


@dataclass
class ScopedDocumentStore:
    _store: DocumentStore
    _owned_ids: set[str]

    def get(self, document_id: str) -> DocumentRecord | None:
        if document_id not in self._owned_ids:
            return None
        return self._store.get(document_id)

    def get_chunk(self, document_id: str, chunk_id: str) -> DocumentChunk | None:
        if document_id not in self._owned_ids:
            return None
        return self._store.get_chunk(document_id, chunk_id)

    def list_summaries(self) -> list[DocumentSummary]:
        return [s for s in self._store.list_summaries() if s.id in self._owned_ids]

    def retrieve(self, query: str, top_k: int = 5, document_ids: list[str] | None = None):
        scoped_ids = list(self._owned_ids) if document_ids is None else [d for d in document_ids if d in self._owned_ids]
        if not scoped_ids:
            return []
        return self._store.retrieve(query, top_k=top_k, document_ids=scoped_ids)

    def new_id(self) -> str:
        return self._store.new_id()

    def put(self, summary, chunks) -> None:
        self._store.put(summary, chunks)

    def narrowed(self, ids: set[str]) -> "ScopedDocumentStore":
        """See ScopedDatasetStore.narrowed -- same intersect-only restriction."""
        return ScopedDocumentStore(_store=self._store, _owned_ids=self._owned_ids & ids)
