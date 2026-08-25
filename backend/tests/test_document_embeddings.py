"""Phase 4: embedding-based document retrieval. Uses a fake local Embeddings
double (never the real network-backed HuggingFace model) so these tests are
deterministic and offline -- the real model is exercised separately by the
existing test_document_chunking_and_retrieval.py suite, which transparently
uses whatever embedder app.embeddings.provider.get_embedder() resolves to.
"""

from datetime import datetime, timezone

import numpy as np
import pytest
from langchain_core.embeddings import Embeddings

from app.documents.models import ChunkLocation, DocumentChunk, DocumentSummary, DocumentType
from app.documents.store import DocumentStore
from app.embeddings.provider import get_embedder


class FakeEmbeddings(Embeddings):
    """Deterministic hash-based fake embedder -- same text always yields
    the same vector, semantically-similar-by-construction texts (sharing a
    keyword) get closer vectors. No model download, no network."""

    def __init__(self):
        self.embed_documents_calls: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        # A tiny bag-of-keywords embedding: presence of each keyword sets one axis.
        keywords = ["revenue", "supply", "footwear", "electronics", "unrelated"]
        return [1.0 if kw in text.lower() else 0.0 for kw in keywords] or [0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class RaisingEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("simulated embedding backend failure")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("simulated embedding backend failure")


def _summary(doc_id: str, filename: str) -> DocumentSummary:
    return DocumentSummary(
        id=doc_id, filename=filename, document_type=DocumentType.TXT,
        chunk_count=0, char_count=0, created_at=datetime.now(timezone.utc),
    )


def _chunk(doc_id: str, chunk_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(id=chunk_id, document_id=doc_id, document_name="doc.txt", chunk_index=0, text=text, location=ChunkLocation())


def test_default_embedder_is_huggingface_not_openai():
    # The Settings field default (no .env / env var override at all) must
    # be "huggingface" -- DataWise must work without OpenAI embedding
    # credits. (This is the schema default, independent of whatever the
    # project's real .env currently has EMBEDDING_PROVIDER set to.)
    from app.config import Settings

    assert Settings(_env_file=None).embedding_provider == "huggingface"


def test_retrieval_uses_embedder_when_available(tmp_path, monkeypatch):
    fake = FakeEmbeddings()
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: fake)

    store = DocumentStore(storage_dir=tmp_path)
    store.put(
        _summary("doc1", "doc.txt"),
        [
            _chunk("doc1", "c1", "Revenue increased due to a supply disruption."),
            _chunk("doc1", "c2", "This paragraph is completely unrelated filler text."),
        ],
    )

    results = store.retrieve("revenue supply", top_k=5)

    assert len(results) == 1  # only the chunk sharing keywords has score > 0
    assert results[0].chunk.id == "c1"
    assert fake.embed_documents_calls  # embedder was actually used, not just constructed


def test_retrieval_falls_back_to_tfidf_when_embedder_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: RaisingEmbeddings())

    store = DocumentStore(storage_dir=tmp_path)
    store.put(
        _summary("doc1", "doc.txt"),
        [_chunk("doc1", "c1", "Footwear was the strongest category by volume this quarter.")],
    )

    results = store.retrieve("footwear category", top_k=5)

    assert len(results) == 1
    assert results[0].chunk.id == "c1"


def test_retrieval_falls_back_to_tfidf_when_no_embedder_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: None)

    store = DocumentStore(storage_dir=tmp_path)
    store.put(
        _summary("doc1", "doc.txt"),
        [_chunk("doc1", "c1", "Electronics revenue grew twenty percent year over year.")],
    )

    results = store.retrieve("electronics revenue", top_k=5)

    assert len(results) == 1


def test_embeddings_are_cached_per_chunk_not_recomputed_on_every_call(tmp_path, monkeypatch):
    fake = FakeEmbeddings()
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: fake)

    store = DocumentStore(storage_dir=tmp_path)
    store.put(_summary("doc1", "doc.txt"), [_chunk("doc1", "c1", "Revenue increased this quarter.")])
    store.retrieve("revenue", top_k=5)
    first_call_count = len(fake.embed_documents_calls)

    # A second retrieve() with no new chunks must not re-embed anything.
    store.retrieve("revenue", top_k=5)
    assert len(fake.embed_documents_calls) == first_call_count

    # Adding a second document only embeds the NEW chunk, not c1 again.
    store.put(_summary("doc2", "doc2.txt"), [_chunk("doc2", "c2", "Unrelated filler paragraph.")])
    store.retrieve("revenue", top_k=5)
    new_texts_embedded = fake.embed_documents_calls[-1]
    assert new_texts_embedded == ["Unrelated filler paragraph."]


def test_document_metadata_preserved_through_embedding_retrieval(tmp_path, monkeypatch):
    fake = FakeEmbeddings()
    monkeypatch.setattr("app.documents.store.get_embedder", lambda: fake)

    store = DocumentStore(storage_dir=tmp_path)
    chunk = DocumentChunk(
        id="c1", document_id="doc1", document_name="management_report.pdf", chunk_index=0,
        text="Revenue increased due to a supply disruption.", location=ChunkLocation(page=3),
    )
    store.put(_summary("doc1", "management_report.pdf"), [chunk])

    results = store.retrieve("revenue supply", top_k=5)

    assert results[0].chunk.document_id == "doc1"
    assert results[0].chunk.document_name == "management_report.pdf"
    assert results[0].chunk.location.page == 3
