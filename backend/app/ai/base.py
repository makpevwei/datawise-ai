from abc import ABC, abstractmethod

from app.ai.types import ConversationTurn, LLMTurn, ToolSchema


class LLMNotConfiguredError(Exception):
    """Raised when no LLM provider/API key is configured.

    Callers must catch this and return an honest "AI features are not
    configured" response -- never a fabricated answer.
    """


class LLMProvider(ABC):
    provider_name: str
    model: str

    @abstractmethod
    def send(
        self,
        system: str,
        history: list[ConversationTurn],
        tools: list[ToolSchema],
    ) -> LLMTurn:
        """Send the conversation so far and return the model's next turn."""
