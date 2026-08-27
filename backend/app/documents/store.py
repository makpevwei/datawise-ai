"""Document registry + retrieval index.

Retrieval prefers embedding-based cosine similarity (app/embeddings) when
an embedder is available -- by default a free local HuggingFace model, so
this needs no API key and runs entirely on-CPU. If no embedder can be
built (model unavailable, misconfigured, or a call fails at retrieval
time), this falls back to the original TF-IDF cosine-similarity index,
which is always built as a safety net. Persists like DatasetStore: JSON
per document under the configured storage directory, reloaded on startup.

Computed chunk embeddings are ALSO cached to disk (embeddings_cache/cache.json),
not just in-memory: the local HuggingFace model is slow per chunk on CPU, and
without disk persistence every process restart would silently force the very
next question to re-embed the entire corpus (every chunk of every document
ever uploaded, by any user, since this store is process-global) before it
could answer -- a multi-minute stall on what looks like a simple question,
and exactly the moment a fresh deploy makes this most likely to happen.
"""

import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.documents.models import DocumentChunk, DocumentSummary, RetrievalResult
from app.embeddings.provider import get_embedder


@dataclass
class DocumentRecord:
    summary: DocumentSummary
    chunks: list[DocumentChunk]


class DocumentStore:
    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, DocumentRecord] = {}
        self._lock = threading.Lock()
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._chunk_index: list[tuple[str, DocumentChunk]] = []
        self._chunk_embeddings: dict[str, list[float]] = {}
        self._embedding_matrix: np.ndarray | None = None
        self._embeddings_cache_path = self._storage_dir / "embeddings_cache" / "cache.json"
        self._dirty = True
        self._load_from_disk()
        self._load_embeddings_cache()

    def _load_embeddings_cache(self) -> None:
        if not self._embeddings_cache_path.exists():
            return
        try:
            self._chunk_embeddings = json.loads(self._embeddings_cache_path.read_text())
        except Exception:  # noqa: BLE001 -- a corrupt cache must not block startup, just re-embed
            self._chunk_embeddings = {}

    def _save_embeddings_cache(self) -> None:
        try:
            self._embeddings_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._embeddings_cache_path.write_text(json.dumps(self._chunk_embeddings))
        except Exception:  # noqa: BLE001 -- caching is an optimization, never fatal
            pass

    def _load_from_disk(self) -> None:
        for meta_path in sorted(self._storage_dir.glob("*.json")):
            try:
                data = json.loads(meta_path.read_text())
                summary = DocumentSummary.model_validate(data["summary"])
                chunks = [DocumentChunk.model_validate(c) for c in data["chunks"]]
            except Exception:  # noqa: BLE001 -- a corrupt cached file must not block startup
                continue
            self._records[summary.id] = DocumentRecord(summary=summary, chunks=chunks)
        self._dirty = True

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def put(self, summary: DocumentSummary, chunks: list[DocumentChunk]) -> None:
        with self._lock:
            self._records[summary.id] = DocumentRecord(summary=summary, chunks=chunks)
            path = self._storage_dir / f"{summary.id}.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": summary.model_dump(mode="json"),
                        "chunks": [c.model_dump(mode="json") for c in chunks],
                    }
                )
            )
            self._dirty = True

    def list_summaries(self) -> list[DocumentSummary]:
        return [r.summary for r in sorted(self._records.values(), key=lambda r: r.summary.created_at)]

    def get(self, document_id: str) -> DocumentRecord | None:
        return self._records.get(document_id)

    def get_chunk(self, document_id: str, chunk_id: str) -> DocumentChunk | None:
        record = self._records.get(document_id)
        if not record:
            return None
        return next((c for c in record.chunks if c.id == chunk_id), None)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            existed = self._records.pop(document_id, None) is not None
            (self._storage_dir / f"{document_id}.json").unlink(missing_ok=True)
            self._dirty = True
            return existed

    def _ensure_index(self) -> None:
        if not self._dirty:
            return
        flat: list[tuple[str, DocumentChunk]] = []
        for doc_id, record in self._records.items():
            for chunk in record.chunks:
                flat.append((doc_id, chunk))
        self._chunk_index = flat
        if not flat:
            self._vectorizer = None
            self._matrix = None
            self._embedding_matrix = None
            self._dirty = False
            return

        texts = [c.text for _, c in flat]

        # Always build the TF-IDF fallback index -- cheap, and it's the
        # safety net if no embedder is available or an embed call fails.
        self._vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
        self._matrix = self._vectorizer.fit_transform(texts)

        embedder = get_embedder()
        if embedder is None:
            self._embedding_matrix = None
            self._dirty = False
            return

        try:
            missing = [(c.id, c.text) for _, c in flat if c.id not in self._chunk_embeddings]
            if missing:
                vectors = embedder.embed_documents([text for _, text in missing])
                for (chunk_id, _), vector in zip(missing, vectors):
                    self._chunk_embeddings[chunk_id] = vector
                self._save_embeddings_cache()
            self._embedding_matrix = np.array([self._chunk_embeddings[c.id] for _, c in flat])
        except Exception:  # noqa: BLE001 -- an embedding failure must degrade to TF-IDF, not crash retrieval
            self._embedding_matrix = None
        self._dirty = False

    def retrieve(
        self, query: str, top_k: int = 5, document_ids: list[str] | None = None
    ) -> list[RetrievalResult]:
        self._ensure_index()
        if not query.strip() or not self._chunk_index:
            return []

        scores = None
        if self._embedding_matrix is not None:
            embedder = get_embedder()
            try:
                query_vec = np.array(embedder.embed_query(query)).reshape(1, -1)
                scores = cosine_similarity(query_vec, self._embedding_matrix)[0]
            except Exception:  # noqa: BLE001 -- fall back to TF-IDF below
                scores = None

        if scores is None:
            if self._vectorizer is None or self._matrix is None:
                return []
            query_vec = self._vectorizer.transform([query])
            scores = cosine_similarity(query_vec, self._matrix)[0]

        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results: list[RetrievalResult] = []
        for i in ranked:
            if scores[i] <= 0:
                continue
            doc_id, chunk = self._chunk_index[i]
            if document_ids and doc_id not in document_ids:
                continue
            results.append(RetrievalResult(chunk=chunk, relevance_score=round(float(scores[i]), 4)))
            if len(results) >= top_k:
                break
        return results
