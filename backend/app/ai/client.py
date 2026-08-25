"""LLM provider factory.

Primary interface is LLM_PROVIDER / LLM_API_KEY / LLM_MODEL (never
hardcoded). Falls back to a provider-specific key/model (OPENAI_API_KEY,
etc.) when the generic ones are unset, so the broader multi-provider .env
schema drafted in .env.example works without duplicating the key under
two names. Returns None when nothing is configured -- callers must
degrade honestly rather than fabricate a response. Never logs or returns
the API key itself.

build_llm_client()/is_llm_configured() are the original Phase 3 single-
provider surface -- unchanged, still returns a bare provider, still what
tests/test_llm_client.py exercises. build_llm_gateway() is the Phase 3A
addition: it builds the same primary provider plus any other configured
providers as fallbacks (fixed priority order below) and wraps them in an
LLMGateway for retry/fallback/metadata. app/api/deps.get_llm_provider()
is what the running app actually calls.
"""

from functools import lru_cache

from app.ai.base import LLMProvider
from app.config import Settings, get_settings

SUPPORTED_PROVIDERS = ("anthropic", "openai")

# All providers the gateway knows how to build. Order matches the priority
# documented in .env.example (OpenAI, Gemini, Groq, OpenRouter); anthropic
# is appended last purely to preserve it as an available fallback without
# promoting it ahead of the documented default order.
GATEWAY_PROVIDER_PRIORITY = ("openai", "gemini", "groq", "openrouter", "anthropic")


def _resolve_api_key(settings: Settings) -> str | None:
    if settings.llm_api_key:
        return settings.llm_api_key
    provider = (settings.llm_provider or "").strip().lower()
    if provider == "openai":
        return settings.openai_api_key
    if provider == "anthropic":
        return settings.anthropic_api_key
    return None


def _resolve_model(settings: Settings) -> str | None:
    if settings.llm_model:
        return settings.llm_model
    provider = (settings.llm_provider or "").strip().lower()
    if provider == "openai":
        return settings.openai_model
    return None


def is_llm_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.llm_provider and _resolve_api_key(settings))


def build_llm_client(settings: Settings | None = None) -> LLMProvider | None:
    settings = settings or get_settings()
    api_key = _resolve_api_key(settings)
    if not settings.llm_provider or not api_key:
        return None

    provider = settings.llm_provider.strip().lower()
    model = _resolve_model(settings)
    if provider == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)
    if provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model)

    return None


@lru_cache
def get_llm_client() -> LLMProvider | None:
    return build_llm_client()


def _gateway_api_key_for(provider: str, settings: Settings) -> str | None:
    return {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
    }.get(provider)


def _gateway_model_for(provider: str, settings: Settings) -> str | None:
    per_provider = {
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
        "groq": settings.groq_model,
        "openrouter": settings.openrouter_model,
        "anthropic": None,  # no anthropic-specific model field
    }.get(provider)
    return per_provider or settings.default_model


def _build_gateway_provider(
    provider: str, api_key: str, model: str | None, settings: Settings
) -> LLMProvider | None:
    if provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, timeout=settings.llm_timeout, temperature=settings.temperature)
    if provider == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model, timeout=settings.llm_timeout, temperature=settings.temperature)
    if provider == "gemini":
        from app.ai.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=api_key, model=model, timeout=settings.llm_timeout, temperature=settings.temperature)
    if provider == "groq":
        from app.ai.groq_provider import GroqProvider

        return GroqProvider(api_key=api_key, model=model, timeout=settings.llm_timeout, temperature=settings.temperature)
    if provider == "openrouter":
        from app.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(
            api_key=api_key,
            model=model,
            base_url=settings.openrouter_base_url,
            timeout=settings.llm_timeout,
            temperature=settings.temperature,
        )
    return None


def _build_gateway_candidate(provider: str, settings: Settings, *, is_primary: bool) -> LLMProvider | None:
    # The generic LLM_API_KEY/LLM_MODEL override only ever applied to
    # "the one configured provider" in Phase 3 -- preserved here as
    # applying only to whichever provider is primary, never to an
    # auto-discovered fallback (which has no way to know the generic
    # override was meant for it).
    api_key = (settings.llm_api_key if is_primary else None) or _gateway_api_key_for(provider, settings)
    if not api_key:
        return None
    model = (settings.llm_model if is_primary else None) or _gateway_model_for(provider, settings)
    return _build_gateway_provider(provider, api_key, model, settings)


def build_llm_gateway(settings: Settings | None = None) -> LLMProvider | None:
    """Builds the primary provider (same selection as build_llm_client)
    plus up to MAX_LLM_FALLBACKS additional configured providers, in
    GATEWAY_PROVIDER_PRIORITY order, wrapped in an LLMGateway. Returns
    None under the exact same conditions build_llm_client() would --
    the primary provider must be explicitly selected and configured;
    fallbacks never substitute for a missing/misconfigured primary."""
    settings = settings or get_settings()
    primary_name = (settings.llm_provider or "").strip().lower()
    if not primary_name:
        return None

    primary = _build_gateway_candidate(primary_name, settings, is_primary=True)
    if primary is None:
        return None

    providers = [primary]
    for name in GATEWAY_PROVIDER_PRIORITY:
        if name == primary_name:
            continue
        if len(providers) - 1 >= settings.max_llm_fallbacks:
            break
        candidate = _build_gateway_candidate(name, settings, is_primary=False)
        if candidate is not None:
            providers.append(candidate)

    from app.ai.gateway import LLMGateway

    return LLMGateway(providers=providers, max_retries=settings.max_retries, retry_backoff=settings.retry_backoff)


@lru_cache
def get_llm_gateway() -> LLMProvider | None:
    return build_llm_gateway()
