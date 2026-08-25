import anthropic

from app.ai.base import LLMProvider
from app.ai.errors import PermanentLLMError, TransientLLMError, redact_secrets
from app.ai.types import ConversationTurn, LLMTurn, ToolCall, ToolSchema

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 4096

_TRANSIENT_EXCEPTIONS = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)
_PERMANENT_EXCEPTIONS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.BadRequestError,
    anthropic.NotFoundError,
    anthropic.UnprocessableEntityError,
    anthropic.ConflictError,
)


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float | None = 0.0,
    ):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature

    def _to_messages(self, history: list[ConversationTurn]) -> list[dict]:
        messages: list[dict] = []
        for turn in history:
            if turn.role == "user":
                if turn.tool_results:
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tr.tool_call_id,
                                    "content": tr.content,
                                    **({"is_error": True} if tr.is_error else {}),
                                }
                                for tr in turn.tool_results
                            ],
                        }
                    )
                else:
                    messages.append({"role": "user", "content": turn.text or ""})
            else:
                content: list[dict] = []
                if turn.text:
                    content.append({"type": "text", "text": turn.text})
                for tc in turn.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
                messages.append({"role": "assistant", "content": content})
        return messages

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        kwargs: dict = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=self._to_messages(history),
        )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]

        try:
            response = self._client.messages.create(**kwargs)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientLLMError(redact_secrets(str(exc))) from exc
        except _PERMANENT_EXCEPTIONS as exc:
            raise PermanentLLMError(redact_secrets(str(exc))) from exc
        except anthropic.APIError as exc:
            raise TransientLLMError(redact_secrets(str(exc))) from exc

        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input) for b in response.content if b.type == "tool_use"
        ]
        if tool_calls:
            stop_reason = "tool_use"
        elif response.stop_reason == "max_tokens":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        return LLMTurn(
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=response,
        )
