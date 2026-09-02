"""Google OAuth token lifecycle: authorization URL, code exchange, refresh,
revoke. Deliberately separate from app/integrations/google_client.py, which
is the ONLY module allowed to call the actual Drive/Sheets data APIs -- this
file only ever talks to Google's *OAuth* endpoints (accounts.google.com,
oauth2.googleapis.com), never a Drive/Sheets data endpoint, so it stays out
of scope for that module's read-only enforcement test.
"""

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings

# Read-only, and only read-only -- see the plan/README for why these two
# specific scopes and no others (no userinfo/email scope, no drive.file,
# no spreadsheets write scope).
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class GoogleOAuthNotConfiguredError(Exception):
    """Raised when GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI are unset."""


def _client_config(settings: Settings) -> dict:
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret and settings.google_oauth_redirect_uri):
        raise GoogleOAuthNotConfiguredError(
            "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, "
            "and GOOGLE_OAUTH_REDIRECT_URI to enable the Drive/Sheets connector."
        )
    return {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_oauth_redirect_uri],
        }
    }


def build_authorization_url(state: str, settings: Settings) -> str:
    """state is the caller's signed OAuth-state JWT (see
    app/auth/security.py's create_oauth_state_token) -- passed through
    verbatim, Google returns it unmodified on the callback redirect."""
    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    # access_type=offline: request a refresh token, not just a short-lived
    # access token. prompt=consent: force the consent screen (and a fresh
    # refresh token) even on a repeat connect -- Google only issues a
    # refresh token on the *first* consent otherwise.
    authorization_url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    return authorization_url


def exchange_code_for_tokens(code: str, settings: Settings) -> Credentials:
    """Redeems the one-time authorization code Google sent back on the
    callback for a refresh token + short-lived access token. Never logs
    the code or the resulting tokens."""
    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    flow.fetch_token(code=code)
    return flow.credentials


def refresh_access_token(refresh_token: str, settings: Settings) -> Credentials:
    """Mints a fresh, short-lived access token from a stored (decrypted)
    refresh token -- called right before each sync; the access token itself
    is never persisted (see Integration model docstring)."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=SCOPES,
    )
    creds.refresh(GoogleAuthRequest())
    return creds


def revoke_refresh_token(refresh_token: str) -> None:
    """Best-effort: tells Google to invalidate this token server-side, on
    top of us deleting our own local copy -- a real revocation, not just a
    local soft-delete. If Google's revoke call fails (e.g. token already
    invalid), the local rows are still removed by the caller regardless;
    see app/api/integrations.py's disconnect endpoint."""
    requests.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": refresh_token},
        headers={"content-type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
