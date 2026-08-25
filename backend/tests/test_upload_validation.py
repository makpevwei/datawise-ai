import pytest

from app.upload.validation import UploadValidationError, validate_upload


def test_accepts_valid_csv():
    result = validate_upload("orders.csv", b"a,b\n1,2\n", max_size_mb=10)
    assert result.extension == ".csv"


def test_accepts_valid_xlsx_extension():
    result = validate_upload("orders.xlsx", b"PKzzz", max_size_mb=10)
    assert result.extension == ".xlsx"


def test_rejects_empty_file():
    with pytest.raises(UploadValidationError, match="empty"):
        validate_upload("orders.csv", b"", max_size_mb=10)


def test_rejects_legacy_xls():
    with pytest.raises(UploadValidationError, match="legacy .xls"):
        validate_upload("orders.xls", b"data", max_size_mb=10)


def test_rejects_unsupported_extension():
    with pytest.raises(UploadValidationError, match="unsupported"):
        validate_upload("orders.pdf", b"data", max_size_mb=10)


def test_rejects_file_without_extension():
    with pytest.raises(UploadValidationError, match="no extension"):
        validate_upload("orders", b"data", max_size_mb=10)


def test_rejects_oversized_file():
    with pytest.raises(UploadValidationError, match="exceeds"):
        validate_upload("orders.csv", b"x" * 2000, max_size_mb=0.001)
