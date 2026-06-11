"""Flask application object, configuration, and lifecycle hooks.

Routes live in the `routes/` package (registered by importing it); reusable
non-HTTP logic lives in `services/` and `core/`. The Gunicorn/CLI entry point
remains `word_to_wordpressV4:app`.
"""
import logging
import os
import shutil
import time

from flask import Flask, flash, redirect, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge

from auth import login_manager, auth_enabled

from config import (
    LOG_LEVEL,
    FLASK_SECRET_KEY,
    PERSIST_DIR,
    SESSION_TTL_HOURS,
    PANDOC_PINNED_VERSION,
    PANDOC_UPDATE_CHECK_ENABLED,
    PANDOC_UPDATE_CHECK_TTL_HOURS,
    PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS,
    PANDOC_UPDATE_CACHE_PATH,
)
from core.pandoc_wrapper import (
    get_pandoc_version,
    check_min_version,
    check_for_pandoc_update,
)

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
# Non-file form fields (pasted heading maps, table edits) are small; only file
# uploads need the large MAX_CONTENT_LENGTH above.
app.config["MAX_FORM_MEMORY_SIZE"] = 16 * 1024 * 1024
app.config["MAX_FORM_PARTS"] = 20000
app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)

# Session-cookie hardening. Secure-only when deployed (Railway terminates TLS);
# left off locally so http://127.0.0.1 dev still works.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("PORT"))

csrf = CSRFProtect(app)
login_manager.init_app(app)

# Endpoints reachable without a session (probe, the login flow, static assets).
_PUBLIC_ENDPOINTS = {"healthz", "login", "logout", "static"}


@app.before_request
def _require_login():
    """Global auth gate. No-op when auth is disabled (no accounts configured)."""
    if not auth_enabled():
        return
    if request.endpoint in _PUBLIC_ENDPOINTS or request.endpoint is None:
        return
    if not current_user.is_authenticated:
        return redirect(url_for("login", next=request.full_path))


_last_prune_ts = 0.0


def _prune_stale_sessions_if_due() -> None:
    """Remove session directories older than SESSION_TTL_HOURS (throttled)."""
    global _last_prune_ts
    if SESSION_TTL_HOURS <= 0:
        return
    now = time.time()
    if now - _last_prune_ts < 1800:
        return
    _last_prune_ts = now
    cutoff = now - SESSION_TTL_HOURS * 3600
    try:
        for child in list(PERSIST_DIR.iterdir()):
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        logger.exception("Session prune scan failed")


@app.before_request
def _run_session_prune_before_request():
    try:
        _prune_stale_sessions_if_due()
    except Exception:
        logger.exception("Session prune hook failed")


# One-shot guard for the Pandoc version/update check. Under Gunicorn the
# `if __name__ == "__main__"` block never runs, so the checks fire lazily on
# the first request per worker. Under local `python word_to_wordpressV4.py`
# the __main__ block runs them eagerly and calls mark_pandoc_checks_done() so
# the hook below is a no-op on the first request.
_pandoc_startup_checks_done = False


def mark_pandoc_checks_done() -> None:
    global _pandoc_startup_checks_done
    _pandoc_startup_checks_done = True


@app.before_request
def _run_pandoc_startup_checks_before_request():
    if _pandoc_startup_checks_done:
        return
    # Mark done in `finally` so one attempt per worker is guaranteed even if
    # the check raises — no silent retry loop if the inner try/except is ever
    # tightened or removed.
    try:
        run_startup_pandoc_checks()
    except Exception:
        logger.exception("Pandoc startup check failed")
    finally:
        mark_pandoc_checks_done()


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(error):
    flash("Request too large. Use a smaller file or increase the upload/form limits.")
    return redirect(url_for("index"))


def run_startup_pandoc_checks() -> None:
    """
    Verify Pandoc is present, log its version, warn if older than the pinned
    version, and (optionally) notify the operator when a newer upstream
    release is available. Never auto-upgrades. Never blocks on the network.
    """
    installed = get_pandoc_version()
    if not installed:
        logger.error(
            "Pandoc is not installed or not on PATH. "
            "Install from https://pandoc.org/installing.html"
        )
        raise RuntimeError("Pandoc not found on PATH")

    logger.info(f"Pandoc: installed version {installed} (pinned {PANDOC_PINNED_VERSION})")

    if not check_min_version(installed, PANDOC_PINNED_VERSION):
        logger.warning(
            "Pandoc %s is older than the pinned version %s. "
            "The app will still run, but consider upgrading: "
            "https://github.com/jgm/pandoc/releases/tag/%s",
            installed, PANDOC_PINNED_VERSION, PANDOC_PINNED_VERSION,
        )

    if not PANDOC_UPDATE_CHECK_ENABLED:
        return

    ttl_seconds = max(0, PANDOC_UPDATE_CHECK_TTL_HOURS) * 3600
    newer = check_for_pandoc_update(
        installed=installed,
        cache_path=PANDOC_UPDATE_CACHE_PATH,
        ttl_seconds=ttl_seconds,
        timeout_seconds=PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS,
    )
    if newer:
        # Informational only — operators upgrade deliberately (bump pin in
        # config.py + Dockerfile). Keep at INFO so the message does not look
        # like an alert in production log aggregators; pin mismatches above
        # remain at WARNING.
        logger.info(
            "Pandoc update available: %s is out. You are running %s. "
            "Review release notes at https://github.com/jgm/pandoc/releases/tag/%s "
            "before upgrading. (Set PANDOC_UPDATE_CHECK_ENABLED=0 to silence.)",
            newer, installed, newer,
        )
