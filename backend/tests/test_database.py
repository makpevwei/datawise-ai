"""Database Foundation: confirms DATABASE_URL loads, the real Neon Postgres
connection works, and a session can be initialized -- against the actual
configured database, never mocked. Never prints DATABASE_URL or any
value derived from it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import check_db_connection, get_db, get_engine, normalize_database_url


def test_database_url_loads_from_env():
    settings = get_settings()
    assert settings.database_url, "DATABASE_URL must be set in DataWise-AI/.env for this test to run."


def test_normalize_database_url_pins_psycopg_driver():
    assert normalize_database_url("postgres://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert normalize_database_url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert normalize_database_url("postgresql+psycopg://u:p@host/db") == "postgresql+psycopg://u:p@host/db"


@pytest.mark.skipif(not get_settings().database_url, reason="DATABASE_URL not configured")
def test_real_postgres_connection_succeeds():
    assert check_db_connection() is True


@pytest.mark.skipif(not get_settings().database_url, reason="DATABASE_URL not configured")
def test_select_1_succeeds_against_real_database():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.skipif(not get_settings().database_url, reason="DATABASE_URL not configured")
def test_application_can_initialize_a_database_session():
    session_gen = get_db()
    session = next(session_gen)
    try:
        assert isinstance(session, Session)
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        session_gen.close()  # runs the generator's finally: -> session.close()
