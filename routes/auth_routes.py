"""Login / logout routes (Tier-1 auth)."""
import logging

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user

from webapp import app
from auth import auth_enabled, verify_credentials, current_uid

logger = logging.getLogger(__name__)


def _safe_next(target: str | None) -> str:
    """Only allow same-app relative redirects (no scheme/host)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth_enabled():
        return redirect(url_for("index"))
    if current_uid():
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        user = verify_credentials(email, password)
        if user:
            login_user(user)
            logger.info("Login succeeded for %s", user.get_id())
            return redirect(_safe_next(request.args.get("next") or request.form.get("next")))
        logger.warning("Login failed for %r", (email or "")[:80])
        flash("Invalid email or password.")

    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("You have been signed out.")
    return redirect(url_for("login") if auth_enabled() else url_for("index"))
