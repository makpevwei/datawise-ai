"""OpenRouter's API is OpenAI-compatible (including tool calling), so this
is a thin subclass of OpenAIProvider pointed at OpenRouter's base_url --
no new SDK dependency."""

from app.ai.openai_provider import OpenAIProvider

DEFAULT_MODEL = "openai/gpt-4.1"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAIProvider):
    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        temperature: float | None = 0.0,
    ):
        super().__init__(
            api_key=api_key,
            model=model or DEFAULT_MODEL,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout=timeout,
            temperature=temperature,
        )
