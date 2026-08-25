"""Provider gateway: primary provider -> retry transient failures on that
same provider -> configured fallback provider(s) in priority order ->
honest final failure. Bounded by MAX_RETRIES (same-provider retries) and
MAX_LLM_FALLBACKS (how many candidate providers were even built -- see
app/ai/client.py), so total attempts per send() call are always finite.

A fallback provider gets exactly one attempt (no retries) before the
gateway moves to the next one -- MAX_RETRIES applies only to the primary.
Retrying every fallback MAX_RETRIES times too would multiply attempts (and
cost/latency) by the fallback count for no real benefit; one attempt per
fallback is enough to route around a provider that's actually down while
still bounding the worst case.
"""

import time

from app.ai.base import LLMProvider
from app.ai.errors import PermanentLLMError, TransientLLMError, redact_secrets
from app.ai.types import ConversationTurn, LLMCallMetadata, LLMTurn, ToolSchema


class LLMGateway(LLMProvider):
    provider_name = "gateway"

    def __init__(self, providers: list[LLMProvider], max_retries: int, retry_backoff: float = 0.0):
        if not providers:
            raise ValueError("LLMGateway requires at least one configured provider")
        self._providers = providers
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff)
        # Reflects the provider that most recently produced a successful
        # turn (starts as the primary) -- for any code that reads these
        # attributes directly rather than turn.metadata.
        self.provider_name = providers[0].provider_name
        self.model = providers[0].model

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        start = time.monotonic()
        attempt_count = 0
        last_error: Exception | None = None

        for index, provider in enumerate(self._providers):
            fallback_used = index > 0
            retries_for_this_provider = self._max_retries if index == 0 else 0

            for retry in range(retries_for_this_provider + 1):
                if retry > 0 and self._retry_backoff:
                    time.sleep(self._retry_backoff)
                attempt_count += 1
                try:
                    turn = provider.send(system, history, tools)
                except PermanentLLMError as exc:
                    last_error = exc
                    break  # never retry a permanent failure -- try the next fallback instead
                except TransientLLMError as exc:
                    last_error = exc
                    continue  # retry the same provider
                else:
                    self.provider_name = provider.provider_name
                    self.model = provider.model
                    latency_ms = int((time.monotonic() - start) * 1000)
                    turn.metadata = LLMCallMetadata(
                        provider=provider.provider_name,
                        model=provider.model,
                        fallback_used=fallback_used,
                        attempt_count=attempt_count,
                        latency_ms=latency_ms,
                    )
                    return turn

        latency_ms = int((time.monotonic() - start) * 1000)
        detail = f" Last error: {redact_secrets(str(last_error))}" if last_error else ""
        message = f"All configured LLM providers failed after {attempt_count} attempt(s).{detail}"
        return LLMTurn(
            text=message,
            tool_calls=[],
            stop_reason="error",
            metadata=LLMCallMetadata(
                provider=self._providers[-1].provider_name,
                model=self._providers[-1].model,
                fallback_used=len(self._providers) > 1,
                attempt_count=attempt_count,
                latency_ms=latency_ms,
            ),
        )
