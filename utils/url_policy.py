"""External URL allowlisting for DOCX links and exported HTML anchors.

Two layers, deliberately separate:

* ``is_safe_href`` / ``sanitize_external_href`` are the strict output gate. They
  never rewrite a value — anything not already an internal anchor, http(s), or
  mailto is refused. Everything written into exported HTML passes through here.
* ``normalize_external_href`` is the *input* helper used where a human types a
  URL. Operators paste "policies.wsu.edu/bppm-10-65" without a scheme, which the
  output gate correctly refuses; silently discarding it meant the link simply
  never appeared. Normalizing at the point of entry fixes the common case while
  leaving the output gate exactly as strict.
"""
import re

# A bare host with no scheme: labels separated by dots, an alphabetic TLD, an
# optional port, and an optional path/query/fragment with no whitespace.
# Deliberately narrow — "42.52.040" and "Section 6.0" must not be mistaken for
# hostnames, and no value carrying a scheme we do not allow may match.
_BARE_HOST_RE = re.compile(
    r'^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}'
    r'(?::\d{1,5})?'
    r'(?:[/?#]\S*)?$'
)


def normalize_external_href(href: str) -> str:
    """Coerce operator input into a safe absolute URL, or '' if it cannot be.

    Accepts what ``is_safe_href`` accepts, plus scheme-less hosts
    ("policies.wsu.edu/x", "www.wsu.edu") and protocol-relative URLs, which are
    promoted to https. Never rewrites a value that already carries a scheme, so
    "javascript:alert(1)" is refused rather than turned into a URL.
    """
    value = str(href or "").strip()
    if not value:
        return ""
    if is_safe_href(value):
        return value
    if value.startswith("//"):
        candidate = f"https:{value}"
        return candidate if is_safe_href(candidate) else ""
    if _BARE_HOST_RE.match(value):
        candidate = f"https://{value}"
        return candidate if is_safe_href(candidate) else ""
    return ""


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
