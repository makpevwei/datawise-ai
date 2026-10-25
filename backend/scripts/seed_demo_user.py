"""Idempotently provision the demo account the login page advertises.

The login screen (frontend/src/app/login/page.tsx) shows a "Demo Access"
box with demo@datawise.ai / datawise2026 so evaluators can sign in without
registering. Nothing in the codebase ever created that account, though --
so every demo sign-in hit /auth/login, found no such user, and came back
401 "Incorrect email or password". This script closes that gap.

Idempotent by design so it's safe to run on every deploy:
  - no demo user yet            -> create it
  - demo user exists, wrong/old -> reset its password + reactivate
  - demo user exists, correct   -> no-op (hash compare short-circuits)

Env overrides (all optional):
  DEMO_USER_EMAIL     (default: demo@datawise.ai)
  DEMO_USER_PASSWORD  (default: datawise2026)
  DEMO_USER_NAME      (default: Demo User)
  SEED_DEMO_USER=0    -> skip entirely (opt out without editing the deploy
                         command), so a real production instance can leave
                         the public demo account disabled.

Exits 0 on success AND on expected "can't run" conditions (DB not
configured / unreachable), so wiring it into the deploy start command with
`&&` never blocks the app from booting over a seed hiccup -- the worst case
is the demo login still 401s, exactly today's behavior, not an outage.
"""

import os
import sys
from pathlib import Path

# Make "app" importable when run as `python scripts/seed_demo_user.py` from
# backend/ (its normal working directory, matching every other entry point).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password, verify_password  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import (  # noqa: E402
    DatabaseNotConfiguredError,
    get_session_factory,
)

DEFAULT_EMAIL = "demo@datawise.ai"
DEFAULT_PASSWORD = "datawise2026"  # noqa: S105 -- intentionally public demo credential, shown on the login page
DEFAULT_NAME = "Demo User"


def _truthy(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def seed_demo_user() -> int:
    if not _truthy(os.getenv("SEED_DEMO_USER"), default=True):
        print("[seed-demo-user] SEED_DEMO_USER is disabled; skipping.")
        return 0

    email = os.getenv("DEMO_USER_EMAIL", DEFAULT_EMAIL).strip().lower()
    password = os.getenv("DEMO_USER_PASSWORD", DEFAULT_PASSWORD)
    full_name = os.getenv("DEMO_USER_NAME", DEFAULT_NAME).strip()

    try:
        session = get_session_factory()()
    except DatabaseNotConfiguredError:
        # No DATABASE_URL -- the app itself can't do user features either,
        # so this isn't a seed-specific failure. Don't block the deploy.
        print("[seed-demo-user] DATABASE_URL not configured; skipping (not fatal).")
        return 0
    except Exception as exc:  # noqa: BLE001 -- never let a DB hiccup abort the deploy's start command
        print(f"[seed-demo-user] could not open a DB session ({type(exc).__name__}); skipping (not fatal).")
        return 0

    try:
        user = session.query(User).filter(User.email == email).first()

        if user is None:
            session.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name or DEFAULT_NAME,
                )
            )
            session.commit()
            print(f"[seed-demo-user] created demo account {email}.")
            return 0

        # Already there -- make sure it still logs in with the advertised
        # password and is active, repairing drift (e.g. an earlier run that
        # used a different password, or a deactivated account).
        changed = False
        if not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True

        if changed:
            session.commit()
            print(f"[seed-demo-user] demo account {email} already existed; reset password / reactivated.")
        else:
            print(f"[seed-demo-user] demo account {email} already present and correct; nothing to do.")
        return 0
    except Exception as exc:  # noqa: BLE001 -- see module docstring: expected-failure tolerance
        session.rollback()
        print(f"[seed-demo-user] seeding failed ({type(exc).__name__}: {exc}); skipping (not fatal).")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(seed_demo_user())
