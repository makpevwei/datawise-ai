import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_document_store, get_scoped_document_store
from app.api.scoped_stores import ScopedDocumentStore
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import Document, User
from app.db.session import get_db
from app.documents.models import DocumentSummary, DocumentUploadError, DocumentUploadResult
from app.documents.service import ingest_documents
from app.documents.store import DocumentStore

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentLibraryItem(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int | None
    processing_status: str
    extraction_status: str
    embedding_status: str
    version: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DuplicateCheckResult(BaseModel):
    status: str  # "new" | "exact_duplicate" | "changed_version"
    existing: DocumentLibraryItem | None = None
    next_version: int | None = None


def _active_document(db: DBSession, user_id: str, filename: str) -> Document | None:
    return (
        db.query(Document)
        .filter(Document.user_id == user_id, Document.filename == filename, Document.is_active.is_(True))
        .first()
    )


def _max_version(db: DBSession, user_id: str, filename: str) -> int:
    rows = db.query(Document.version).filter(Document.user_id == user_id, Document.filename == filename).all()
    return max((r[0] for r in rows), default=0)


@router.post("/check-duplicate", response_model=DuplicateCheckResult)
async def check_duplicate(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DuplicateCheckResult:
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()
    filename = file.filename or "unnamed"

    active = _active_document(db, user.id, filename)
    if active is None:
        return DuplicateCheckResult(status="new")
    if active.content_hash == content_hash:
        return DuplicateCheckResult(status="exact_duplicate", existing=DocumentLibraryItem.model_validate(active))
    return DuplicateCheckResult(
        status="changed_version",
        existing=DocumentLibraryItem.model_validate(active),
        next_version=_max_version(db, user.id, filename) + 1,
    )


@router.post("/upload", response_model=DocumentUploadResult)
async def upload_documents(
    files: list[UploadFile] = File(...),
    force_new_version: bool = Form(False),
    store: DocumentStore = Depends(get_document_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentUploadResult:
    """Same duplicate-detection/versioning contract as datasets.upload_datasets:
    an unchanged re-upload is reused untouched (no re-extraction, no
    re-chunking, no re-embedding); changed content creates a new version and
    deactivates (never deletes) the old one."""
    settings = get_settings()
    documents: list[DocumentSummary] = []
    errors: list[DocumentUploadError] = []

    for f in files:
        content = await f.read()
        filename = f.filename or "unnamed"
        content_hash = hashlib.sha256(content).hexdigest()

        active = _active_document(db, user.id, filename)
        is_exact_duplicate = active is not None and active.content_hash == content_hash and not force_new_version

        if is_exact_duplicate:
            record = store.get(active.storage_reference)
            if record is not None:
                documents.append(record.summary)
                continue

        result = ingest_documents([(filename, content)], store, settings.max_document_upload_mb)
        errors.extend(result.errors)
        if not result.documents:
            continue

        next_version = _max_version(db, user.id, filename) + 1
        if active is not None and not is_exact_duplicate:
            active.is_active = False

        for summary in result.documents:
            db.add(
                Document(
                    id=summary.id,
                    user_id=user.id,
                    filename=filename,
                    file_type=Path(filename).suffix.lstrip(".").lower() or "unknown",
                    file_size=len(content),
                    content_hash=content_hash,
                    processing_status="ready",
                    extraction_status="ready",
                    chunk_count=summary.chunk_count,
                    embedding_status="ready",
                    version=next_version,
                    is_active=True,
                    storage_reference=summary.id,
                )
            )
            documents.append(summary)

    db.commit()
    return DocumentUploadResult(documents=documents, errors=errors)


@router.get("", response_model=list[DocumentSummary])
def list_documents(store: ScopedDocumentStore = Depends(get_scoped_document_store)) -> list[DocumentSummary]:
    return store.list_summaries()


@router.get("/library", response_model=list[DocumentLibraryItem])
def list_document_library(
    include_inactive: bool = False, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[DocumentLibraryItem]:
    query = db.query(Document).filter(Document.user_id == user.id)
    if not include_inactive:
        query = query.filter(Document.is_active.is_(True))
    rows = query.order_by(Document.filename, Document.version.desc()).all()
    return [DocumentLibraryItem.model_validate(r) for r in rows]


@router.get("/{document_id}/versions", response_model=list[DocumentLibraryItem])
def list_document_versions(document_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[DocumentLibraryItem]:
    row = db.get(Document, document_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    versions = (
        db.query(Document)
        .filter(Document.user_id == user.id, Document.filename == row.filename)
        .order_by(Document.version.desc())
        .all()
    )
    return [DocumentLibraryItem.model_validate(v) for v in versions]


@router.post("/{document_id}/activate", response_model=DocumentLibraryItem)
def activate_document_version(document_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentLibraryItem:
    row = db.get(Document, document_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    current_active = _active_document(db, user.id, row.filename)
    if current_active is not None and current_active.id != row.id:
        current_active.is_active = False
    row.is_active = True
    db.commit()
    db.refresh(row)
    return DocumentLibraryItem.model_validate(row)


@router.get("/{document_id}", response_model=DocumentSummary)
def get_document(document_id: str, store: ScopedDocumentStore = Depends(get_scoped_document_store)) -> DocumentSummary:
    record = store.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return record.summary


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    store: DocumentStore = Depends(get_document_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(Document, document_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    store.delete(row.storage_reference)
    was_active = row.is_active
    db.delete(row)
    db.flush()
    if was_active:
        remaining = (
            db.query(Document)
            .filter(Document.user_id == user.id, Document.filename == row.filename)
            .order_by(Document.version.desc())
            .first()
        )
        if remaining is not None:
            remaining.is_active = True
    db.commit()
