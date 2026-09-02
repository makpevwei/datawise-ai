"""Enforces that app/integrations/google_client.py -- the only module
allowed to call the actual Drive/Sheets data APIs -- never calls a write
endpoint, by parsing its own source as an AST rather than trusting a
comment. This is the second, independent read-only layer described in that
module's docstring: layer one is the OAuth scope (drive.readonly /
spreadsheets.readonly) rejecting a write call at the protocol level before
our code is even involved; this test is layer two, catching a write call
that would otherwise merely fail loudly in production the first time
someone tried it (or worse, silently succeed if the scope were ever
accidentally broadened).

Deliberately does NOT import googleapiclient stubs or mock a live API --
this only needs to prove *what method names this file's source calls*,
which is exactly what an AST walk answers without any network dependency.
"""

import ast
from pathlib import Path

GOOGLE_CLIENT_PATH = Path(__file__).resolve().parents[1] / "app" / "integrations" / "google_client.py"

# Every Drive/Sheets API method name that mutates data in any way. If any of
# these ever appears as a method call anywhere in google_client.py, this
# test fails the build -- see that module's docstring for the full,
# maintained list this mirrors.
DISALLOWED_METHOD_NAMES = {
    # Drive
    "create",
    "update",
    "delete",
    "copy",
    "emptyTrash",
    "trash",
    "untrash",
    "modifyLabels",
    "generateIds",
    "watch",
    # Drive permissions/comments/replies -- also mutating, also disallowed
    # even though this module has no legitimate reason to touch them at all
    "insert",
    # Sheets
    "batchUpdate",
    "append",
    "clear",
    "batchClear",
    "batchClearByDataFilter",
    "batchUpdateByDataFilter",
    "batchGetByDataFilter",  # not a write, but not in this module's documented allow-list either
}

ALLOWED_METHOD_NAMES = {
    "files",
    "list",
    "get",
    "get_media",
    "export",
    "spreadsheets",
    "values",
    "execute",
}


def _method_call_names(tree: ast.Module) -> set[str]:
    """Every method name called anywhere in the module, e.g. the `list` in
    `.files().list(...)`."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def test_google_client_source_exists():
    assert GOOGLE_CLIENT_PATH.exists(), f"expected {GOOGLE_CLIENT_PATH} to exist"


def test_google_client_never_calls_a_disallowed_write_method():
    tree = ast.parse(GOOGLE_CLIENT_PATH.read_text(encoding="utf-8"))
    called = _method_call_names(tree)
    disallowed_calls_found = called & DISALLOWED_METHOD_NAMES
    assert not disallowed_calls_found, (
        f"google_client.py calls disallowed (write) Drive/Sheets method(s): {sorted(disallowed_calls_found)}. "
        "This module must never construct a request to a Google API endpoint that creates, updates, "
        "deletes, or otherwise mutates Drive/Sheets data -- see the module's own docstring."
    )


def test_google_client_only_calls_the_documented_allow_list():
    """Stricter than the disallow-list check above: every method call in
    the file must be one of the explicitly documented read-only Drive/
    Sheets methods (or a plain Python builtin/helper) -- catches a *new*,
    not-yet-blocklisted write method being added before it's ever added to
    DISALLOWED_METHOD_NAMES above."""
    tree = ast.parse(GOOGLE_CLIENT_PATH.read_text(encoding="utf-8"))
    called = _method_call_names(tree)
    # encode/decode etc. are plain str/bytes builtins used incidentally,
    # not Google API calls -- excluded from the allow-list check since this
    # test is specifically about the Google API surface, not every method
    # call in the file.
    non_google_builtins = {"read_text", "resolve", "parents"}
    unexpected = called - ALLOWED_METHOD_NAMES - non_google_builtins
    assert not unexpected, (
        f"google_client.py calls method(s) not in its documented read-only allow-list: {sorted(unexpected)}. "
        "If this is a genuine new read-only method, add it to ALLOWED_METHOD_NAMES here AND to the "
        "module's own docstring; if it's a write method, it must not be added at all."
    )
