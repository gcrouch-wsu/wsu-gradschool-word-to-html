"""Request-parsing helpers shared by multiple route modules."""
from flask import request

from core.html_processor import parse_heading_id_map_json


def load_heading_id_map_from_request() -> tuple[dict, str]:
    """Parse signature-to-ID JSON from form or file."""
    raw_text = request.form.get("stable_heading_map_raw", "").strip()
    if not raw_text:
        f = request.files.get("stable_heading_map_file")
        if f and f.filename:
            raw_text = f.read().decode("utf-8", errors="ignore")

    return parse_heading_id_map_json(raw_text), raw_text
