from app.ai.anthropic_provider import AnthropicProvider
from app.ai.client import build_llm_client, is_llm_configured
from app.ai.openai_provider import OpenAIProvider
from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_not_configured_without_provider():
    settings = _settings(llm_provider=None, llm_api_key="sk-something")
    assert is_llm_configured(settings) is False
    assert build_llm_client(settings) is None


def test_not_configured_without_key():
    settings = _settings(llm_provider="openai", llm_api_key=None)
    assert is_llm_configured(settings) is False
    assert build_llm_client(settings) is None


def test_selects_openai_provider():
    settings = _settings(llm_provider="openai", llm_api_key="sk-test", llm_model="gpt-4o-mini")
    client = build_llm_client(settings)
    assert isinstance(client, OpenAIProvider)
    assert client.model == "gpt-4o-mini"


def test_selects_anthropic_provider():
    settings = _settings(llm_provider="anthropic", llm_api_key="sk-ant-test")
    client = build_llm_client(settings)
    assert isinstance(client, AnthropicProvider)


def test_provider_name_is_case_insensitive():
    settings = _settings(llm_provider="OpenAI", llm_api_key="sk-test")
    assert isinstance(build_llm_client(settings), OpenAIProvider)


def test_unknown_provider_returns_none():
    settings = _settings(llm_provider="not-a-real-provider", llm_api_key="sk-test")
    assert build_llm_client(settings) is None


def test_never_logs_or_exposes_the_key_itself():
    # The key must never appear in a provider's repr/model attribute.
    settings = _settings(llm_provider="openai", llm_api_key="sk-super-secret-value", llm_model=None)
    client = build_llm_client(settings)
    assert "sk-super-secret-value" not in repr(client)
    assert "sk-super-secret-value" not in str(vars(client).get("model"))
