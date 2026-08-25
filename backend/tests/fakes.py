"""Test doubles for the agent layer -- never hits a real LLM API in pytest."""

from app.ai.base import LLMProvider
from app.ai.errors import TransientLLMError
from app.ai.types import ConversationTurn, LLMTurn, ToolSchema


class FakeLLMProvider(LLMProvider):
    """Returns a pre-scripted sequence of turns, one per .send() call."""

    provider_name = "fake"

    def __init__(self, turns: list[LLMTurn]):
        self.model = "fake-model"
        self._turns = list(turns)
        self.calls: list[tuple[str, list[ConversationTurn], list[ToolSchema]]] = []

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        self.calls.append((system, history, tools))
        if not self._turns:
            return LLMTurn(text="(no more scripted turns)", tool_calls=[], stop_reason="end_turn")
        return self._turns.pop(0)


class FakeRaisingProvider(LLMProvider):
    """A provider whose .send() raises a scripted sequence of exceptions
    before (optionally) succeeding with a scripted LLMTurn -- for exercising
    LLMGateway's retry/fallback logic without a real provider SDK."""

    def __init__(self, provider_name: str, to_raise: list[Exception], final_turn: LLMTurn | None = None):
        self.provider_name = provider_name
        self.model = f"{provider_name}-model"
        self._to_raise = list(to_raise)
        self._final_turn = final_turn
        self.call_count = 0

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        self.call_count += 1
        if self._to_raise:
            raise self._to_raise.pop(0)
        if self._final_turn is not None:
            return self._final_turn
        return LLMTurn(text=f"{self.provider_name} succeeded", tool_calls=[], stop_reason="end_turn")


class FakeLLMProviderWithTransientBlip(FakeLLMProvider):
    """Like FakeLLMProvider, but raises TransientLLMError on its very first
    .send() call (simulating one flaky attempt) before behaving normally --
    for testing that an LLMGateway's retry recovers transparently."""

    provider_name = "flaky-fake"

    def __init__(self, turns: list[LLMTurn]):
        super().__init__(turns)
        self._blipped = False

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        if not self._blipped:
            self._blipped = True
            raise TransientLLMError("simulated one-off blip")
        return super().send(system, history, tools)
