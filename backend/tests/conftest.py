"""Shared auth test fixtures.

Every endpoint that touches user-owned data now requires a logged-in user
(app.auth.dependencies.get_current_user). Existing tests built their own
TestClient with dependency_overrides for the dataset/document/LLM stores;
`fake_user` + `auth_override` let them add "and there's a logged-in user"
with one line, without a real HTTP register/login round trip per test.

`fake_user` creates a real row in the configured DataWise Postgres
database (not a mock) -- this project's convention (see test_database.py)
is to test against the real dev DB rather than mock it out. Cleanup
relies on the ON DELETE CASCADE set on every user-owned table, so deleting
the user also removes any datasets/documents/sessions/messages/reports
the test created.
"""

import uuid

import pytest

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_session_factory


@pytest.fixture
def fake_user():
    session = get_session_factory()()
    user = User(
        email=f"test-{uuid.uuid4().hex}@example.com",
        password_hash="not-a-real-hash",
        full_name="Test User",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    yield user
    session.delete(user)
    session.commit()
    session.close()


@pytest.fixture
def auth_override(fake_user):
    """Apply to an app's dependency_overrides to satisfy get_current_user
    without a real bearer token: `app.dependency_overrides[get_current_user] = auth_override`.
    Returns the override callable; the user it resolves to is `fake_user`."""

    def _override():
        return fake_user

    return _override
