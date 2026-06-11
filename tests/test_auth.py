"""Tier-1 authentication: login gate, login/logout flow, per-session ownership.

Auth is off by default (no env accounts), so the rest of the suite is
unaffected; these tests turn it on by configuring an in-memory account table
and reset it afterward.
"""
import json
import shutil
import uuid

import pytest
from werkzeug.security import generate_password_hash

import auth
from config import SessionDir
from word_to_wordpressV4 import app

A_EMAIL, A_PW = "alice@wsu.edu", "alice-pw-123"
B_EMAIL, B_PW = "bob@wsu.edu", "bob-pw-456"


@pytest.fixture
def with_auth():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    saved_secret = app.secret_key
    app.secret_key = "test-strong-secret-not-the-default"  # auth requires a real secret
    auth.configure_users({
        A_EMAIL: generate_password_hash(A_PW),
        B_EMAIL: generate_password_hash(B_PW),
    })
    try:
        yield
    finally:
        auth.configure_users({})  # back to disabled (env is empty in tests)
        app.secret_key = saved_secret
        app.config["WTF_CSRF_ENABLED"] = True
        app.config["TESTING"] = False


def _login(client, email, pw):
    return client.post("/login", data={"email": email, "password": pw})


def test_auth_disabled_by_default():
    assert auth.auth_enabled() is False


def test_unauthenticated_request_redirects_to_login(with_auth):
    c = app.test_client()
    r = c.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_healthz_and_login_stay_public(with_auth):
    c = app.test_client()
    assert c.get("/healthz").status_code == 200
    assert c.get("/login").status_code == 200


def test_login_success_then_access(with_auth):
    c = app.test_client()
    r = _login(c, A_EMAIL, A_PW)
    assert r.status_code == 302
    assert c.get("/").status_code == 200


def test_login_rejects_bad_password(with_auth):
    c = app.test_client()
    r = _login(c, A_EMAIL, "wrong")
    assert r.status_code == 200  # re-renders the form
    assert c.get("/").status_code == 302  # still not signed in


def test_login_rejects_unknown_email(with_auth):
    c = app.test_client()
    _login(c, "nobody@wsu.edu", "whatever")
    assert c.get("/").status_code == 302


def test_logout(with_auth):
    c = app.test_client()
    _login(c, A_EMAIL, A_PW)
    assert c.get("/").status_code == 200
    r = c.post("/logout")
    assert r.status_code == 302
    assert c.get("/").status_code == 302  # signed out again


def test_ownerless_session_not_accessible_when_auth_enabled(with_auth):
    """A session with no `owner` (legacy/corrupt/planted) must not be reachable
    by any authenticated user when auth is enabled."""
    sid = str(uuid.uuid4())
    sd = SessionDir(sid, create=True)
    sd.session_json.write_text(json.dumps({
        # no "owner" key
        "references": [], "new_headings": {}, "auto_crosswalk": {},
        "approved_crosswalk": {}, "manual_type": "chapter",
        "filename": "x.docx", "mapping_mode": "map_new", "html_import": False,
    }), encoding="utf-8")
    try:
        c = app.test_client()
        _login(c, A_EMAIL, A_PW)
        assert c.get(f"/review/{sid}").status_code == 302, "ownerless session must be rejected"
    finally:
        shutil.rmtree(sd.root, ignore_errors=True)


def test_session_ownership_isolation(with_auth):
    """A session owned by Alice is not reachable by Bob."""
    sid = str(uuid.uuid4())
    sd = SessionDir(sid, create=True)
    sd.session_json.write_text(json.dumps({
        "owner": A_EMAIL,
        "references": [], "new_headings": {}, "auto_crosswalk": {},
        "approved_crosswalk": {}, "manual_type": "chapter",
        "filename": "x.docx", "mapping_mode": "map_new", "html_import": False,
    }), encoding="utf-8")
    try:
        cb = app.test_client()
        _login(cb, B_EMAIL, B_PW)
        assert cb.get(f"/review/{sid}").status_code == 302, "Bob must not reach Alice's session"

        ca = app.test_client()
        _login(ca, A_EMAIL, A_PW)
        assert ca.get(f"/review/{sid}").status_code == 200, "Alice can reach her own session"
    finally:
        shutil.rmtree(sd.root, ignore_errors=True)


def test_verify_credentials_is_case_insensitive_on_email(with_auth):
    assert auth.verify_credentials("ALICE@wsu.edu", A_PW) is not None
    assert auth.verify_credentials(A_EMAIL, "nope") is None


def test_insecure_secret_with_auth_rejects_forged_cookie():
    """With auth enabled and the default 'dev-secret', a forged login cookie
    must NOT authenticate — the gate refuses to serve."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    saved = app.secret_key
    app.secret_key = "dev-secret"  # the insecure default
    auth.configure_users({A_EMAIL: generate_password_hash(A_PW)})
    try:
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["_user_id"] = A_EMAIL  # forge "logged in as alice"
        r = c.get("/")
        assert r.status_code != 200, "forged default-secret cookie must not be honored"
    finally:
        auth.configure_users({})
        app.secret_key = saved
        app.config["WTF_CSRF_ENABLED"] = True
        app.config["TESTING"] = False
