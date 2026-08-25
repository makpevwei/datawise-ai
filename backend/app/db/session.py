"""Sync SQLAlchemy engine/session for DataWise's Postgres (Neon) database.

Sync, not async: the DataWise FastAPI app is overwhelmingly synchronous
(`def`, not `async def`, endpoints -- the two file-upload routes are
`async def` only because of `await file.read()`, not because the app has
an async database story), so a sync driver (psycopg) is the simpler,
correct fit rather than adding asyncpg for no reason.

Never logs, returns, or embeds DATABASE_URL (or any exception that might
contain it) anywhere -- see _connection_error_message().
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


class DatabaseNotConfiguredError(Exception):
    """Raised when DATABASE_URL is unset and a DB operation is attempted."""


def normalize_database_url(raw_url: str) -> str:
    """SQLAlchemy needs an explicit driver in the URL scheme. Neon (and most
    providers) hand out bare postgres:// / postgresql:// URLs, which
    SQLAlchemy would otherwise try to open with whatever PostgreSQL DBAPI
    happens to be installed -- pin it explicitly to psycopg (v3, sync).
    """
    if raw_url.startswith("postgresql+"):
        return raw_url
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://") :]
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    return raw_url


def connection_error_message() -> str:
    return (
        "Could not connect to the DataWise database. Check DATABASE_URL in "
        "the project's .env and that the Neon database is reachable."
    )


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set in .env -- DataWise's database features are unavailable."
        )
    url = normalize_database_url(settings.database_url)
    # pool_pre_ping guards against Neon's autosuspend/idle-connection resets.
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a Session, always closes it afterward."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_db_connection() -> bool:
    """Runs SELECT 1. Returns True/False; never raises, never leaks the DSN."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except DatabaseNotConfiguredError:
        return False
    except Exception:  # noqa: BLE001 -- deliberately broad: any failure here
        # must degrade to False, never propagate a driver exception that
        # could contain the DSN.
        return False
