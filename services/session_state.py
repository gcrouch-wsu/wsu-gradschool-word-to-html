"""Session-state persistence helpers (session.json / edits.json).

Concurrency note: session files are read-modify-written with no locking. The
tool is built for a single operator working one session at a time; two browser
tabs editing the same session can clobber each other's last save. If that
assumption ever changes, add per-session file locking here (one chokepoint).
"""
import json
import logging

from config import SessionDir

logger = logging.getLogger(__name__)


def load_session_data(session: SessionDir) -> dict | None:
    """Return the parsed session.json, or None if the session does not exist."""
    session_file = session.session_json
    if not session_file.exists():
        return None
    return json.loads(session_file.read_text(encoding='utf-8'))


def save_session_data(session: SessionDir, session_data: dict) -> None:
    session.session_json.write_text(
        json.dumps(session_data, indent=2, default=str), encoding='utf-8'
    )


def load_edits_data(session: SessionDir) -> dict:
    """Return the parsed edits.json, or {} when missing/unreadable."""
    edit_file = session.edits_json
    if not edit_file.exists():
        return {}
    try:
        return json.loads(edit_file.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"Failed to load edits from {edit_file}: {e}")
        return {}


def save_edits_data(session: SessionDir, edit_data: dict) -> None:
    session.edits_json.write_text(json.dumps(edit_data, indent=2), encoding='utf-8')
