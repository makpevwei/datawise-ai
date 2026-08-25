"""End-to-end validate -> extract -> chunk -> index for the document
ingestion service, focused on Phase 4's new .py support and confirming
filename/document_id/source-type metadata survives the whole pipeline."""

from app.documents.models import DocumentType
from app.documents.service import ingest_documents
from app.documents.store import DocumentStore
from app.documents.validation import DocumentValidationError, validate_document_upload


def test_validate_document_upload_accepts_py_extension():
    validated = validate_document_upload("script.py", b"print('hi')\n", max_size_mb=10)
    assert validated.document_type == DocumentType.PY


def test_validate_document_upload_rejects_unknown_extension():
    try:
        validate_document_upload("data.exe", b"binary", max_size_mb=10)
        assert False, "expected DocumentValidationError"
    except DocumentValidationError as exc:
        assert ".py" in str(exc)  # accepted-extensions list mentions .py


def test_ingest_py_file_end_to_end(tmp_path):
    store = DocumentStore(storage_dir=tmp_path)
    content = b"def calculate_total(items):\n    return sum(items)\n"
    result = ingest_documents([("billing.py", content)], store, max_size_mb=10)

    assert result.errors == []
    assert len(result.documents) == 1
    summary = result.documents[0]
    assert summary.filename == "billing.py"
    assert summary.document_type == DocumentType.PY
    assert summary.chunk_count >= 1

    stored = store.get(summary.id)
    assert stored is not None
    assert stored.chunks[0].document_id == summary.id
    assert stored.chunks[0].document_name == "billing.py"
    assert stored.chunks[0].location.heading == "def calculate_total"


def test_ingest_mixed_batch_one_bad_file_does_not_block_others(tmp_path):
    store = DocumentStore(storage_dir=tmp_path)
    files = [
        ("good.py", b"def ok():\n    return 1\n"),
        ("bad.exe", b"binary junk"),
    ]
    result = ingest_documents(files, store, max_size_mb=10)

    assert len(result.documents) == 1
    assert result.documents[0].filename == "good.py"
    assert len(result.errors) == 1
    assert result.errors[0].file == "bad.exe"


# -- HTML (Phase 4A) ------------------------------------------------------


def test_validate_document_upload_accepts_html_and_htm_extensions():
    for filename in ("page.html", "page.htm"):
        validated = validate_document_upload(filename, b"<p>hi</p>", max_size_mb=10)
        assert validated.document_type == DocumentType.HTML


def test_ingest_html_file_end_to_end_metadata(tmp_path):
    store = DocumentStore(storage_dir=tmp_path)
    content = b"""
    <html><body>
        <h1>Regional Performance</h1>
        <p>West Africa underperformed due to slower fulfillment.</p>
    </body></html>
    """
    result = ingest_documents([("commentary.html", content)], store, max_size_mb=10)

    assert result.errors == []
    assert len(result.documents) == 1
    summary = result.documents[0]
    assert summary.filename == "commentary.html"
    assert summary.document_type == DocumentType.HTML
    assert summary.chunk_count >= 1

    stored = store.get(summary.id)
    assert stored.chunks[0].document_id == summary.id
    assert stored.chunks[0].document_name == "commentary.html"
    assert stored.chunks[0].location.heading == "Regional Performance"


def test_html_document_is_retrievable_and_citable(tmp_path, monkeypatch):
    # Force the TF-IDF fallback path for a fast, deterministic retrieval
    # check independent of the embedding model.
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: None)

    store = DocumentStore(storage_dir=tmp_path)
    content = b"""
    <html><body>
        <h1>Regional Performance</h1>
        <p>West Africa underperformed due to slower Standard Class fulfillment.</p>
    </body></html>
    """
    result = ingest_documents([("commentary.html", content)], store, max_size_mb=10)
    document_id = result.documents[0].id

    results = store.retrieve("West Africa Standard Class fulfillment", top_k=3)

    assert len(results) == 1
    assert results[0].chunk.document_id == document_id
    assert results[0].chunk.document_name == "commentary.html"
    assert results[0].chunk.location.heading == "Regional Performance"

    # Citable: the exact chunk is independently retrievable by (document_id, chunk_id).
    chunk = store.get_chunk(document_id, results[0].chunk.id)
    assert chunk is not None
    assert "West Africa" in chunk.text
