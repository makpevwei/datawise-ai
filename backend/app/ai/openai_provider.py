import json

import openai
from openai import OpenAI

from app.ai.base import LLMProvider
from app.ai.errors import PermanentLLMError, TransientLLMError, redact_secrets
from app.ai.types import ConversationTurn, LLMTurn, ToolCall, ToolSchema

DEFAULT_MODEL = "gpt-4o-mini"

# openai raises these regardless of base_url -- the same classification
# applies whether we're actually hitting OpenAI or an OpenAI-compatible
# endpoint (Groq, OpenRouter, Gemini's compat layer).
_TRANSIENT_EXCEPTIONS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)
_PERMANENT_EXCEPTIONS = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.BadRequestError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
    openai.ConflictError,
)


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        temperature: float | None = 0.0,
    ):
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature

    def _to_messages(self, system: str, history: list[ConversationTurn]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        for turn in history:
            if turn.role == "user":
                if turn.tool_results:
                    for tr in turn.tool_results:
                        messages.append(
                            {"role": "tool", "tool_call_id": tr.tool_call_id, "content": tr.content}
                        )
                else:
                    messages.append({"role": "user", "content": turn.text or ""})
            else:
                message: dict = {"role": "assistant", "content": turn.text}
                if turn.tool_calls:
                    message["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
                        }
                        for tc in turn.tool_calls
                    ]
                messages.append(message)
        return messages

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        kwargs: dict = dict(model=self.model, messages=self._to_messages(system, history))
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]

        try:
            response = self._client.chat.completions.create(**kwargs)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientLLMError(redact_secrets(str(exc))) from exc
        except _PERMANENT_EXCEPTIONS as exc:
            raise PermanentLLMError(redact_secrets(str(exc))) from exc
        except openai.APIError as exc:
            # Any other/unclassified SDK error -- treat as transient so a
            # bounded retry/fallback still gets a chance. MAX_RETRIES and
            # MAX_LLM_FALLBACKS bound the blast radius, so this can't loop
            # forever or blow the cost budget.
            raise TransientLLMError(redact_secrets(str(exc))) from exc

        choice = response.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        if tool_calls:
            stop_reason = "tool_use"
        elif choice.finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        return LLMTurn(text=message.content, tool_calls=tool_calls, stop_reason=stop_reason, raw=response)
