"""External URL allowlisting for DOCX links and exported HTML anchors."""

import re


def is_safe_href(href: str) -> bool:
    """
    Return True if href is safe to emit in HTML (internal anchor, http(s), or mailto).
    Rejects javascript:, data:, vbscript:, file:, and unknown schemes.
    """
    if not href or not str(href).strip():
        return False
    value = str(href).strip()
    lower = value.lower()
    if lower.startswith("#"):
        return not lower.startswith("#x")  # legacy bad marker from Word
    if lower.startswith("mailto:"):
        return "@" in value[7:50]  # minimal sanity
    if lower.startswith("http://") or lower.startswith("https://"):
        return True
    return False


def sanitize_external_href(href: str) -> str:
    """Return href if safe; otherwise empty string (caller should not emit a link)."""
    return href.strip() if is_safe_href(href) else ""
