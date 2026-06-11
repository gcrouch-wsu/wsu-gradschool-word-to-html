"""Tier-1 authentication: env-configured accounts, signed-cookie sessions.

No database. Accounts come from environment variables:

  AUTH_OWNER_EMAIL / AUTH_OWNER_PASSWORD
      A single convenience account; the plaintext password is hashed at load.
  AUTH_USERS
      Optional additional accounts as a comma/newline-separated list of
      "email:password_hash" entries (hashes from scripts/make_password_hash.py).

Auth is **enabled only when at least one account is configured.** With no
accounts the app runs open (current local-dev behavior) and these helpers are
no-ops, so the existing test suite is unaffected.

Sessions ride Flask's own signed cookie (keyed by FLASK_SECRET_KEY) via
Flask-Login. Resource ownership for converter sessions is enforced separately
via the `owner` field written into each session.json (see current_uid /
session_owner_ok).
"""
import logging
import os

from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

login_manager = LoginManager()
login_manager.login_view = "login"

# {email_lower: werkzeug_password_hash}
_USERS: dict[str, str] = {}


class User(UserMixin):
    """A logged-in account. The email (lowercased) is the stable id."""

    def __init__(self, email: str):
        self.id = email


def load_users_from_env() -> dict[str, str]:
    """Build the account table from the environment. Idempotent; call to refresh."""
    users: dict[str, str] = {}

    email = os.environ.get("AUTH_OWNER_EMAIL", "").strip().lower()
    password = os.environ.get("AUTH_OWNER_PASSWORD", "")
    if email and password:
        users[email] = generate_password_hash(password)

    raw = os.environ.get("AUTH_USERS", "")
    for entry in raw.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        e, h = entry.split(":", 1)
        e, h = e.strip().lower(), h.strip()
        if e and h:
            users[e] = h  # already a hash

    return users


def configure_users(users: dict[str, str] | None = None) -> None:
    """Replace the in-memory account table (from env by default).

    Tests call this with an explicit map to toggle auth on/off without touching
    the process environment.
    """
    global _USERS
    _USERS = dict(users) if users is not None else load_users_from_env()
    if _USERS:
        logger.info("Authentication enabled: %d account(s) configured.", len(_USERS))
    else:
        logger.warning(
            "Authentication is DISABLED (no AUTH_OWNER_* / AUTH_USERS configured). "
            "The app is open to anyone who can reach it."
        )


# Populate from the environment at import.
configure_users()


def auth_enabled() -> bool:
    return bool(_USERS)


def verify_credentials(email: str, password: str) -> User | None:
    """Return a User for valid credentials, else None (constant-time on the hash)."""
    email = (email or "").strip().lower()
    stored = _USERS.get(email)
    if not stored:
        return None
    try:
        ok = check_password_hash(stored, password or "")
    except Exception:
        return None
    return User(email) if ok else None


@login_manager.user_loader
def _load_user(user_id: str):
    if user_id and user_id.strip().lower() in _USERS:
        return User(user_id.strip().lower())
    return None


def current_uid() -> str | None:
    """The current account id when auth is on and a user is signed in, else None."""
    if auth_enabled() and current_user.is_authenticated:
        return current_user.get_id()
    return None


def session_owner_ok(session_data: dict) -> bool:
    """True if the current request may access this converter session.

    Open when auth is disabled. When enabled, a session is accessible if it has
    no recorded owner (created before auth, or by a tool path) or its owner
    matches the signed-in user. This is the per-session isolation check.
    """
    if not auth_enabled():
        return True
    owner = (session_data or {}).get("owner")
    return owner is None or owner == current_uid()
