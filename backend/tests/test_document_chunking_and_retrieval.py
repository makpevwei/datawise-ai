from datetime import datetime, timezone

from app.documents.chunking import MAX_CHUNK_CHARS, chunk_segments
from app.documents.extraction import Segment
from app.documents.models import ChunkLocation, DocumentSummary, DocumentType
from app.documents.store import DocumentStore


def test_chunking_merges_small_adjacent_segments_with_same_location():
    segments = [
        Segment(text="Short line one.", location=ChunkLocation(heading="Intro")),
        Segment(text="Short line two.", location=ChunkLocation(heading="Intro")),
    ]
    chunks = chunk_segments(segments, "doc1", "report.pdf")
    assert len(chunks) == 1
    assert "Short line one." in chunks[0].text
    assert "Short line two." in chunks[0].text


def test_chunking_does_not_merge_across_different_locations():
    segments = [
        Segment(text="Page one text.", location=ChunkLocation(page=1)),
        Segment(text="Page two text.", location=ChunkLocation(page=2)),
    ]
    chunks = chunk_segments(segments, "doc1", "report.pdf")
    assert len(chunks) == 2
    assert chunks[0].location.page == 1
    assert chunks[1].location.page == 2


def test_chunking_splits_long_segment_into_overlapping_windows():
    long_text = "word " * 400  # well over MAX_CHUNK_CHARS
    segments = [Segment(text=long_text, location=ChunkLocation(page=1))]
    chunks = chunk_segments(segments, "doc1", "report.pdf")
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    assert all(c.location.page == 1 for c in chunks)


def test_chunk_ids_are_sequential_and_carry_document_metadata():
    segments = [Segment(text="a", location=ChunkLocation()), Segment(text="b" * 900, location=ChunkLocation(page=3))]
    chunks = chunk_segments(segments, "docX", "notes.md")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.document_id == "docX" and c.document_name == "notes.md" for c in chunks)


def _store_with_documents(tmp_path):
    store = DocumentStore(storage_dir=tmp_path)

    revenue_chunks = chunk_segments(
        [Segment(text="Q2 revenue declined 14.2% due to a supply disruption in the West region.", location=ChunkLocation(page=1))],
        "doc-revenue", "management_report.pdf",
    )
    store.put(
        DocumentSummary(
            id="doc-revenue", filename="management_report.pdf", document_type=DocumentType.PDF,
            chunk_count=len(revenue_chunks), char_count=sum(len(c.text) for c in revenue_chunks),
            created_at=datetime.now(timezone.utc),
        ),
        revenue_chunks,
    )

    hr_chunks = chunk_segments(
        [Segment(text="Employee headcount grew 8% year over year across all departments.", location=ChunkLocation(page=1))],
        "doc-hr", "hr_summary.pdf",
    )
    store.put(
        DocumentSummary(
            id="doc-hr", filename="hr_summary.pdf", document_type=DocumentType.PDF,
            chunk_count=len(hr_chunks), char_count=sum(len(c.text) for c in hr_chunks),
            created_at=datetime.now(timezone.utc),
        ),
        hr_chunks,
    )
    return store


def test_retrieval_ranks_relevant_document_first(tmp_path):
    store = _store_with_documents(tmp_path)
    results = store.retrieve("revenue decline supply disruption", top_k=5)
    assert results[0].chunk.document_name == "management_report.pdf"
    assert results[0].relevance_score > 0


def test_retrieval_result_carries_source_location(tmp_path):
    store = _store_with_documents(tmp_path)
    results = store.retrieve("revenue decline", top_k=1)
    assert results[0].chunk.location.page == 1
    assert results[0].chunk.document_id == "doc-revenue"


def test_retrieval_can_scope_to_specific_documents(tmp_path):
    store = _store_with_documents(tmp_path)
    results = store.retrieve("revenue", top_k=5, document_ids=["doc-hr"])
    assert all(r.chunk.document_id == "doc-hr" for r in results)


def test_retrieval_returns_nothing_for_empty_query(tmp_path):
    store = _store_with_documents(tmp_path)
    assert store.retrieve("", top_k=5) == []


def test_retrieval_on_empty_store_returns_nothing(tmp_path):
    store = DocumentStore(storage_dir=tmp_path)
    assert store.retrieve("anything", top_k=5) == []
