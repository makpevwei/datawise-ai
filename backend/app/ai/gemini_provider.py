"""Gemini exposes an OpenAI-compatible chat completions endpoint
(including tool calling), so this is a thin subclass of OpenAIProvider
pointed at that endpoint -- no google-genai SDK dependency, no duplicated
request/parsing logic. See:
https://ai.google.dev/gemini-api/docs/openai
"""

from app.ai.openai_provider import OpenAIProvider

DEFAULT_MODEL = "gemini-2.5-pro"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiProvider(OpenAIProvider):
    provider_name = "gemini"

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
