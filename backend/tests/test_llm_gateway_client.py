"""build_llm_gateway(): selects the primary provider exactly like
build_llm_client() always has, then adds configured fallback providers in
priority order, bounded by MAX_LLM_FALLBACKS. Never hits a real LLM API."""

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.client import build_llm_gateway
from app.ai.gateway import LLMGateway
from app.ai.gemini_provider import GeminiProvider
from app.ai.groq_provider import GroqProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_missing_provider_returns_none():
    settings = _settings(llm_provider=None, openai_api_key="sk-test")
    assert build_llm_gateway(settings) is None


def test_primary_configured_with_no_other_keys_returns_single_provider_gateway():
    settings = _settings(llm_provider="openai", openai_api_key="sk-test")
    gateway = build_llm_gateway(settings)
    assert isinstance(gateway, LLMGateway)
    assert len(gateway._providers) == 1
    assert isinstance(gateway._providers[0], OpenAIProvider)


def test_primary_not_configured_returns_none_even_if_other_providers_are():
    # A different provider having a key must never silently become primary --
    # an explicitly requested but unconfigured primary is an honest failure.
    settings = _settings(llm_provider="openai", openai_api_key=None, gemini_api_key="sk-gemini-test")
    assert build_llm_gateway(settings) is None


def test_fallbacks_added_in_priority_order():
    settings = _settings(
        llm_provider="openai",
        openai_api_key="sk-openai",
        gemini_api_key="sk-gemini",
        groq_api_key="sk-groq",
        openrouter_api_key="sk-openrouter",
        max_llm_fallbacks=10,
    )
    gateway = build_llm_gateway(settings)
    types = [type(p) for p in gateway._providers]
    assert types == [OpenAIProvider, GeminiProvider, GroqProvider, OpenRouterProvider]


def test_fallbacks_bounded_by_max_llm_fallbacks():
    settings = _settings(
        llm_provider="openai",
        openai_api_key="sk-openai",
        gemini_api_key="sk-gemini",
        groq_api_key="sk-groq",
        openrouter_api_key="sk-openrouter",
        max_llm_fallbacks=1,
    )
    gateway = build_llm_gateway(settings)
    assert len(gateway._providers) == 2  # primary + exactly 1 fallback
    assert isinstance(gateway._providers[1], GeminiProvider)


def test_anthropic_can_still_be_selected_as_primary():
    settings = _settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    gateway = build_llm_gateway(settings)
    assert isinstance(gateway._providers[0], AnthropicProvider)


def test_anthropic_can_be_a_fallback_when_configured():
    settings = _settings(
        llm_provider="openai", openai_api_key="sk-openai", anthropic_api_key="sk-ant-test", max_llm_fallbacks=10
    )
    gateway = build_llm_gateway(settings)
    assert any(isinstance(p, AnthropicProvider) for p in gateway._providers)


def test_generic_override_key_applies_only_to_primary_not_fallbacks():
    # LLM_API_KEY is set generically (no provider-specific key for openai),
    # gemini has its own real key -- the override must not leak into gemini.
    settings = _settings(
        llm_provider="openai",
        llm_api_key="sk-generic-override",
        gemini_api_key="sk-gemini-real",
        max_llm_fallbacks=10,
    )
    gateway = build_llm_gateway(settings)
    assert isinstance(gateway._providers[0], OpenAIProvider)
    assert isinstance(gateway._providers[1], GeminiProvider)


def test_never_exposes_the_api_key_in_repr():
    settings = _settings(llm_provider="openai", openai_api_key="sk-super-secret-value")
    gateway = build_llm_gateway(settings)
    assert "sk-super-secret-value" not in repr(gateway)
    assert "sk-super-secret-value" not in repr(gateway._providers[0])
