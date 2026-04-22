import os
import tempfile
from pathlib import Path

# --- Application Configuration ---
# Environment-backed settings with sensible defaults
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "48"))

# Bundle / ZIP import limits (uncompressed totals; defense-in-depth)
ZIP_MAX_UNCOMPRESSED_BYTES = int(os.environ.get("ZIP_MAX_UNCOMPRESSED_BYTES", str(200 * 1024 * 1024)))
ZIP_MAX_FILES = int(os.environ.get("ZIP_MAX_FILES", "5000"))

# --- Pandoc Version Policy ---
# Pinned "known-good" Pandoc version. The app does not auto-upgrade; it only
# warns when the installed binary is older than this or when a newer upstream
# release exists. Bump this value when you intentionally adopt a new release.
PANDOC_PINNED_VERSION = os.environ.get("PANDOC_PINNED_VERSION", "3.9.0.2")

# Set to "0" to disable the one-shot GitHub release lookup at startup.
PANDOC_UPDATE_CHECK_ENABLED = os.environ.get("PANDOC_UPDATE_CHECK_ENABLED", "1") not in ("0", "false", "False", "")

# How long a successful update check is cached before the app will re-query
# GitHub. Default: 7 days.
PANDOC_UPDATE_CHECK_TTL_HOURS = int(os.environ.get("PANDOC_UPDATE_CHECK_TTL_HOURS", "168"))

# Network timeout for the update check. Startup never waits longer than this.
PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS = float(os.environ.get("PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS", "3.0"))

# --- Path Configuration ---
# All paths resolve under a single PERSIST_DIR
PERSIST_DIR = Path(os.environ.get("PERSIST_DIR", tempfile.gettempdir())) / "docx2html_wsumanual"
PERSIST_DIR.mkdir(parents=True, exist_ok=True)

# Centralized location for reference templates (relative to app root)
REFERENCE_DIR = Path(__file__).parent / "reference_docs"

# Cache file for the last-known-latest Pandoc version (GitHub lookup).
PANDOC_UPDATE_CACHE_PATH = PERSIST_DIR / "pandoc_update_cache.json"

# --- Session Isolation Helper ---
class SessionDir:
    """
    Manages a single session's isolated directory and paths.
    Ensures that filenames are never used as raw path components to avoid collisions.
    """
    def __init__(self, session_id: str):
        self.session_id = str(session_id)
        self.root = PERSIST_DIR / self.session_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.export_dir = self.root / "export"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    @property
    def source_docx(self) -> Path:
        """The original uploaded DOCX file."""
        return self.root / "source.docx"

    @property
    def pre_docx(self) -> Path:
        """The preprocessed DOCX ready for Pandoc."""
        return self.root / "source.pre.docx"

    @property
    def temp_html(self) -> Path:
        """The raw Pandoc output HTML."""
        return self.root / "source.temp.html"

    @property
    def edits_json(self) -> Path:
        """Manual reference and link overrides."""
        return self.root / "edits.json"

    @property
    def stable_map_json(self) -> Path:
        """The canonical signature-to-ID permalink artifact."""
        return self.root / "stable_heading_map.json"

    @property
    def manifest_json(self) -> Path:
        """The session state and metadata (manifest.json)."""
        return self.root / "manifest.json"

    @property
    def export_html(self) -> Path:
        """The final formatted HTML output."""
        return self.export_dir / "output.html"

    @property
    def export_docx(self) -> Path:
        """The final plain-Pandoc DOCX output."""
        return self.export_dir / "output.docx"

    @property
    def session_json(self) -> Path:
        """The primary session state file within the isolated session directory."""
        return self.root / "session.json"

    def exists(self) -> bool:
        return self.root.exists()

    def __repr__(self):
        return f"<SessionDir {self.session_id} at {self.root}>"
