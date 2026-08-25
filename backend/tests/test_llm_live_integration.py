"""A SMALL number of REAL integration tests against whichever providers
have live credentials configured in DataWise-AI/.env. Each test is
skipped outright if its provider's key isn't set. Never prints an API key,
DATABASE_URL, or any other credential -- only pass/fail, provider/model
names, and latency are ever surfaced (see app/ai/errors.redact_secrets for
the same discipline applied to failure paths)."""

import pytest

from app.ai.gateway import LLMGateway
from app.ai.gemini_provider import GeminiProvider
from app.ai.groq_provider import GroqProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.ai.types import ConversationTurn
from app.config import get_settings

PING_SYSTEM = "Reply with exactly one word: pong"
PING_HISTORY = [ConversationTurn(role="user", text="ping")]


@pytest.mark.live
@pytest.mark.skipif(not get_settings().openai_api_key, reason="OPENAI_API_KEY not configured")
def test_live_openai_responds():
    settings = get_settings()
    provider = OpenAIProvider(
        api_key=settings.openai_api_key, model=settings.openai_model,
        timeout=settings.llm_timeout, temperature=settings.temperature,
    )
    turn = provider.send(PING_SYSTEM, PING_HISTORY, [])
    assert turn.stop_reason in ("end_turn", "max_tokens")
    assert turn.text


@pytest.mark.live
@pytest.mark.skipif(not get_settings().gemini_api_key, reason="GEMINI_API_KEY not configured")
def test_live_gemini_responds():
    settings = get_settings()
    provider = GeminiProvider(
        api_key=settings.gemini_api_key, model=settings.gemini_model,
        timeout=settings.llm_timeout, temperature=settings.temperature,
    )
    turn = provider.send(PING_SYSTEM, PING_HISTORY, [])
    assert turn.stop_reason in ("end_turn", "max_tokens")
    assert turn.text


@pytest.mark.live
@pytest.mark.skipif(not get_settings().groq_api_key, reason="GROQ_API_KEY not configured")
def test_live_groq_responds():
    settings = get_settings()
    provider = GroqProvider(
        api_key=settings.groq_api_key, model=settings.groq_model,
        timeout=settings.llm_timeout, temperature=settings.temperature,
    )
    turn = provider.send(PING_SYSTEM, PING_HISTORY, [])
    assert turn.stop_reason in ("end_turn", "max_tokens")
    assert turn.text


@pytest.mark.live
@pytest.mark.skipif(not get_settings().openrouter_api_key, reason="OPENROUTER_API_KEY not configured")
def test_live_openrouter_responds():
    settings = get_settings()
    provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key, model=settings.openrouter_model,
        base_url=settings.openrouter_base_url, timeout=settings.llm_timeout, temperature=settings.temperature,
    )
    turn = provider.send(PING_SYSTEM, PING_HISTORY, [])
    assert turn.stop_reason in ("end_turn", "max_tokens")
    assert turn.text


@pytest.mark.live
@pytest.mark.skipif(
    not (get_settings().openai_api_key and get_settings().gemini_api_key),
    reason="requires both OPENAI_API_KEY and GEMINI_API_KEY",
)
def test_live_gateway_falls_back_from_broken_primary_to_real_provider():
    """A deliberately-invalid (not a real leaked key) primary credential
    forces a real 401 from OpenAI; the gateway must fail over to the real,
    correctly-configured Gemini provider and succeed."""
    settings = get_settings()
    broken_primary = OpenAIProvider(
        api_key="sk-deliberately-invalid-for-this-test", model=settings.openai_model, timeout=settings.llm_timeout
    )
    real_fallback = GeminiProvider(
        api_key=settings.gemini_api_key, model=settings.gemini_model,
        timeout=settings.llm_timeout, temperature=settings.temperature,
    )
    gateway = LLMGateway(providers=[broken_primary, real_fallback], max_retries=0)

    turn = gateway.send(PING_SYSTEM, PING_HISTORY, [])

    assert turn.stop_reason == "end_turn"
    assert turn.metadata.fallback_used is True
    assert turn.metadata.provider == "gemini"
