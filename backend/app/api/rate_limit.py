"""Rate limiting for auth endpoints and every endpoint that calls an LLM
provider -- both a live cost-abuse surface (open sign-up + a metered LLM
API key behind it) and a brute-force surface (login, password reset).

In-memory storage (slowapi's default): correct and sufficient for the
current deployment (Cloud Run, min-instances=1, effectively one warm
process most of the time). If this service is ever scaled to multiple
concurrent instances, each instance enforces its own separate counter --
the *effective* limit becomes roughly (configured limit x instance count),
not a hard violation of the limit, but a real gap worth closing with a
shared backend (Redis) before that happens. Tracked in TODO.md.

IP-address extraction: Cloud Run terminates the client connection at
Google's own load balancer, so request.client.host (what slowapi's
default get_remote_address() reads) is always Google's internal proxy
address -- identical for every request, which would make per-IP limiting
a no-op in production. The real client IP arrives in X-Forwarded-For
instead, so key functions here read that first.
"""

import sys

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.security import TokenError, decode_access_token
from app.config import get_settings


def real_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First entry is the original client; the rest are intermediate
        # proxies (Cloud Run's own LB may append its own hop after Google's).
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def user_id_or_ip(request: Request) -> str:
    """Per-account limiting for authenticated endpoints, so one account
    can't dodge its own limit by rotating IPs -- falls back to per-IP
    only if the request has no valid token (shouldn't happen behind
    get_current_user, but the limiter runs independently of that
    dependency, so this must not assume a valid token is present)."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            user_id = decode_access_token(token, get_settings())
            return f"user:{user_id}"
        except TokenError:
            pass
    return f"ip:{real_client_ip(request)}"


async def email_from_body(request: Request) -> str:
    """Keys forgot-password's second limit by the target email address, not
    the caller's IP -- an IP-only limit doesn't stop someone spamming one
    victim's inbox with reset emails from many different IPs/devices."""
    try:
        body = await request.json()
        email = str(body.get("email", "")).strip().lower()
    except Exception:  # noqa: BLE001 -- malformed body; group it under one bucket rather than failing the request here
        email = ""
    return f"email:{email or 'unknown'}"


# Enforcement is off under pytest, on everywhere else (including local dev
# and every real deployment) -- FastAPI's TestClient reports the same
# synthetic "testclient" host for every request, so without this the test
# suite's own back-to-back /auth/register calls would trip the real limit
# and fail on request count, not on what each test actually asserts.
#
# "pytest" in sys.modules (not the PYTEST_CURRENT_TEST env var -- that's
# only set once a specific test starts *running*, too late here: most
# test files do `from app.main import app` at module level, which
# executes during pytest's collection phase, before any test has started).
# pytest necessarily imports itself before it can discover or import any
# test file, so this is true for the whole run, checked at the same
# import time this module itself gets loaded.
limiter = Limiter(key_func=real_client_ip, enabled="pytest" not in sys.modules)
