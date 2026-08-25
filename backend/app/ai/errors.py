"""Typed failure classes providers raise from send(), plus a defense-in-depth
secret redactor applied to every message built from an SDK exception before
it can reach a log, an LLMTurn, or a final gateway failure message.

TransientLLMError: worth retrying (timeout, rate limit, connection failure,
temporary 5xx). PermanentLLMError: never worth retrying (malformed request,
invalid prompt, auth failure, permanent config error) -- the gateway skips
straight to the next fallback provider instead of burning retries on it.
"""

import re

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"sk-or-[A-Za-z0-9_-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{10,}"),
    re.compile(r"tvly-[A-Za-z0-9_-]{10,}"),
    re.compile(r"fc-[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}"),
    # Catches any leftover "key=..."/"api_key=..." query-param value in a
    # URL that slipped through despite _raise_for_status's clean messages
    # (app/agent/web_research.py) -- e.g. SerpAPI/Google CSE's auth style.
    re.compile(r"(?i)\b(api_key|key|token)=[^&\s'\"]{10,}"),
]


def redact_secrets(text: str) -> str:
    """Best-effort scrub of anything that looks like an API key. The SDKs
    themselves don't echo back full keys in error messages, but this is a
    second layer so a leak can never depend solely on that assumption."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class TransientLLMError(Exception):
    """A provider call failed in a way worth retrying (same provider) or
    falling back from (different provider): timeout, rate limit, connection
    failure, temporary server error."""


class PermanentLLMError(Exception):
    """A provider call failed in a way that will never succeed on retry:
    malformed request, invalid prompt, authentication failure, permanent
    configuration error. The gateway does not retry these -- it moves
    straight to the next configured fallback provider, if any."""
