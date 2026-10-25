import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # Annotated[..., NoDecode] turns OFF pydantic-settings' automatic
    # JSON-decoding of this env var. Without it, the env source tries to
    # json.loads() the raw CORS_ORIGINS string *before* the validator below
    # ever runs -- so a plain, non-JSON value raises SettingsError at the
    # source level and the validator never gets a chance to normalize it.
    # With NoDecode, the raw string reaches _parse_cors_origins untouched.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Accept the forms a human actually types into a deploy dashboard,
        not just the JSON array pydantic-settings demands by default.

        A plain `list[str]` field makes pydantic-settings parse the
        CORS_ORIGINS env var as JSON -- so `https://app.example.com` or
        `https://a.com,https://b.com` (the obvious things to type in
        Render's env-var UI) each raise SettingsError. Because
        get_settings() runs at import time in app.main, that error crashes
        the whole backend at startup: uvicorn never binds, the health check
        fails, the deploy is marked failed, and the frontend -- which needs
        this API for every page -- hangs or errors. An empty CORS_ORIGINS=
        (easy to leave set in a dashboard) crashed it too.

        So, before validation, normalize a string into a list ourselves:
          - "" / whitespace            -> []  (no origins, no crash)
          - '["https://a","https://b"]' -> parsed as JSON (back-compat)
          - "https://a, https://b"      -> split on commas, trimmed
        A value that's already a list (e.g. the in-code default) is passed
        through untouched.
        """
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                # Looks like the documented JSON-array form; let json parse
                # it so a genuinely malformed array still fails loudly
                # rather than being silently misread as one long origin.
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    # Used to build the link inside a password-reset email (e.g.
    # "{frontend_base_url}/reset-password?token=..."). Falls back to the
    # first CORS origin if unset, since that's almost always the deployed
    # frontend anyway -- but an explicit value avoids that assumption
    # breaking if CORS_ORIGINS ever lists something else first.
    frontend_base_url: str | None = None

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

    # Google Drive/Sheets connector (read-only). All optional -- every other
    # feature works with none of these set; the /integrations/google/*
    # routes report "not configured" honestly rather than pretending to
    # work. google_oauth_redirect_uri must exactly match an Authorized
    # redirect URI configured on the Google Cloud OAuth client, including
    # scheme/host/path -- Google rejects any mismatch outright.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None
    # Fernet key (base64, via cryptography.fernet.Fernet.generate_key())
    # encrypting Integration.encrypted_refresh_token at rest -- see
    # app/integrations/crypto.py. Unlike the settings above, this one is
    # required the moment google_oauth_client_id is set: a connected
    # integration's refresh token has nowhere safe to live without it.
    token_encryption_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
