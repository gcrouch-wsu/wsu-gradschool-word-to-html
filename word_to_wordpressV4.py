#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSU Manual Converter — DOCX → HTML (Preview & Downloads)

Entry point only. The Flask app object lives in webapp.py, HTTP routes in the
routes/ package, shared workflow logic in services/, and the conversion
machinery in core/. The Gunicorn/CLI target remains `word_to_wordpressV4:app`.
"""
import logging
import os

from config import PERSIST_DIR
from webapp import app, run_startup_pandoc_checks, mark_pandoc_checks_done
import routes  # noqa: F401  — importing the package registers every route on `app`
from routes.imports import _bundle_import_post_pandoc_pipeline  # noqa: F401  — re-export (tests)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    # Run eagerly so the operator sees the version / pin status before the
    # browser window opens. Mark the flag done so the before_request hook
    # does not re-run the check on the first HTTP hit.
    try:
        run_startup_pandoc_checks()
    finally:
        mark_pandoc_checks_done()
    logger.info(f"Persist directory for edits: {PERSIST_DIR}")

    port = int(os.environ.get("PORT", 5000))
    is_local = not os.environ.get("PORT")

    if is_local:
        logger.info(f"Starting on http://127.0.0.1:{port}")
        import webbrowser, threading
        threading.Timer(1.0, webbrowser.open, args=[f"http://127.0.0.1:{port}"]).start()
    else:
        logger.info(f"Starting on port {port}")

    app.run(host="0.0.0.0", port=port, debug=is_local)
