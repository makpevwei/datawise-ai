"""The ONLY module in this codebase allowed to call the Google Drive and
Sheets *data* APIs (as opposed to app/integrations/oauth.py, which only
talks to Google's OAuth endpoints). This is the second, independent
read-only enforcement layer: layer one is the OAuth scope itself
(drive.readonly / spreadsheets.readonly -- a token minted from that consent
physically cannot authenticate a write call, enforced by Google before our
code is even involved). This module is layer two -- even with a
theoretically-broader token, this code simply never constructs a write
call. That claim is not just a comment: tests/test_google_client_read_only.py
parses this file's own AST and asserts none of the disallowed method names
below ever appear in it. Adding a write call here -- even by accident --
fails the build.

Allowed (read-only) methods only:
  Drive:  files().list, files().get, files().get_media, files().export
  Sheets: spreadsheets().get, spreadsheets().values().get

Never, under any circumstance, in this file:
  Drive:  files().create, files().update, files().delete, files().copy,
          files().emptyTrash, permissions().*
  Sheets: spreadsheets().batchUpdate, spreadsheets().values().update,
          spreadsheets().values().append, spreadsheets().values().clear,
          spreadsheets().values().batchUpdate, spreadsheets().create
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build


def _drive(creds: Credentials) -> Resource:
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sheets(creds: Credentials) -> Resource:
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def list_drive_files(creds: Credentials, page_token: str | None = None, page_size: int = 100) -> dict:
    """One page of the connected account's Drive files -- used to populate
    the file picker (GET /integrations/{id}/browse). Explicitly excludes
    trashed files and folders (folders aren't ingestible content)."""
    return (
        _drive(creds)
        .files()
        .list(
            q="trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            pageSize=page_size,
            pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
        )
        .execute()
    )


def get_drive_file_metadata(creds: Credentials, file_id: str) -> dict:
    """Just modifiedTime + mimeType -- the cheap call used to decide
    whether a ConnectedItem needs re-syncing at all, before paying for a
    full download/export."""
    return _drive(creds).files().get(fileId=file_id, fields="id, name, mimeType, modifiedTime, size").execute()


def export_drive_file(creds: Credentials, file_id: str, mime_type: str) -> bytes:
    """For Google-native files (Docs, Slides) which have no downloadable
    binary of their own -- exports a rendered copy in the requested format
    (e.g. 'application/pdf', 'text/plain'). Google enforces a 10MB cap on
    export; callers should catch and surface HttpError for oversized files
    rather than let it propagate as an unhandled 500."""
    return _drive(creds).files().export(fileId=file_id, mimeType=mime_type).execute()


def download_drive_file(creds: Credentials, file_id: str) -> bytes:
    """For ordinary files already sitting in Drive (an uploaded PDF, a
    .docx, etc.) that aren't Google-native and so have real bytes to
    download directly, rather than export."""
    return _drive(creds).files().get_media(fileId=file_id).execute()


def get_spreadsheet_metadata(creds: Credentials, spreadsheet_id: str) -> dict:
    """Sheet tab names within a spreadsheet -- needed before pulling values,
    since a spreadsheet can have multiple tabs and the caller needs to know
    what ranges exist."""
    return _sheets(creds).spreadsheets().get(spreadsheetId=spreadsheet_id, fields="properties, sheets.properties").execute()


def get_spreadsheet_values(creds: Credentials, spreadsheet_id: str, range_: str) -> dict:
    """The actual cell values for one sheet tab/range -- range_ is an A1
    notation range, e.g. 'Sheet1' for the whole tab."""
    return _sheets(creds).spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_).execute()
