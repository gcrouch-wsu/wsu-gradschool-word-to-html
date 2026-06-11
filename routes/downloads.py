"""Artifact downloads, theme updates, and session-bundle export."""

import io
import json
import html
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from flask import (
    request,
    send_file,
    redirect,
    url_for,
    flash,
)

from webapp import app
from auth import session_owner_ok
from config import SessionDir, is_valid_session_id
from services.session_state import load_session_data, save_session_data
from core.html_processor import shift_heading_levels, build_manual_grid_block
from core.docx_processor import compute_sha256
from core.styling import (
    default_theme_settings,
    coerce_theme_settings,
    build_theme_css,
    get_wp_css_text,
    get_wp_js_text,
)

logger = logging.getLogger(__name__)

def _within_session(session, path) -> bool:
    """True only if `path` resolves inside this session's directory.

    The download metadata is attacker-influenceable (a malicious bundle can
    plant a {token}_meta.json), so any file path read from it must be confined
    to the session root before it is opened.
    """
    if not path:
        return False
    try:
        root = session.root.resolve()
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return resolved == root or root in resolved.parents


@app.route("/download/<uuid:session_id>/<uuid:token>/<kind>", methods=["GET"])
def download(session_id, token, kind):
    session_id = str(session_id)
    token = str(token)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    meta_file = session.root / f"{token}_meta.json"
    # Require a real session AND per-session ownership: a download must belong to
    # the signed-in user's session (ownership is a no-op when auth is disabled).
    if session_data is None or not meta_file.exists() or not session_owner_ok(session_data):
        flash("Download not found or expired.")
        return redirect(url_for("index"))
    try:
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
    except Exception:
        meta = {}


    if kind == "css":
        css_file = session.root / f"{token}_wordpress.css"
        if css_file.exists():
            return send_file(str(css_file), as_attachment=True, download_name="wordpress.css")
    
    if kind == "js":
        js_path = Path(app.root_path) / "wordpress.js"
        if js_path.exists():
            return send_file(str(js_path), as_attachment=True, download_name="wordpress.js")
            
    if kind in ("fragment", "fragment_css", "standalone"):
        manual_content_path = Path(meta.get("manual_content_path", "") or "")
        if manual_content_path.exists() and _within_session(session, manual_content_path):
            normalized = manual_content_path.read_text(encoding='utf-8', errors='ignore')
            manual_type = meta.get("manual_type") or "chapter"
            toc_depth = meta.get("toc_depth") or 2
            numbering_mode = meta.get("numbering_mode") or "css-counters"
            theme_settings = meta.get("theme_settings") or default_theme_settings(manual_type)
            theme_id = meta.get("theme_id") or "manual"

            manual_grid_block = build_manual_grid_block(normalized, toc_depth, manual_type, numbering_mode, theme_id=theme_id)

            if kind == "fragment":
                fragment_body = shift_heading_levels(normalized, 1)
                fragment_html = build_manual_grid_block(fragment_body, toc_depth, manual_type, numbering_mode, heading_offset=1, theme_id=theme_id)
                return send_file(io.BytesIO(fragment_html.encode('utf-8')), as_attachment=True, download_name="manual_fragment.html", mimetype="text/html")
            elif kind == "fragment_css":
                wp_css = get_wp_css_text()
                theme_css = build_theme_css(theme_settings)
                wp_js = get_wp_js_text()
                combined_css = f"{wp_css}\n{theme_css}"
                fragment_body = shift_heading_levels(normalized, 1)
                fragment_html = build_manual_grid_block(fragment_body, toc_depth, manual_type, numbering_mode, heading_offset=1, theme_id=theme_id)
                styled_fragment = f"<style>\n{combined_css}\n</style>\n{fragment_html}\n<script>\n{wp_js}\n</script>"
                return send_file(io.BytesIO(styled_fragment.encode('utf-8')), as_attachment=True, download_name="manual_fragment_styled.html", mimetype="text/html")
            else:
                wp_js = get_wp_js_text()
                wp_css = get_wp_css_text()
                theme_css = build_theme_css(theme_settings)
                combined_css = f"{wp_css}\n{theme_css}"
                standalone_html = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(meta.get("filename", "manual"))}</title><style>{combined_css}</style></head><body>{manual_grid_block}<script>{wp_js}</script></body></html>'
                return send_file(io.BytesIO(standalone_html.encode('utf-8')), as_attachment=True, download_name="manual_standalone.html", mimetype="text/html")

    if kind == "docx":
        if not meta.get("docx_ok", True):
            flash("DOCX export failed during conversion; the HTML outputs are unaffected. Re-run the conversion to retry.")
            return redirect(url_for("index"))
        docx_path = Path(meta.get("docx_path", ""))
        if docx_path.exists() and _within_session(session, docx_path):
            return send_file(str(docx_path), as_attachment=True, download_name=f"{meta.get('filename', 'document')}_numbered.docx")

    if kind == "heading_map":
        stable_map_file = session.stable_map_json
        if stable_map_file.exists():
            doc_stem = Path(meta.get("filename", "document")).stem
            return send_file(str(stable_map_file), as_attachment=True, download_name=f"{doc_stem}.heading-map.json", mimetype="application/json")

    flash("Download type not supported or file missing.")
    return redirect(url_for("index"))

@app.route("/update_theme", methods=["POST"])
def update_theme():
    session_id = request.form.get("session_id", "")
    if not is_valid_session_id(session_id):
        flash("Missing or invalid session information.")
        return redirect(url_for("index"))

    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session expired or invalid.")
        return redirect(url_for("index"))

    manual_type = session_data.get('manual_type', 'chapter')

    # Update style panels state
    style_panels = session_data.get('style_panels', {"doc": True, "toc": False, "heading": False})
    style_panels["doc"] = request.form.get("doc_panel_open") == "1"
    style_panels["toc"] = request.form.get("toc_panel_open") == "1"
    style_panels["heading"] = request.form.get("heading_panel_open") == "1"
    session_data['style_panels'] = style_panels

    # Handle theme reset or update
    if 'reset_theme' in request.form:
        theme_settings, warnings = coerce_theme_settings(None, manual_type)
    else:
        theme_settings, warnings = coerce_theme_settings(
            request.form.to_dict(),
            manual_type,
            prior=session_data.get("theme_settings"),
        )
    
    session_data['theme_settings'] = theme_settings
    save_session_data(session, session_data)

    flash("Styling updated.")
    return redirect(url_for('do_convert', session_id=session_id))

@app.route("/export/<uuid:session_id>", methods=["POST"])
def export_session(session_id):
    """Export session bundle (DOCX + edits + manifest)"""
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session not found.")
        return redirect(url_for("index"))

    filename = session_data.get('filename', 'document.docx')
    src_path = Path(session_data.get('src_path', ''))
    
    # Use standardized edit path
    edit_file = session.edits_json
    if not src_path.exists() or not edit_file.exists():
        flash("Missing source DOCX or edits file; cannot export session.")
        return redirect(url_for("review", session_id=session_id))

    bundle_name = f"{Path(filename).stem}_{session_id[:8]}_session.zip"
    bundle_path = session.root / bundle_name

    stable_for_manifest = session_data.get("stable_heading_map", {}) or {}
    if session.stable_map_json.exists():
        try:
            stable_for_manifest = json.loads(session.stable_map_json.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Export: could not read stable_heading_map.json: %s", e)

    manifest = {
        "document": filename,
        "doc_hash": compute_sha256(src_path),
        "manual_type": session_data.get('manual_type', 'chapter'),
        "toc_depth": session_data.get('toc_depth', 2),
        "mapping_mode": session_data.get('mapping_mode', 'map_new'),
        "numbering_mode": session_data.get('numbering_mode', 'css-counters'),
        "preserve_numbers": session_data.get('preserve_numbers', False),
        "edit_tables": session_data.get('edit_tables', False),
        "html_import": session_data.get('html_import', False),
        "rebuild_links": session_data.get('rebuild_links', False),
        "strip_docx_formatting": session_data.get('strip_docx_formatting', False),
        "infer_heading_depth": session_data.get('infer_heading_depth', False),
        "infer_style_map": session_data.get('infer_style_map', {}),
        "infer_sequence_map": session_data.get('infer_sequence_map', {}),
        "theme_settings": session_data.get('theme_settings', {}),
        "heading_edits": session_data.get('heading_edits', {}),
        "stable_heading_map": stable_for_manifest,
        "stable_heading_map_raw": session_data.get('stable_heading_map_raw', "") or "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": {
            "docx": src_path.name,
            "edits": edit_file.name
        }
    }

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=src_path.name)
        zf.write(edit_file, arcname=edit_file.name)
        # Include the permalink continuity artifact if it exists
        stable_map_file = session.stable_map_json
        if stable_map_file.exists():
            zf.write(stable_map_file, arcname=stable_map_file.name)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return send_file(str(bundle_path), as_attachment=True, download_name=bundle_name)
