"""Upload Layer -- validates a raw uploaded file before it reaches parsing."""

from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}


class UploadValidationError(Exception):
    """Raised for a file that must be rejected before parsing is attempted."""


@dataclass
class ValidatedUpload:
    filename: str
    extension: str
    content: bytes


def validate_upload(filename: str, content: bytes, max_size_mb: int) -> ValidatedUpload:
    if not filename or "." not in filename:
        raise UploadValidationError(f"{filename or '(unnamed file)'}: file has no extension.")

    extension = "." + filename.rsplit(".", 1)[1].lower()

    if extension == ".xls":
        raise UploadValidationError(
            f"{filename}: legacy .xls format is not supported -- please re-save as .xlsx."
        )
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadValidationError(
            f"{filename}: unsupported file type '{extension}'. Only .csv and .xlsx are accepted."
        )

    if len(content) == 0:
        raise UploadValidationError(f"{filename}: file is empty.")

    max_bytes = max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        size_mb = len(content) / (1024 * 1024)
        raise UploadValidationError(
            f"{filename}: file is {size_mb:.1f}MB, which exceeds the {max_size_mb}MB limit."
        )

    return ValidatedUpload(filename=filename, extension=extension, content=content)
