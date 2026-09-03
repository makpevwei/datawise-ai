from functools import lru_cache
from pathlib import Path

from fastapi import Depends
from sqlalchemy.orm import Session as DBSession

from app.agent.memory import ConversationMemory
from app.ai.base import LLMProvider
from app.ai.client import build_llm_gateway
from app.api.scoped_stores import ScopedDatasetStore, ScopedDocumentStore
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import Dataset, Document, User
from app.db.session import get_db
from app.documents.store import DocumentStore
from app.semantic.store import DatasetStore


@lru_cache
def get_dataset_store() -> DatasetStore:
    settings = get_settings()
    return DatasetStore(storage_dir=Path(settings.upload_dir))


@lru_cache
def get_document_store() -> DocumentStore:
    settings = get_settings()
    return DocumentStore(storage_dir=Path(settings.document_dir))


def get_scoped_dataset_store(
    store: DatasetStore = Depends(get_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScopedDatasetStore:
    """The dataset store, filtered to this user's own *active* datasets --
    see app/api/scoped_stores.py. Every endpoint/agent call that must not
    leak another user's data depends on this instead of get_dataset_store.

    is_active=True is deliberate, not incidental: re-uploading a changed
    file creates a new version and flips the old row to is_active=False,
    but never deletes it (see Dataset's own docstring) -- without this
    filter, both versions stay permanently visible to the agent, and any
    name-based fallback resolution (_resolve_dataset_id in
    app/agent/tools.py, the equivalent for documents) can silently pick
    the stale one. Found live: re-uploading a document to fix a citation
    bug had the agent keep citing the old, deactivated version by name."""
    owned_ids = {
        row.storage_reference
        for row in db.query(Dataset.storage_reference).filter(Dataset.user_id == user.id, Dataset.is_active.is_(True))
    }
    return ScopedDatasetStore(store, owned_ids)


def get_scoped_document_store(
    store: DocumentStore = Depends(get_document_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScopedDocumentStore:
    """Same is_active scoping as get_scoped_dataset_store, and for the
    same reason -- see its docstring."""
    owned_ids = {
        row.storage_reference
        for row in db.query(Document.storage_reference).filter(Document.user_id == user.id, Document.is_active.is_(True))
    }
    return ScopedDocumentStore(store, owned_ids)


@lru_cache
def get_conversation_memory() -> ConversationMemory:
    return ConversationMemory()


def get_llm_provider() -> LLMProvider | None:
    """Not cached: re-reads settings each call so a key added after startup
    (or overridden in tests) takes effect without restarting the process.
    Returns the multi-provider gateway (primary + configured fallbacks),
    not a bare provider -- see app/ai/client.build_llm_gateway."""
    return build_llm_gateway()
