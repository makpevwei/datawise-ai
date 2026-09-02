"""Google Drive/Sheets connector: OAuth connect/callback/disconnect, browsing
a connected account's files, registering ConnectedItems, and syncing them.

Deliberately thin: every actual Google API call goes through
app/integrations/google_client.py (the read-only-enforced module) or
app/integrations/oauth.py (token lifecycle only); this file just wires
those into the same auth/ownership/rate-limit conventions every other
router here already uses.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession
from starlette.responses import RedirectResponse

from app.api.deps import get_dataset_store, get_document_store
from app.api.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.auth.security import TokenError, create_oauth_state_token, decode_oauth_state_token
from app.config import get_settings
from app.db.models import ConnectedItem, Integration, User
from app.db.session import get_db
from app.documents.store import DocumentStore
from app.integrations import google_client, oauth
from app.integrations.crypto import (
    TokenDecryptionError,
    TokenEncryptionNotConfiguredError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)
from app.integrations.oauth import GoogleOAuthNotConfiguredError
from app.integrations.service import sync_connected_item
from app.semantic.store import DatasetStore

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationSummary(BaseModel):
    id: str
    provider: str
    status: str
    scopes_granted: str
    connected_at: datetime
    last_synced_at: datetime | None
    item_count: int

    model_config = ConfigDict(from_attributes=True)


class ConnectedItemSummary(BaseModel):
    id: str
    external_id: str
    external_kind: str
    display_name: str
    sync_status: str
    last_synced_at: datetime | None
    last_error: str | None
    dataset_id: str | None
    document_id: str | None

    model_config = ConfigDict(from_attributes=True)


class ConnectUrlResponse(BaseModel):
    authorization_url: str


class BrowseFile(BaseModel):
    id: str
    name: str
    mime_type: str
    modified_time: str
    external_kind: str  # "sheet" | "drive_file", derived from mime_type


class BrowseResponse(BaseModel):
    files: list[BrowseFile]
    next_page_token: str | None


class SelectItemsRequest(BaseModel):
    items: list[BrowseFile]


_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def _get_owned_integration(db: DBSession, integration_id: str, user: User) -> Integration:
    row = db.get(Integration, integration_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail=f"Integration '{integration_id}' not found.")
    return row


def _item_count(db: DBSession, integration_id: str) -> int:
    return db.query(ConnectedItem).filter(ConnectedItem.integration_id == integration_id).count()


@router.get("", response_model=list[IntegrationSummary])
def list_integrations(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[IntegrationSummary]:
    rows = db.query(Integration).filter(Integration.user_id == user.id).order_by(Integration.connected_at.desc()).all()
    return [
        IntegrationSummary(
            id=r.id,
            provider=r.provider,
            status=r.status,
            scopes_granted=r.scopes_granted,
            connected_at=r.connected_at,
            last_synced_at=r.last_synced_at,
            item_count=_item_count(db, r.id),
        )
        for r in rows
    ]


@router.post("/google/connect", response_model=ConnectUrlResponse)
def start_google_connect(user: User = Depends(get_current_user)) -> ConnectUrlResponse:
    """Returns the Google consent-screen URL for the frontend to redirect
    the browser to. The `state` param round-trips through Google unmodified
    and is how /google/callback below learns which user this is for."""
    settings = get_settings()
    state = create_oauth_state_token(user.id, settings)
    try:
        url = oauth.build_authorization_url(state, settings)
    except GoogleOAuthNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ConnectUrlResponse(authorization_url=url)


@router.get("/google/callback")
@limiter.limit("20/minute")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: DBSession = Depends(get_db)) -> RedirectResponse:
    """OAuth redirect target -- unauthenticated (Google's redirect is a
    plain browser navigation, no Authorization header), rate-limited by IP
    instead, and identifies the user solely via the signed `state` JWT
    (see create_oauth_state_token). Never raises an HTTPException back to
    the browser -- always redirects to the frontend, success or failure,
    since a raw JSON 4xx is a dead end for a browser-navigation flow."""
    settings = get_settings()
    frontend_base = settings.frontend_base_url or settings.cors_origins[0]
    redirect_base = f"{frontend_base}/settings?tab=integrations"

    if error or not code or not state:
        return RedirectResponse(f"{redirect_base}&connect_error=denied")

    try:
        user_id = decode_oauth_state_token(state, settings)
    except TokenError:
        return RedirectResponse(f"{redirect_base}&connect_error=invalid_state")

    try:
        creds = oauth.exchange_code_for_tokens(code, settings)
    except GoogleOAuthNotConfiguredError:
        return RedirectResponse(f"{redirect_base}&connect_error=not_configured")
    except Exception:  # noqa: BLE001 -- any Google-side failure here becomes one honest redirect outcome, not a 500
        return RedirectResponse(f"{redirect_base}&connect_error=google_error")

    if not creds.refresh_token:
        # Shouldn't happen given access_type=offline&prompt=consent, but if
        # Google ever omits it there is nothing useful to store -- a
        # refresh-token-less connection can't sync anything later.
        return RedirectResponse(f"{redirect_base}&connect_error=no_refresh_token")

    try:
        encrypted = encrypt_refresh_token(creds.refresh_token, settings)
    except TokenEncryptionNotConfiguredError:
        return RedirectResponse(f"{redirect_base}&connect_error=not_configured")

    integration = Integration(
        user_id=user_id,
        provider="google",
        status="connected",
        scopes_granted=" ".join(creds.scopes or oauth.SCOPES),
        encrypted_refresh_token=encrypted,
    )
    db.add(integration)
    db.commit()
    return RedirectResponse(f"{redirect_base}&connected=google")


@router.get("/{integration_id}/browse", response_model=BrowseResponse)
def browse_integration(integration_id: str, page_token: str | None = None, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> BrowseResponse:
    """Lists the connected account's Drive files (Sheets included -- Sheets
    are Drive files under the hood) for the frontend's file picker."""
    integration = _get_owned_integration(db, integration_id, user)
    settings = get_settings()
    try:
        refresh_token = decrypt_refresh_token(integration.encrypted_refresh_token, settings)
        creds = oauth.refresh_access_token(refresh_token, settings)
        page = google_client.list_drive_files(creds, page_token=page_token)
    except (TokenDecryptionError, TokenEncryptionNotConfiguredError, GoogleOAuthNotConfiguredError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to list Drive files: {exc}") from exc

    files = [
        BrowseFile(
            id=f["id"],
            name=f["name"],
            mime_type=f["mimeType"],
            modified_time=f["modifiedTime"],
            external_kind="sheet" if f["mimeType"] == _SHEET_MIME_TYPE else "drive_file",
        )
        for f in page.get("files", [])
    ]
    return BrowseResponse(files=files, next_page_token=page.get("nextPageToken"))


@router.get("/{integration_id}/items", response_model=list[ConnectedItemSummary])
def list_items(integration_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[ConnectedItemSummary]:
    """The items already selected on this integration and their sync
    status -- the "what's connected" view (distinct from /browse, which
    lists everything available to select). Needed so the frontend can show
    this on page load, not only right after a select/sync call."""
    integration = _get_owned_integration(db, integration_id, user)
    items = db.query(ConnectedItem).filter(ConnectedItem.integration_id == integration.id).all()
    return [ConnectedItemSummary.model_validate(i) for i in items]


@router.post("/{integration_id}/items", response_model=list[ConnectedItemSummary])
def select_items(integration_id: str, body: SelectItemsRequest, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[ConnectedItemSummary]:
    """Registers the files/sheets the user picked in the browser as
    ConnectedItem rows (sync_status="pending") -- syncing them is a
    separate step (POST /{id}/sync), so selecting is instant and doesn't
    block on downloading anything."""
    integration = _get_owned_integration(db, integration_id, user)
    existing_ids = {
        row.external_id
        for row in db.query(ConnectedItem.external_id).filter(ConnectedItem.integration_id == integration.id)
    }
    created = []
    for f in body.items:
        if f.id in existing_ids:
            continue
        item = ConnectedItem(
            integration_id=integration.id,
            user_id=user.id,
            external_id=f.id,
            external_kind=f.external_kind,
            display_name=f.name,
            external_modified_at=datetime.fromisoformat(f.modified_time).replace(tzinfo=None),
            sync_status="pending",
        )
        db.add(item)
        created.append(item)
    db.commit()
    for item in created:
        db.refresh(item)

    all_items = db.query(ConnectedItem).filter(ConnectedItem.integration_id == integration.id).all()
    return [ConnectedItemSummary.model_validate(i) for i in all_items]


@router.post("/{integration_id}/sync", response_model=list[ConnectedItemSummary])
def sync_integration(
    integration_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dataset_store: DatasetStore = Depends(get_dataset_store),
    document_store: DocumentStore = Depends(get_document_store),
) -> list[ConnectedItemSummary]:
    """Syncs every item on this integration that isn't already up to date.
    One bad item's failure never blocks the rest -- see
    app/integrations/service.py's own docstring. Uses the plain (unscoped)
    stores, same as the upload endpoint does: a freshly-synced dataset/
    document has no ownership conflict to resolve against, since its
    Dataset/Document row is created here with user_id=user.id directly."""
    integration = _get_owned_integration(db, integration_id, user)
    settings = get_settings()
    items = db.query(ConnectedItem).filter(ConnectedItem.integration_id == integration.id).all()
    for item in items:
        sync_connected_item(item, integration, db, dataset_store, document_store, settings)
    integration.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    items = db.query(ConnectedItem).filter(ConnectedItem.integration_id == integration.id).all()
    return [ConnectedItemSummary.model_validate(i) for i in items]


@router.delete("/{integration_id}")
def disconnect_integration(integration_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, str]:
    """Revokes the token with Google (best-effort) and deletes the local
    Integration/ConnectedItem rows -- a real revocation, not a soft flag.
    Previously-synced Dataset/Document rows are left as-is, same as
    deleting an uploaded file already works: this stops future syncs, it
    doesn't retroactively delete data already pulled in."""
    integration = _get_owned_integration(db, integration_id, user)
    settings = get_settings()
    try:
        refresh_token = decrypt_refresh_token(integration.encrypted_refresh_token, settings)
        oauth.revoke_refresh_token(refresh_token)
    except (TokenDecryptionError, TokenEncryptionNotConfiguredError):
        pass  # nothing we can decrypt to revoke; still remove the local rows below
    db.delete(integration)
    db.commit()
    return {"status": "disconnected"}
