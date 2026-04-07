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
        "table_align_mode": "auto",
        "table_col1_align": None,
        "table_coln_align": None,
        "table_header_align": None,
        "table_layout_mode": "auto",
        "table_block_align": "full",
        "table_header_bg": "#f5f5f5",
        "table_header_color": "#000000",
        "table_header_bold": False,
        "table_border_color": "#dddddd",
        "table_border_width": 1,
        "table_border_style": "solid",
        "table_cell_padding": 8,
        "table_row_stripe": False,
        "table_row_stripe_color": "#f9fafb",
    }

_ALIGN_KEYS = frozenset({"table_col1_align", "table_coln_align", "table_header_align"})
_BOOL_KEYS = frozenset({"table_header_bold", "table_row_stripe"})


def _coerce_align_value(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("", "auto", "none"):
        return None
    return s if s in ("left", "center", "right") else None


def coerce_theme_settings(
    raw_settings: dict | None,
    manual_type: str,
    prior: dict | None = None,
) -> tuple[dict, list[str]]:
    """Validate and normalize theme settings from a form or JSON.

    ``prior`` is merged after defaults so partial forms (e.g. preview theme panel)
    do not wipe unrelated keys like table options.
    """
    settings = default_theme_settings(manual_type)
    warnings: list[str] = []
    if prior:
        for key in settings:
            if key in prior:
                settings[key] = prior[key]
    if not raw_settings:
        return _finalize_theme_settings(settings, warnings)

    for key in settings:
        if key not in raw_settings:
            continue
        val = raw_settings[key]
        if key in _BOOL_KEYS:
            settings[key] = str(val).lower() in ("1", "true", "yes", "on")
        elif key in _ALIGN_KEYS:
            coerced = _coerce_align_value(val)
            if val not in (None, "") and str(val).strip().lower() not in ("", "auto", "none") and coerced is None:
                warnings.append(f"Ignored invalid table alignment for {key}.")
            settings[key] = coerced
        elif "color" in key:
            fb = settings[key] if isinstance(settings[key], str) else "#000000"
            settings[key] = normalize_hex_color(str(val), fb)
        elif key == "base_font_size":
            settings[key] = int(clamp_number(val, 8, 72, settings[key]))
        elif key == "line_height":
            settings[key] = clamp_number(val, 1.0, 3.0, settings[key])
        elif key == "table_border_width":
            settings[key] = clamp_number(val, 0, 8, settings[key])
        elif key == "table_cell_padding":
            settings[key] = int(clamp_number(val, 0, 48, settings[key]))
        elif key == "table_layout_mode":
            s = str(val).strip().lower()
            settings[key] = s if s in ("auto", "fixed") else "auto"
        elif key == "table_block_align":
            s = str(val).strip().lower()
            settings[key] = s if s in ("full", "center", "left") else "full"
        elif key == "table_border_style":
            s = str(val).strip().lower()
            settings[key] = s if s in ("solid", "dashed", "dotted", "none") else "solid"
        elif key == "table_align_mode":
            s = str(val).strip().lower()
            allowed = ("auto", "left_all", "center_all", "right_all", "right_numeric", "auto_skip_first")
            settings[key] = s if s in allowed else "auto"
        else:
            settings[key] = val

    return _finalize_theme_settings(settings, warnings)


def _finalize_theme_settings(settings: dict, warnings: list[str]) -> tuple[dict, list[str]]:
    for key in _ALIGN_KEYS:
        settings[key] = _coerce_align_value(settings.get(key))
    s = str(settings.get("table_border_style", "solid")).strip().lower()
    settings["table_border_style"] = s if s in ("solid", "dashed", "dotted", "none") else "solid"
    s = str(settings.get("table_layout_mode", "auto")).strip().lower()
    settings["table_layout_mode"] = s if s in ("auto", "fixed") else "auto"
    s = str(settings.get("table_block_align", "full")).strip().lower()
    settings["table_block_align"] = s if s in ("full", "center", "left") else "full"
    for bk in _BOOL_KEYS:
        settings[bk] = bool(settings.get(bk))
    return settings, warnings


def _build_manual_table_css(settings: dict) -> str:
    """Scoped rules that override wordpress.css table defaults (!important)."""
    layout = settings.get("table_layout_mode", "auto")
    if layout not in ("auto", "fixed"):
        layout = "auto"
    block = str(settings.get("table_block_align", "full")).lower()
    if block not in ("full", "center", "left"):
        block = "full"

    if block == "full":
        block_css = """
    .manual-grid .manual table {
        width: 100% !important;
        max-width: 100% !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }"""
    elif block == "center":
        block_css = """
    .manual-grid .manual table {
        width: auto !important;
        max-width: 100% !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }"""
    else:
        block_css = """
    .manual-grid .manual table {
        width: auto !important;
        max-width: 100% !important;
        margin-left: 0 !important;
        margin-right: auto !important;
    }"""

    hdr_bg = normalize_hex_color(str(settings.get("table_header_bg", "#f5f5f5")), "#f5f5f5")
    hdr_fg = normalize_hex_color(str(settings.get("table_header_color", "#000000")), "#000000")
    bd_color = normalize_hex_color(str(settings.get("table_border_color", "#dddddd")), "#dddddd")
    stripe = normalize_hex_color(str(settings.get("table_row_stripe_color", "#f9fafb")), "#f9fafb")
    try:
        bw = float(settings.get("table_border_width", 1))
    except (TypeError, ValueError):
        bw = 1.0
    bw = max(0.0, min(8.0, bw))
    pad = int(clamp_number(settings.get("table_cell_padding", 8), 0, 48, 8))
    bstyle = str(settings.get("table_border_style", "solid")).lower()
    if bstyle not in ("solid", "dashed", "dotted", "none"):
        bstyle = "solid"
    bold = bool(settings.get("table_header_bold"))
    stripe_on = bool(settings.get("table_row_stripe"))
    fw = "700" if bold else "400"

    if bstyle == "none":
        border_rule = "border: none !important;"
    else:
        border_rule = f"border: {bw}px {bstyle} {bd_color} !important;"

    stripe_rule = ""
    if stripe_on:
        stripe_rule = f"""
    .manual-grid .manual table tbody tr:nth-child(even) th,
    .manual-grid .manual table tbody tr:nth-child(even) td {{
        background-color: {stripe} !important;
    }}"""

    return f"""
    /* Session table theme (overrides wordpress.css) */
    .manual-grid .manual table {{
        border-collapse: collapse !important;
        table-layout: {layout} !important;
    }}
    {block_css}
    .manual-grid .manual table th,
    .manual-grid .manual table td {{
        {border_rule}
        padding: {pad}px !important;
        vertical-align: top !important;
    }}
    .manual-grid .manual table th {{
        background-color: {hdr_bg} !important;
        color: {hdr_fg} !important;
        font-weight: {fw} !important;
    }}
    {stripe_rule}
    """


def build_table_theme_css(settings: dict) -> str:
    """Table override CSS only (same rules appended after wordpress.css in exports)."""
    return _build_manual_table_css(settings)


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
    return css + build_table_theme_css(settings)

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
