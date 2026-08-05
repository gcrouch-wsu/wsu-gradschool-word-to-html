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
import logging
import re

logger = logging.getLogger(__name__)

# A bare host with no scheme: labels separated by dots, an alphabetic TLD, an
# optional port, and an optional path/query/fragment with no whitespace.
# Deliberately narrow — "42.52.040" and "Section 6.0" must not be mistaken for
# hostnames, and no value carrying a scheme we do not allow may match.
_BARE_HOST_RE = re.compile(
    r'^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}'
    r'(?::\d{1,5})?'
    r'(?:[/?#]\S*)?$'
)


def _authority_is_plausible(url: str) -> bool:
    """Reject http(s) authorities that misrepresent where the link goes.

    ``https://facsen.wsu.edu@evil.example/manual`` reads as a WSU link but sends
    the browser to evil.example — everything before the ``@`` is userinfo. A
    non-ASCII host can do the same with look-alike characters. Neither has a
    legitimate use in a policy manual's citations, and the value here is typed by
    an operator who is very likely pasting something they were given.
    """
    rest = url.split("//", 1)[1] if "//" in url else url
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" in authority:
        return False
    return authority.isascii()


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
    lower = value.lower()
    if (lower.startswith("http://") or lower.startswith("https://")) \
            and not _authority_is_plausible(value):
        return ""
    if is_safe_href(value):
        return value
    if value.startswith("//"):
        candidate = f"https:{value}"
        return candidate if (is_safe_href(candidate) and _authority_is_plausible(candidate)) else ""
    if _BARE_HOST_RE.match(value):
        candidate = f"https://{value}"
        return candidate if (is_safe_href(candidate) and _authority_is_plausible(candidate)) else ""
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
    """Return href if safe to emit; otherwise empty string.

    The authority check runs here as well as on input. Guarding only operator
    input left already-stored values — from an older session, or an imported
    bundle someone else assembled — free to publish
    ``https://facsen.wsu.edu@evil.example/...``, which reads as a WSU link and is
    not one. This is the gate everything written into exported HTML passes.
    """
    value = str(href or "").strip()
    if not is_safe_href(value):
        return ""
    lower = value.lower()
    if (lower.startswith("http://") or lower.startswith("https://"))             and not _authority_is_plausible(value):
        logger.warning("Refusing to emit a link with a misleading authority: %r", value)
        return ""
    return value
