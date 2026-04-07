import logging
import re
from pathlib import Path
from docx import Document
from utils.helpers import normalize_hex_color, clamp_number

logger = logging.getLogger(__name__)

def resolve_reference_doc_path(session_id: str, session_data: dict) -> Path | None:
    """Determine the actual path to the reference DOCX for this session."""
    from config import REFERENCE_DIR, SessionDir
    ref_name = session_data.get('reference_doc_path')
    if ref_name:
        path = REFERENCE_DIR / ref_name
        if path.exists(): return path
    return None

def get_reference_style_context(session_id: str, session_data: dict) -> tuple[dict, dict]:
    """Extract style and sequence info from the session's reference doc."""
    from .docx_processor import extract_style_map_from_reference
    path = resolve_reference_doc_path(session_id, session_data)
    if path:
        return extract_style_map_from_reference(path)
    return {}, {}

def parse_reference_overrides_from_form(form, summary: dict | None = None) -> dict:
    """Extract manual reference overrides from the review form."""
    overrides = {}
    for key, value in form.items():
        if key.startswith("ref_override_"):
            ref_id = key.replace("ref_override_", "")
            if value.strip():
                overrides[ref_id] = value.strip()
    return overrides

def default_theme_settings(manual_type: str = "chapter", theme_id: str | None = None) -> dict:
    """Return default styling settings for a given manual type."""
    return {
        "theme_id": theme_id or "manual",
        "primary_color": "#8d0a0a",
        "link_color": "#8d0a0a",
        "font_family": "system-ui, -apple-system, sans-serif",
        "base_font_size": 16,
        "line_height": 1.6,
        "table_align_mode": "auto"
    }

def coerce_theme_settings(raw_settings: dict | None, manual_type: str) -> tuple[dict, list[str]]:
    """Validate and normalize theme settings from a form or JSON."""
    settings = default_theme_settings(manual_type)
    warnings = []
    if not raw_settings:
        return settings, warnings
        
    for key in settings:
        if key in raw_settings:
            val = raw_settings[key]
            if "color" in key:
                settings[key] = normalize_hex_color(str(val), settings[key])
            elif "font_size" in key or "line_height" in key:
                settings[key] = clamp_number(val, 8, 72, settings[key])
            else:
                settings[key] = val
                
    return settings, warnings

def build_theme_css(settings: dict) -> str:
    """Generate dynamic CSS based on theme settings."""
    primary = settings.get("primary_color", "#8d0a0a")
    font = settings.get("font_family", "sans-serif")
    
    css = f"""
    :root {{
        --manual-primary: {primary};
        --manual-font: {font};
    }}
    .manual-grid {{ font-family: var(--manual-font); }}
    .manual-toc h2 {{ color: var(--manual-primary); }}
    .manual a {{ color: {settings.get("link_color", primary)}; }}
    """
    return css

def get_wp_css_text() -> str:
    path = Path(__file__).parent.parent / "wordpress.css"
    return path.read_text(encoding="utf-8") if path.exists() else ""

def get_wp_js_text() -> str:
    path = Path(__file__).parent.parent / "wordpress.js"
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Convert hex #RRGGBB to (r, g, b) float tuple."""
    value = value.lstrip('#')
    return tuple(int(value[i:i+2], 16) / 255.0 for i in (0, 2, 4))

def _relative_luminance(color: str) -> float:
    """Calculate relative luminance for a color string."""
    rgb = _hex_to_rgb(normalize_hex_color(color))
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])

def contrast_ratio(fg: str, bg: str) -> float:
    """Calculate WCAG contrast ratio between two colors."""
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    if l1 < l2: l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)
