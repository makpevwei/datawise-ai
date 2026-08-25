"""Provider-agnostic types for the LLM abstraction.

Every provider backend (Anthropic, OpenAI, ...) speaks these types --
callers never touch a provider SDK's own message/tool shapes directly.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]
StopReason = Literal["tool_use", "end_turn", "max_tokens", "error"]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class ConversationTurn:
    """One turn of normalized conversation history.

    A user turn carries either free text (`text`) or tool results
    (`tool_results`), never both. An assistant turn may carry text,
    tool_calls, or both.
    """

    role: Role
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the tool's input


@dataclass
class LLMCallMetadata:
    """Non-secret facts about how a turn was actually produced -- safe to
    surface to the UI (e.g. "Answered by OpenAI · gpt-4o-mini"). Never
    carries credentials."""

    provider: str
    model: str
    fallback_used: bool
    attempt_count: int
    latency_ms: int


@dataclass
class LLMTurn:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    raw: Any = None
    metadata: LLMCallMetadata | None = None
