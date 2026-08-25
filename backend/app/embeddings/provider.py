"""Embedding provider factory.

Default is "huggingface": a free, local, CPU-friendly sentence-transformers
model (all-MiniLM-L6-v2 by default) via LangChain's HuggingFaceEmbeddings --
no API key, no per-call cost, no network dependency once the model is
cached locally. See docs/embeddings.md for why this model was chosen.

"openai" remains available (EMBEDDING_PROVIDER=openai) for anyone who
wants OpenAI's embedding quality/latency instead and already has credits;
DataWise must never *require* it. Implemented directly against the openai
SDK (already a dependency) rather than adding langchain-openai just for
this optional secondary path.
"""

from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.config import Settings, get_settings

DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIEmbeddings(Embeddings):
    """Minimal LangChain-compatible wrapper over the openai SDK's
    embeddings endpoint -- used only when EMBEDDING_PROVIDER=openai."""

    def __init__(self, api_key: str, model: str | None = None):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model or DEFAULT_OPENAI_EMBEDDING_MODEL

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class EmbeddingNotConfiguredError(Exception):
    """Raised when embedding_provider="openai" but no OpenAI key is set."""


def _build_embedder(settings: Settings) -> Embeddings:
    provider = (settings.embedding_provider or "huggingface").strip().lower()
    if provider == "openai":
        if not settings.openai_api_key and not settings.llm_api_key:
            raise EmbeddingNotConfiguredError(
                "EMBEDDING_PROVIDER=openai but no OPENAI_API_KEY (or LLM_API_KEY) is configured."
            )
        api_key = settings.openai_api_key or settings.llm_api_key
        return OpenAIEmbeddings(api_key=api_key, model=settings.openai_embedding_model)

    # Default / "huggingface": a free local model, no credentials needed.
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=settings.huggingface_embedding_model)


@lru_cache
def get_embedder() -> Embeddings | None:
    """Returns None (never raises) if embeddings can't be constructed --
    document retrieval falls back to TF-IDF. Cached: the HuggingFace model
    is expensive to load and should only happen once per process."""
    settings = get_settings()
    try:
        return _build_embedder(settings)
    except Exception:  # noqa: BLE001 -- any failure here must degrade to TF-IDF, never crash retrieval
        return None
