"""Groq's chat completions API is OpenAI-compatible (including tool
calling and the exception hierarchy the openai SDK raises), so this is a
thin subclass of OpenAIProvider pointed at Groq's base_url -- no new SDK
dependency, no duplicated request/parsing logic."""

from app.ai.openai_provider import OpenAIProvider

DEFAULT_MODEL = "llama-3.3-70b-versatile"
BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAIProvider):
    provider_name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float | None = 0.0,
    ):
        super().__init__(
            api_key=api_key,
            model=model or DEFAULT_MODEL,
            base_url=BASE_URL,
            timeout=timeout,
            temperature=temperature,
        )
