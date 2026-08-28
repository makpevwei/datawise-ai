"""DataWise's persistence layer: ownership, history, and processing state.

These tables do NOT replace the existing file-backed engines -- DatasetStore
and DocumentStore (app/semantic/store.py, app/documents/store.py) remain the
actual dataframe/chunk/embedding storage, unchanged. What these tables add is
the piece those stores never had: a per-user owner, and durability for
history (sessions, messages, reports) across restarts and logins.

A Dataset/Document row's `storage_reference` is the id DatasetStore/
DocumentStore already use internally -- the join key between "who owns this"
(Postgres) and "where the actual data lives" (the file store).
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    full_name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    # Presentation-only preferences (section 5-7 of the Phase 4 continuation
    # spec): never change what's calculated, only how numbers are displayed.
    currency: Mapped[str] = mapped_column(default="USD")
    decimal_places: Mapped[int] = mapped_column(default=2)
    # Password reset: reset_token_hash stores a SHA-256 hash of the token
    # emailed to the user, never the raw token -- mirrors why password_hash
    # above is never the plain password. A hash (not bcrypt) is deliberate:
    # this token is already high-entropy random bytes, not a human-chosen
    # password, so it doesn't need bcrypt's slow work factor. Null except
    # during the brief window between a forgot-password request and its use
    # or expiry.
    reset_token_hash: Mapped[str | None] = mapped_column(default=None)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Dataset(Base):
    """`(user_id, original_filename)` is the logical-dataset grouping key
    versions are chained under -- see app/domains/versioning.py. Re-uploading
    a file with the same name but different content creates a new row with
    version = max(existing) + 1 and is_active=True; the previous active row
    for that (user, filename) is flipped to is_active=False. Nothing is ever
    deleted automatically."""

    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_user_content_hash", "user_id", "content_hash"),
        Index("ix_datasets_user_filename", "user_id", "original_filename"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str]
    display_name: Mapped[str]
    file_type: Mapped[str]
    file_size: Mapped[int]
    row_count: Mapped[int | None]
    column_count: Mapped[int | None]
    processing_status: Mapped[str] = mapped_column(default="ready")
    processing_error: Mapped[str | None]
    content_hash: Mapped[str] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    # The id DatasetStore knows this dataset by -- may be shared by several
    # Dataset rows when one uploaded file splits into multiple sheets, and
    # each sheet gets its own row with its own storage_reference.
    storage_reference: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Document(Base):
    """Versioned the same way as Dataset -- see that model's docstring."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_content_hash", "user_id", "content_hash"),
        Index("ix_documents_user_filename", "user_id", "filename"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str]
    file_type: Mapped[str]
    file_size: Mapped[int]
    content_hash: Mapped[str] = mapped_column(index=True)
    processing_status: Mapped[str] = mapped_column(default="ready")
    extraction_status: Mapped[str] = mapped_column(default="ready")
    chunk_count: Mapped[int | None]
    embedding_status: Mapped[str] = mapped_column(default="pending")
    version: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(default=True)
    storage_reference: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class AnalysisSession(Base):
    """One continuous investigation thread -- both Ask DataWise Q&A turns
    and Analysis Workspace runs are persisted as Messages under a session,
    so either surface can be reopened and continued (Phase 4 continuation
    sections 14-17, 30, 49)."""

    __tablename__ = "analysis_sessions"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    """A single turn's user-visible content -- never hidden chain-of-thought.

    `kind` distinguishes an Ask DataWise conversational turn ("agent_answer")
    from an Analysis Workspace run ("analysis_run"); `content` holds the
    question/summary text and `message_metadata` holds the structured
    payload (AgentAnswer or AnalysisRequest+Result, as plain JSON) needed to
    restore or re-render the turn -- see app/api/sessions.py.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str]
    kind: Mapped[str] = mapped_column(default="agent_answer")
    content: Mapped[str]
    message_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="messages")


class Report(Base):
    """A generated PDF, kept on disk under data/reports/{user_id}/{id}.pdf --
    `storage_reference` is that path (relative to the configured reports
    dir), so reopening a report serves the existing file instead of calling
    the PDF renderer again."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_sessions.id", ondelete="SET NULL"))
    title: Mapped[str]
    dataset_reference: Mapped[str | None]
    storage_reference: Mapped[str]
    email_status: Mapped[str] = mapped_column(default="not_sent")  # not_sent | pending | sent | failed
    email_recipient: Mapped[str | None]
    email_sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
