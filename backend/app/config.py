from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at backend/app/config.py. The backend always runs with
# cwd=backend/ (uv run, uvicorn, pytest), so a bare env_file=".env" only
# ever looks at backend/.env -- but the project's real .env lives at the
# DataWise-AI root, one level above backend/. Check both locations, with
# the backend-local one (if it ever exists) taking precedence.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT_ENV = _BACKEND_DIR.parent / ".env"
_BACKEND_ENV = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT_ENV, _BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DataWise AI"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    cors_origins: list[str] = ["http://localhost:3000"]

    upload_dir: str = "../data/uploads"
    max_upload_size_mb: int = 100

    document_dir: str = "../data/documents"
    max_document_upload_mb: int = 50

    database_url: str | None = None

    # Primary, documented interface (matches .env.example's "actually wired
    # up" section): LLM_PROVIDER / LLM_API_KEY / LLM_MODEL.
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    # Fallback: per-provider key/model names, for the broader multi-provider
    # .env schema drafted at the top of .env.example. Only used when the
    # generic llm_api_key/llm_model above are unset -- see app/ai/client.py.
    openai_api_key: str | None = None
    openai_model: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Used as a last-resort model default (after llm_model and the
    # provider-specific *_model field) for whichever provider is selected --
    # see app/ai/client.py. Each provider also has its own hardcoded
    # DEFAULT_MODEL if this and everything else are unset.
    default_model: str | None = None

    # Gateway resilience / cost controls -- see app/ai/gateway.py.
    llm_timeout: float = 120.0
    max_retries: int = 3
    retry_backoff: float = 2.0
    max_llm_fallbacks: int = 2
    temperature: float = 0.0

    agent_max_tool_iterations: int = 8

    # Phase 4: RAG embeddings. "huggingface" is the default -- a free,
    # local, CPU-friendly model, so DataWise works without any embedding
    # provider credits. "openai" remains available if explicitly selected.
    # See app/embeddings/provider.py.
    embedding_provider: str = "huggingface"
    huggingface_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    openai_embedding_model: str | None = None

    rag_max_retrieval_iterations: int = 3
    rag_max_chunks_per_retrieval: int = 8
    rag_chunk_size_tokens: int = 500
    rag_chunk_overlap_tokens: int = 50

    # Phase 4: web research providers -- all optional, none required. See
    # app/agent/web_research.py. Priority when multiple are configured:
    # Tavily, Exa, Firecrawl, SerpAPI, Google CSE.
    tavily_api_key: str | None = None
    exa_api_key: str | None = None
    firecrawl_api_key: str | None = None
    serpapi_api_key: str | None = None
    google_cse_id: str | None = None
    google_cse_api_key: str | None = None

    search_timeout: float = 60.0
    max_research_queries: int = 6
    max_research_sources: int = 30
    max_research_tool_calls: int = 12

    # Auth. JWT_SECRET_KEY must be set for the app to issue/verify tokens --
    # see app/auth/security.py. A long expiry suits an early-stage
    # single-tenant deployment; there is no refresh-token flow yet.
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    reports_dir: str = "../data/reports"

    # Email delivery for reports (Phase 4 continuation section 33). All
    # optional -- report generation and every other feature works with none
    # of these set; only POST /reports/{id}/email needs them, and it
    # reports "not configured" honestly rather than pretending to send.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
