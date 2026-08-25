import hashlib
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_dataset_store, get_scoped_dataset_store
from app.api.scoped_stores import ScopedDatasetStore
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import Dataset, User
from app.db.session import get_db
from app.semantic.models import DatasetProfile, DatasetSummary, UploadError, UploadResult, UploadWarning
from app.semantic.store import DatasetStore
from app.upload.service import ingest_files

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _json_safe(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    return value


class DatasetLibraryItem(BaseModel):
    id: str
    original_filename: str
    display_name: str
    file_type: str
    file_size: int
    row_count: int | None
    column_count: int | None
    processing_status: str
    processing_error: str | None
    version: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DuplicateCheckResult(BaseModel):
    status: str  # "new" | "exact_duplicate" | "changed_version"
    existing: DatasetLibraryItem | None = None
    next_version: int | None = None


def _active_dataset(db: DBSession, user_id: str, filename: str) -> Dataset | None:
    return (
        db.query(Dataset)
        .filter(Dataset.user_id == user_id, Dataset.original_filename == filename, Dataset.is_active.is_(True))
        .first()
    )


def _max_version(db: DBSession, user_id: str, filename: str) -> int:
    rows = db.query(Dataset.version).filter(Dataset.user_id == user_id, Dataset.original_filename == filename).all()
    return max((r[0] for r in rows), default=0)


@router.post("/check-duplicate", response_model=DuplicateCheckResult)
async def check_duplicate(
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DuplicateCheckResult:
    """Dry-run: hashes the file (no parsing/profiling) and reports whether it
    matches the active version, differs from it, or is entirely new -- lets
    the frontend show a confirmation dialog before committing to an upload."""
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()
    filename = file.filename or "unnamed"

    active = _active_dataset(db, user.id, filename)
    if active is None:
        return DuplicateCheckResult(status="new")
    if active.content_hash == content_hash:
        return DuplicateCheckResult(status="exact_duplicate", existing=DatasetLibraryItem.model_validate(active))
    return DuplicateCheckResult(
        status="changed_version",
        existing=DatasetLibraryItem.model_validate(active),
        next_version=_max_version(db, user.id, filename) + 1,
    )


@router.post("/upload", response_model=UploadResult)
async def upload_datasets(
    files: list[UploadFile] = File(...),
    force_new_version: bool = Form(False),
    store: DatasetStore = Depends(get_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadResult:
    """Duplicate detection + versioning (Phase 4 continuation sections 5-9):
    (user_id, original_filename) identifies a "logical dataset". A hash
    match against its current active version is reused untouched (no
    reparse/reprofile/reindex); a hash mismatch creates a new version and
    deactivates the old one (which is kept, not deleted) -- unless
    force_new_version is set, which always creates a fresh version even for
    identical content (the "Replace" choice on an exact-duplicate dialog)."""
    settings = get_settings()
    datasets: list[DatasetSummary] = []
    warnings: list[UploadWarning] = []
    errors: list[UploadError] = []

    for f in files:
        content = await f.read()
        filename = f.filename or "unnamed"
        content_hash = hashlib.sha256(content).hexdigest()

        active = _active_dataset(db, user.id, filename)
        is_exact_duplicate = active is not None and active.content_hash == content_hash and not force_new_version

        if is_exact_duplicate:
            record = store.get(active.storage_reference)
            if record is not None:
                s = record.profile
                datasets.append(
                    DatasetSummary(
                        id=s.id, name=s.name, source_file=s.source_file, sheet_name=s.sheet_name,
                        kind=s.kind, row_count=s.row_count, column_count=s.column_count,
                        quality_rating=s.quality.overall_rating, created_at=s.created_at,
                    )
                )
            warnings.append(UploadWarning(file=filename, message="This dataset already exists in your workspace — using the existing version."))
            continue

        result = ingest_files([(filename, content)], store, settings.max_upload_size_mb)
        warnings.extend(result.warnings)
        errors.extend(result.errors)
        if not result.datasets:
            continue

        next_version = _max_version(db, user.id, filename) + 1
        if active is not None:
            active.is_active = False  # superseded, kept for history -- never deleted automatically

        for summary in result.datasets:
            db.add(
                Dataset(
                    id=summary.id,
                    user_id=user.id,
                    original_filename=filename,
                    display_name=summary.name,
                    file_type=Path(filename).suffix.lstrip(".").lower() or "unknown",
                    file_size=len(content),
                    row_count=summary.row_count,
                    column_count=summary.column_count,
                    processing_status="ready",
                    content_hash=content_hash,
                    version=next_version,
                    is_active=True,
                    storage_reference=summary.id,
                )
            )
            datasets.append(summary)
            if next_version > 1:
                warnings.append(
                    UploadWarning(file=filename, message=f"Content changed — created version {next_version} and made it active.")
                )

    db.commit()
    return UploadResult(datasets=datasets, warnings=warnings, errors=errors)


@router.get("", response_model=list[DatasetSummary])
def list_datasets(store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> list[DatasetSummary]:
    return store.list_summaries()


@router.get("/library", response_model=list[DatasetLibraryItem])
def list_dataset_library(
    include_inactive: bool = False, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[DatasetLibraryItem]:
    """Richer, DB-backed view for My Data / Dashboard: file size, upload
    filename, and processing status alongside the same rows list_datasets
    already returns (via DatasetSummary, unchanged). Active versions only
    by default; include_inactive=true also returns superseded versions."""
    query = db.query(Dataset).filter(Dataset.user_id == user.id)
    if not include_inactive:
        query = query.filter(Dataset.is_active.is_(True))
    rows = query.order_by(Dataset.original_filename, Dataset.version.desc()).all()
    return [DatasetLibraryItem.model_validate(r) for r in rows]


@router.get("/{dataset_id}/versions", response_model=list[DatasetLibraryItem])
def list_dataset_versions(dataset_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[DatasetLibraryItem]:
    row = db.get(Dataset, dataset_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    versions = (
        db.query(Dataset)
        .filter(Dataset.user_id == user.id, Dataset.original_filename == row.original_filename)
        .order_by(Dataset.version.desc())
        .all()
    )
    return [DatasetLibraryItem.model_validate(v) for v in versions]


@router.post("/{dataset_id}/activate", response_model=DatasetLibraryItem)
def activate_dataset_version(dataset_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> DatasetLibraryItem:
    """'Use' an older version -- makes it the active one again, without
    reprocessing (the file store already has it)."""
    row = db.get(Dataset, dataset_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    current_active = _active_dataset(db, user.id, row.original_filename)
    if current_active is not None and current_active.id != row.id:
        current_active.is_active = False
    row.is_active = True
    db.commit()
    db.refresh(row)
    return DatasetLibraryItem.model_validate(row)


@router.get("/{dataset_id}", response_model=DatasetProfile)
def get_dataset(dataset_id: str, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> DatasetProfile:
    record = store.get(dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return record.profile


@router.get("/{dataset_id}/sample")
def get_dataset_sample(
    dataset_id: str, n: int = 20, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)
) -> list[dict]:
    record = store.get(dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    sample = record.dataframe.head(max(1, min(n, 500)))
    rows = sample.to_dict(orient="records")
    return [{k: _json_safe(v) for k, v in row.items()} for row in rows]


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    store: DatasetStore = Depends(get_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(Dataset, dataset_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    store.delete(row.storage_reference)
    was_active = row.is_active
    db.delete(row)
    db.flush()
    if was_active:
        # Deleting the active version promotes the next-newest remaining
        # version (if any) to active, so the logical dataset stays usable.
        remaining = (
            db.query(Dataset)
            .filter(Dataset.user_id == user.id, Dataset.original_filename == row.original_filename)
            .order_by(Dataset.version.desc())
            .first()
        )
        if remaining is not None:
            remaining.is_active = True
    db.commit()
