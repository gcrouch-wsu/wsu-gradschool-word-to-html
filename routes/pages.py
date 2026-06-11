"""Static pages: home, instructions, health probe."""

import logging
from pathlib import Path

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
)
import markdown

from webapp import app
from core.styling import get_wp_css_text, get_wp_js_text

logger = logging.getLogger(__name__)

@app.route("/healthz")
def healthz():
    """Liveness probe for Docker/Railway health checks."""
    return {"status": "ok"}, 200

@app.route("/instructions")
def instructions():
    instructions_path = Path(app.root_path) / "instructions.md"
    if not instructions_path.is_file():
        flash("Instructions are temporarily unavailable.")
        return redirect(url_for("index"))
    md_text = instructions_path.read_text(encoding="utf-8")
    content_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
    )
    return render_template("instructions.html", content=content_html)

@app.route("/", methods=["GET"])
def index():
    # Load WordPress CSS and JS for preview
    wp_css_text = get_wp_css_text()
    wp_js_text = get_wp_js_text()
    wp_css = f"<style>{wp_css_text}</style>" if wp_css_text else ""
    wp_js = f"<script>{wp_js_text}</script>" if wp_js_text else ""

    return render_template(
        "home.html",
        show_preview=False,
        hide_upload=False,
        wordpress_css_tag=wp_css,
        wordpress_js_tag=wp_js
    )
