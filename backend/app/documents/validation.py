from dataclasses import dataclass

from app.documents.models import DocumentType

EXTENSION_TO_TYPE = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".pptx": DocumentType.PPTX,
    ".txt": DocumentType.TXT,
    ".md": DocumentType.MD,
    ".py": DocumentType.PY,
    ".html": DocumentType.HTML,
    ".htm": DocumentType.HTML,
}


class DocumentValidationError(Exception):
    pass


@dataclass
class ValidatedDocument:
    filename: str
    document_type: DocumentType
    content: bytes


def validate_document_upload(filename: str, content: bytes, max_size_mb: int) -> ValidatedDocument:
    if not filename or "." not in filename:
        raise DocumentValidationError(f"{filename or '(unnamed file)'}: file has no extension.")

    extension = "." + filename.rsplit(".", 1)[1].lower()
    document_type = EXTENSION_TO_TYPE.get(extension)
    if document_type is None:
        raise DocumentValidationError(
            f"{filename}: unsupported document type '{extension}'. "
            "Accepted: .pdf, .docx, .pptx, .txt, .md, .py, .html, .htm."
        )

    if len(content) == 0:
        raise DocumentValidationError(f"{filename}: file is empty.")

    max_bytes = max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        size_mb = len(content) / (1024 * 1024)
        raise DocumentValidationError(
            f"{filename}: file is {size_mb:.1f}MB, which exceeds the {max_size_mb}MB limit."
        )

    return ValidatedDocument(filename=filename, document_type=document_type, content=content)
