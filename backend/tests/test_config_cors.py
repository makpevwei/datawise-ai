"""Regression tests for CORS_ORIGINS parsing in app.config.Settings.

Guards the production-outage bug where a plain-string CORS_ORIGINS env var
(the obvious thing to type into Render's env-var UI) raised a SettingsError
at import time -- get_settings() runs at module top level in app.main, so
that error crashed the backend on startup: uvicorn never bound, the health
check failed, the deploy was marked failed, and the frontend (which needs
this API for every page) was left unable to open.

Settings is constructed directly with a per-case `_env_file=None` so these
tests read only the monkeypatched env var, never a real .env on disk.
"""

import pytest

from app.config import Settings


def _settings(monkeypatch, raw: str | None) -> Settings:
    if raw is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", raw)
    # _env_file=None: ignore any .env so the env var is the only source.
    return Settings(_env_file=None)


def test_default_when_unset(monkeypatch):
    assert _settings(monkeypatch, None).cors_origins == ["http://localhost:3000"]


def test_plain_single_origin(monkeypatch):
    # The value that used to crash startup.
    assert _settings(monkeypatch, "https://datawise.vercel.app").cors_origins == [
        "https://datawise.vercel.app"
    ]


def test_plain_comma_separated(monkeypatch):
    s = _settings(monkeypatch, "https://datawise.vercel.app, https://www.datawise.app")
    assert s.cors_origins == ["https://datawise.vercel.app", "https://www.datawise.app"]


def test_json_array_back_compat(monkeypatch):
    # The form .env.example documents must keep working.
    s = _settings(monkeypatch, '["https://a.example.com","https://b.example.com"]')
    assert s.cors_origins == ["https://a.example.com", "https://b.example.com"]


def test_empty_string_is_no_origins_not_a_crash(monkeypatch):
    assert _settings(monkeypatch, "").cors_origins == []


def test_malformed_json_array_still_fails_loudly(monkeypatch):
    # A value that opens like a JSON array but is broken should error,
    # not be silently misread as one giant origin string.
    with pytest.raises(Exception):  # noqa: B017 -- json/validation error either way
        _settings(monkeypatch, '["https://a",')
