"""Request-parsing helpers shared by multiple route modules."""
import time
from pathlib import Path

from flask import request

from config import SESSION_TTL_HOURS, SessionDir
from core.html_processor import parse_heading_id_map_json


def load_heading_id_map_from_request() -> tuple[dict, str]:
    """Parse signature-to-ID JSON from form or file."""
    raw_text = request.form.get("stable_heading_map_raw", "").strip()
    if not raw_text:
        f = request.files.get("stable_heading_map_file")
        if f and f.filename:
            raw_text = f.read().decode("utf-8", errors="ignore")

    return parse_heading_id_map_json(raw_text), raw_text


def session_retention_context(session: SessionDir) -> dict:
    """UI copy for how long a converter session is kept before prune."""
    if SESSION_TTL_HOURS <= 0:
        return {
            "session_ttl_hours": 0,
            "session_retention_note": (
                "Session auto-delete is off on this server. Still export a "
                "session bundle if you need to keep or hand off this work."
            ),
        }
    try:
        mtime = session.root.stat().st_mtime
    except OSError:
        mtime = time.time()
    hours_left = max(0, int((mtime + SESSION_TTL_HOURS * 3600 - time.time()) / 3600))
    return {
        "session_ttl_hours": SESSION_TTL_HOURS,
        "session_hours_left": hours_left,
        "session_retention_note": (
            f"This work session is kept about {SESSION_TTL_HOURS} hours from last "
            f"activity (roughly {hours_left} hour(s) left). Export a session bundle "
            "to keep or continue on another machine."
        ),
    }


def first_manual_table_html(html_path: Path | str | None) -> str | None:
    """Return a .manual-wrapped first <table> from converted HTML, if any."""
    if not html_path:
        return None
    path = Path(html_path)
    if not path.exists():
        return None
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            path.read_text(encoding="utf-8", errors="ignore"), "html.parser"
        )
        tbl = soup.find("table")
        if tbl is None:
            return None
        return f'<div class="manual">{tbl}</div>'
    except Exception:
        return None
