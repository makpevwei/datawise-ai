"""Document / RAG semantic models -- the document-side counterpart to
app/semantic/models.py for datasets.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    MD = "md"
    PY = "py"
    HTML = "html"


class ChunkLocation(BaseModel):
    """Where a chunk came from, in a type-appropriate way."""

    page: int | None = None  # PDF
    slide: int | None = None  # PPTX
    slide_title: str | None = None  # PPTX
    heading: str | None = None  # DOCX / MD
    line_start: int | None = None  # TXT / MD
    line_end: int | None = None  # TXT / MD


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    document_name: str
    chunk_index: int
    text: str
    location: ChunkLocation


class DocumentSummary(BaseModel):
    id: str
    filename: str
    document_type: DocumentType
    chunk_count: int
    char_count: int
    created_at: datetime
    extraction_warnings: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    chunk: DocumentChunk
    relevance_score: float


class DocumentUploadError(BaseModel):
    file: str
    message: str


class DocumentUploadResult(BaseModel):
    documents: list[DocumentSummary]
    errors: list[DocumentUploadError] = Field(default_factory=list)
