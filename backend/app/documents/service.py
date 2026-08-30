"""Document ingestion orchestration: validate -> extract -> clean -> chunk -> index.

Mirrors app/upload/service.py's shape: one bad file never blocks the rest
of a multi-file upload; every failure becomes a DocumentUploadError.
"""

from datetime import UTC, datetime

from app.documents.chunking import chunk_segments
from app.documents.extraction import (
    ExtractionError,
    extract_docx,
    extract_html,
    extract_pdf,
    extract_pptx,
    extract_text_like,
)
from app.documents.models import DocumentSummary, DocumentType, DocumentUploadError, DocumentUploadResult
from app.documents.store import DocumentStore
from app.documents.validation import DocumentValidationError, validate_document_upload

EXTRACTORS = {
    DocumentType.PDF: extract_pdf,
    DocumentType.DOCX: extract_docx,
    DocumentType.PPTX: extract_pptx,
    DocumentType.HTML: extract_html,
}


def ingest_documents(
    files: list[tuple[str, bytes]],
    store: DocumentStore,
    max_size_mb: int,
) -> DocumentUploadResult:
    summaries: list[DocumentSummary] = []
    errors: list[DocumentUploadError] = []

    for filename, content in files:
        try:
            validated = validate_document_upload(filename, content, max_size_mb)
        except DocumentValidationError as exc:
            errors.append(DocumentUploadError(file=filename, message=str(exc)))
            continue

        try:
            if validated.document_type in (DocumentType.TXT, DocumentType.MD, DocumentType.PY):
                segments, warnings = extract_text_like(validated.content, filename, validated.document_type)
            else:
                extractor = EXTRACTORS[validated.document_type]
                segments, warnings = extractor(validated.content, filename)
        except ExtractionError as exc:
            errors.append(DocumentUploadError(file=filename, message=str(exc)))
            continue

        document_id = store.new_id()
        chunks = chunk_segments(segments, document_id=document_id, document_name=filename)
        char_count = sum(len(c.text) for c in chunks)

        summary = DocumentSummary(
            id=document_id,
            filename=filename,
            document_type=validated.document_type,
            chunk_count=len(chunks),
            char_count=char_count,
            created_at=datetime.now(UTC),
            extraction_warnings=warnings,
        )
        store.put(summary, chunks)
        summaries.append(summary)

    return DocumentUploadResult(documents=summaries, errors=errors)
