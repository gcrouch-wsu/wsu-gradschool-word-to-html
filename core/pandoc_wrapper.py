import json
import logging
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

PANDOC_RELEASES_URL = "https://api.github.com/repos/jgm/pandoc/releases/latest"
_VERSION_RE = re.compile(r"^pandoc(?:\.exe)?\s+(\d+(?:\.\d+){1,3})", re.IGNORECASE)


def run_pandoc(input_path: Path, output_path: Path, reference_doc: Path | None = None) -> None:
    """
    Execute Pandoc conversion from DOCX to HTML.
    """
    cmd = [
        "pandoc",
        str(input_path),
        "-f", "docx",
        "-t", "html",
        "--wrap=none",
        "-s",
        "-o", str(output_path)
    ]

    if reference_doc and reference_doc.exists():
        cmd.extend(["--reference-doc", str(reference_doc)])
        logger.info(f"Pandoc: Using reference doc {reference_doc.name}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Pandoc: Converted {input_path.name} to HTML")
    except subprocess.CalledProcessError as e:
        logger.error(f"Pandoc failed: {e.stderr}")
        raise


def run_pandoc_html_to_docx(input_path: Path, output_path: Path) -> None:
    """
    Execute Pandoc conversion from HTML back to DOCX (round-trip export).
    """
    cmd = [
        "pandoc",
        str(input_path),
        "-f", "html",
        "-t", "docx",
        "-o", str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Pandoc: Converted {input_path.name} to DOCX")
    except subprocess.CalledProcessError as e:
        logger.error(f"Pandoc failed: {e.stderr}")
        raise


def _parse_version_string(text: object) -> tuple[int, ...] | None:
    """
    Parse a version like '3.9.0.2' into a tuple of ints. Returns None on failure.
    Leading 'v' and surrounding whitespace are tolerated. Non-string inputs
    (e.g. a tampered cache that stored a number) return None instead of raising.
    """
    if not isinstance(text, str) or not text:
        return None
    cleaned = text.strip().lstrip("vV")
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}", cleaned):
        return None
    try:
        return tuple(int(p) for p in cleaned.split("."))
    except ValueError:
        return None


def get_pandoc_version() -> str | None:
    """
    Return the installed Pandoc version string (e.g. '3.9.0.2'), or None
    if Pandoc is not on PATH or the output could not be parsed.
    """
    try:
        result = subprocess.run(
            ["pandoc", "-v"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None

    first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    match = _VERSION_RE.match(first_line)
    return match.group(1) if match else None


def compare_versions(a: str, b: str) -> int:
    """
    Compare two dotted version strings. Returns -1 if a<b, 0 if equal, 1 if a>b.
    Missing components are treated as 0, so '3.9' == '3.9.0.0'.
    Returns 0 when either input is unparseable (caller should treat as "unknown").
    """
    pa, pb = _parse_version_string(a), _parse_version_string(b)
    if pa is None or pb is None:
        return 0
    # Pad to equal length so '3.9' and '3.9.0.2' compare sensibly.
    width = max(len(pa), len(pb))
    pa = pa + (0,) * (width - len(pa))
    pb = pb + (0,) * (width - len(pb))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def check_min_version(installed: str | None, minimum: str) -> bool:
    """True if `installed` >= `minimum`. False if `installed` is None, older,
    or unparseable.

    `compare_versions` returns 0 (the "equal" value) when either operand is
    unparseable, so a raw `>= 0` would treat a garbage version as satisfying the
    minimum. Guard explicitly so an unparseable `installed` fails the check.
    """
    if not installed:
        return False
    if _parse_version_string(installed) is None or _parse_version_string(minimum) is None:
        return False
    return compare_versions(installed, minimum) >= 0


def _read_cache(cache_path: Path) -> dict | None:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(cache_path: Path, payload: dict) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.debug("Could not write pandoc update cache", exc_info=True)


def _fetch_latest_pandoc_version(timeout_seconds: float) -> str | None:
    """
    Query the GitHub Releases API for the latest Pandoc tag.
    Returns the tag (e.g. '3.9.0.2') or None on any network/parse failure.
    Any exception is swallowed — this must never block app startup.
    """
    req = urllib.request.Request(
        PANDOC_RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "wsu-gradschool-word-to-html/pandoc-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read()
        # errors="replace" so a non-UTF-8 body (unexpected from GitHub but
        # possible from a proxy / captive portal) cannot raise.
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name") or data.get("name")
    if not isinstance(tag, str):
        return None
    cleaned = tag.strip().lstrip("vV")
    return cleaned or None


def check_for_pandoc_update(
    installed: str | None,
    cache_path: Path,
    ttl_seconds: int,
    timeout_seconds: float = 3.0,
) -> str | None:
    """
    Return the latest-upstream Pandoc version string if it is newer than
    `installed`, otherwise None. Caches the last-known-latest on disk to
    avoid hitting GitHub on every startup.

    Any network, parse, or cache-corruption failure is swallowed and returns
    None — the check must never block app startup.
    """
    try:
        now = int(time.time())
        cache = _read_cache(cache_path) or {}

        cached_latest = cache.get("latest")
        if not isinstance(cached_latest, str) or not cached_latest:
            cached_latest = None

        try:
            cached_at = int(cache.get("checked_at", 0) or 0)
        except (TypeError, ValueError):
            cached_at = 0

        if cached_latest and (now - cached_at) < max(0, ttl_seconds):
            latest = cached_latest
        else:
            latest = _fetch_latest_pandoc_version(timeout_seconds) or cached_latest
            if latest:
                _write_cache(cache_path, {"latest": latest, "checked_at": now})

        if not latest or not installed:
            return None
        return latest if compare_versions(installed, latest) < 0 else None
    except Exception:
        logger.debug("Pandoc update check failed unexpectedly", exc_info=True)
        return None
