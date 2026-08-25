"""Provider construction + error classification for OpenAI and the three
OpenAI-compatible providers (Gemini, Groq, OpenRouter) built on top of it,
plus Anthropic. All mocked at the SDK client boundary -- no real network
calls, no real credentials."""

from unittest.mock import MagicMock

import anthropic
import httpx
import openai
import pytest

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.errors import PermanentLLMError, TransientLLMError
from app.ai.gemini_provider import GeminiProvider
from app.ai.groq_provider import GroqProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.ai.types import ConversationTurn

OPENAI_COMPATIBLE_PROVIDERS = [OpenAIProvider, GeminiProvider, GroqProvider, OpenRouterProvider]


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    return httpx.Response(status_code, request=request)


@pytest.mark.parametrize(
    "provider_cls, expected_base_url, default_model",
    [
        (OpenAIProvider, None, "gpt-4o-mini"),
        (GeminiProvider, "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-pro"),
        (GroqProvider, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        (OpenRouterProvider, "https://openrouter.ai/api/v1", "openai/gpt-4.1"),
    ],
)
def test_default_model_and_base_url(provider_cls, expected_base_url, default_model):
    provider = provider_cls(api_key="test-key")
    assert provider.model == default_model
    if expected_base_url is not None:
        assert str(provider._client.base_url).rstrip("/") == expected_base_url.rstrip("/")


def test_openrouter_base_url_is_configurable():
    provider = OpenRouterProvider(api_key="test-key", base_url="https://custom.example/v1")
    assert str(provider._client.base_url).rstrip("/") == "https://custom.example/v1"


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_successful_send_returns_end_turn(provider_cls):
    provider = provider_cls(api_key="test-key", model="test-model")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="hello", tool_calls=None), finish_reason="stop")]
    provider._client.chat.completions.create = MagicMock(return_value=mock_response)

    turn = provider.send("system", [ConversationTurn(role="user", text="hi")], [])

    assert turn.stop_reason == "end_turn"
    assert turn.text == "hello"


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_timeout_is_transient(provider_cls):
    provider = provider_cls(api_key="test-key")
    request = httpx.Request("POST", "https://example.invalid")
    provider._client.chat.completions.create = MagicMock(side_effect=openai.APITimeoutError(request=request))

    with pytest.raises(TransientLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_rate_limit_is_transient(provider_cls):
    provider = provider_cls(api_key="test-key")
    err = openai.RateLimitError("rate limited", response=_http_response(429), body=None)
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(TransientLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_connection_failure_is_transient(provider_cls):
    provider = provider_cls(api_key="test-key")
    request = httpx.Request("POST", "https://example.invalid")
    err = openai.APIConnectionError(request=request)
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(TransientLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_server_error_is_transient(provider_cls):
    provider = provider_cls(api_key="test-key")
    err = openai.InternalServerError("server error", response=_http_response(500), body=None)
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(TransientLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_authentication_failure_is_permanent(provider_cls):
    provider = provider_cls(api_key="test-key")
    err = openai.AuthenticationError("invalid api key", response=_http_response(401), body=None)
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(PermanentLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


@pytest.mark.parametrize("provider_cls", OPENAI_COMPATIBLE_PROVIDERS)
def test_bad_request_is_permanent(provider_cls):
    provider = provider_cls(api_key="test-key")
    err = openai.BadRequestError("malformed request", response=_http_response(400), body=None)
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(PermanentLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


def test_anthropic_timeout_is_transient():
    provider = AnthropicProvider(api_key="test-key")
    request = httpx.Request("POST", "https://example.invalid")
    provider._client.messages.create = MagicMock(side_effect=anthropic.APITimeoutError(request=request))

    with pytest.raises(TransientLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


def test_anthropic_authentication_failure_is_permanent():
    provider = AnthropicProvider(api_key="test-key")
    err = anthropic.AuthenticationError("bad key", response=_http_response(401), body=None)
    provider._client.messages.create = MagicMock(side_effect=err)

    with pytest.raises(PermanentLLMError):
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])


def test_provider_error_messages_never_contain_the_api_key():
    provider = OpenAIProvider(api_key="test-key")
    err = openai.AuthenticationError(
        "Incorrect API key provided: sk-testFAKESECRETVALUE1234567890",
        response=_http_response(401),
        body=None,
    )
    provider._client.chat.completions.create = MagicMock(side_effect=err)

    with pytest.raises(PermanentLLMError) as exc_info:
        provider.send("system", [ConversationTurn(role="user", text="hi")], [])

    assert "sk-testFAKESECRETVALUE1234567890" not in str(exc_info.value)
