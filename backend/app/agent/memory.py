"""Lightweight, in-process conversation memory for the current session only.

No persistence across process restarts and no long-term user memory --
matches the Phase 3 scope of "current analysis session" context only
(e.g. "Show revenue by region." -> "Only 2025." -> "Now show the bottom three.").
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_TURNS_REMEMBERED = 6


@dataclass
class MemoryTurn:
    question: str
    answer_summary: str
    timestamp: datetime


class ConversationMemory:
    def __init__(self):
        self._sessions: dict[str, list[MemoryTurn]] = {}
        self._lock = threading.Lock()

    def get_history(self, session_id: str) -> list[MemoryTurn]:
        return list(self._sessions.get(session_id, []))

    def append(self, session_id: str, question: str, answer_summary: str) -> None:
        with self._lock:
            turns = self._sessions.setdefault(session_id, [])
            turns.append(
                MemoryTurn(question=question, answer_summary=answer_summary, timestamp=datetime.now(UTC))
            )
            if len(turns) > MAX_TURNS_REMEMBERED:
                del turns[: len(turns) - MAX_TURNS_REMEMBERED]

    def format_for_prompt(self, session_id: str) -> str | None:
        turns = self.get_history(session_id)
        if not turns:
            return None
        return "\n\n".join(f"Q: {t.question}\nA (summary): {t.answer_summary}" for t in turns)
