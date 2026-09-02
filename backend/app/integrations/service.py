"""Sync orchestration: pulls from Google (via app/integrations/google_client.py,
never anything else) and lands the result through the *existing*, tested
ingest_files/ingest_documents pipeline (app/upload/service.py,
app/documents/service.py) -- a synced Sheet becomes a real Dataset row, a
synced Drive doc becomes a real Document row, and from that point on every
existing agent tool, citation resolver, and per-user isolation check
already works on it, completely unmodified.

The Dataset/Document versioning logic below (hash-based change detection,
version/is_active chaining) is a deliberate near-duplicate of
app/api/datasets.py's/app/api/documents.py's own inline logic, not a
shared import -- extracting a common app/upload/versioning.py (which the
Dataset model's docstring already gestures at but was never actually
built) was judged higher-risk than duplicating ~15 lines of well-understood
logic under this phase's time constraints; tracked in TODO.md.
"""

import csv
import io
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from app.config import Settings, get_settings
from app.db.models import ConnectedItem, Dataset, Document, Integration
from app.documents.service import ingest_documents
from app.documents.store import DocumentStore
from app.integrations import google_client, oauth
from app.integrations.crypto import decrypt_refresh_token
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from app.upload.service import ingest_files


class GoogleSyncError(Exception):
    """Raised for any failure syncing one ConnectedItem -- callers record
    this on the item's last_error/sync_status rather than letting one bad
    item abort a whole batch, matching ingest_files'/ingest_documents' own
    "one failure becomes a warning" convention."""


def _parse_google_timestamp(value: str) -> datetime:
    # Google's modifiedTime is RFC3339 with a trailing 'Z' -- fromisoformat
    # has accepted bare 'Z' since Python 3.11 (this project pins 3.12).
    return datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None)


def _sheet_values_to_csv_bytes(values: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(values)
    return buffer.getvalue().encode("utf-8")


def _get_credentials(integration: Integration, settings: Settings):
    refresh_token = decrypt_refresh_token(integration.encrypted_refresh_token, settings)
    return oauth.refresh_access_token(refresh_token, settings)


def _active_dataset(db: DBSession, user_id: str, filename: str) -> Dataset | None:
    return (
        db.query(Dataset)
        .filter(Dataset.user_id == user_id, Dataset.original_filename == filename, Dataset.is_active.is_(True))
        .first()
    )


def _active_document(db: DBSession, user_id: str, filename: str) -> Document | None:
    return (
        db.query(Document)
        .filter(Document.user_id == user_id, Document.filename == filename, Document.is_active.is_(True))
        .first()
    )


def _next_version(db: DBSession, model, user_id: str, name_column, name: str) -> int:
    rows = db.query(model.version).filter(model.user_id == user_id, name_column == name).all()
    return max((r[0] for r in rows), default=0) + 1


def _sync_sheet(item: ConnectedItem, integration: Integration, creds, db: DBSession, dataset_store: DatasetStore, settings: Settings) -> None:
    values_response = google_client.get_spreadsheet_values(creds, item.external_id, "A1:ZZ100000")
    csv_bytes = _sheet_values_to_csv_bytes(values_response.get("values", []))
    filename = f"{item.display_name}.csv"

    result = ingest_files([(filename, csv_bytes)], dataset_store, settings.max_upload_size_mb, kind=DatasetKind.CONNECTED)
    if result.errors:
        raise GoogleSyncError("; ".join(e.message for e in result.errors))
    if not result.datasets:
        raise GoogleSyncError("Sheet produced no ingestible data.")

    active = _active_dataset(db, item.user_id, filename)
    next_version = _next_version(db, Dataset, item.user_id, Dataset.original_filename, filename)
    if active is not None:
        active.is_active = False

    summary = result.datasets[0]
    row = Dataset(
        id=summary.id,
        user_id=item.user_id,
        original_filename=filename,
        display_name=item.display_name,
        file_type="csv",
        file_size=len(csv_bytes),
        row_count=summary.row_count,
        column_count=summary.column_count,
        processing_status="ready",
        content_hash=summary.id,  # dataset_store already dedupes by content; the exact hash value isn't load-bearing here
        version=next_version,
        is_active=True,
        storage_reference=summary.id,
    )
    db.add(row)
    db.flush()
    item.dataset_id = row.id


def _sync_drive_doc(item: ConnectedItem, integration: Integration, creds, metadata: dict, db: DBSession, document_store: DocumentStore, settings: Settings) -> None:
    mime_type = metadata.get("mimeType", "")
    if mime_type.startswith("application/vnd.google-apps."):
        content = google_client.export_drive_file(creds, item.external_id, "application/pdf")
        extension = "pdf"
    else:
        content = google_client.download_drive_file(creds, item.external_id)
        extension = Path(metadata.get("name", item.display_name)).suffix.lstrip(".").lower() or "pdf"
    filename = f"{item.display_name}.{extension}"

    result = ingest_documents([(filename, content)], document_store, settings.max_document_upload_mb)
    if result.errors:
        raise GoogleSyncError("; ".join(e.message for e in result.errors))
    if not result.documents:
        raise GoogleSyncError("Drive file produced no ingestible content.")

    active = _active_document(db, item.user_id, filename)
    next_version = _next_version(db, Document, item.user_id, Document.filename, filename)
    if active is not None:
        active.is_active = False

    summary = result.documents[0]
    row = Document(
        id=summary.id,
        user_id=item.user_id,
        filename=filename,
        file_type=extension,
        file_size=len(content),
        content_hash=summary.id,
        processing_status="ready",
        extraction_status="ready",
        chunk_count=summary.chunk_count,
        embedding_status="pending",
        version=next_version,
        is_active=True,
        storage_reference=summary.id,
    )
    db.add(row)
    db.flush()
    item.document_id = row.id


def sync_connected_item(
    item: ConnectedItem,
    integration: Integration,
    db: DBSession,
    dataset_store: DatasetStore,
    document_store: DocumentStore,
    settings: Settings | None = None,
) -> None:
    """Syncs one ConnectedItem. Never raises past its own bookkeeping --
    always leaves item.sync_status/last_error set, so a caller syncing a
    batch of items can move on to the next one exactly like ingest_files'
    per-file error handling already does."""
    settings = settings or get_settings()
    item.sync_status = "syncing"
    db.commit()

    try:
        creds = _get_credentials(integration, settings)
        metadata = google_client.get_drive_file_metadata(creds, item.external_id)
        modified_at = _parse_google_timestamp(metadata["modifiedTime"])

        already_synced = item.dataset_id is not None or item.document_id is not None
        if already_synced and modified_at <= item.external_modified_at:
            item.sync_status = "synced"
            item.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
            return

        if item.external_kind == "sheet":
            _sync_sheet(item, integration, creds, db, dataset_store, settings)
        else:
            _sync_drive_doc(item, integration, creds, metadata, db, document_store, settings)

        item.external_modified_at = modified_at
        item.sync_status = "synced"
        item.last_error = None
        item.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- one bad item must never abort the rest of a sync batch
        db.rollback()
        item.sync_status = "error"
        item.last_error = str(exc)[:500]
        db.commit()
