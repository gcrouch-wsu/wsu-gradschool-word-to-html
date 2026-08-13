"""Pin the session/token hardening: malformed IDs 404 via the <uuid:...>
converter, lookups never write to disk, failed DOCX exports surface an accurate
message, bundle-import manifest paths are validated, and review-page links with
unsafe URL schemes are not rendered clickable.
"""
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

import pytest

from config import PERSIST_DIR, SessionDir, is_valid_session_id


def test_healthz(client_nocsrf):
    r = client_nocsrf.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_instructions_page_renders(client_nocsrf):
    r = client_nocsrf.get("/instructions")
    assert r.status_code == 200
    assert "Instructions" in r.get_data(as_text=True)


@pytest.mark.parametrize(
    "path",
    [
        "/review/not-a-uuid",
        "/review/..",
        "/heading_review/123",
        "/convert/xyz",
        "/table_review/%2e%2e",
    ],
)
def test_malformed_session_ids_404(client_nocsrf, path):
    assert client_nocsrf.get(path).status_code == 404


def test_unknown_session_redirects_without_creating_directory(client_nocsrf):
    ghost = str(uuid.uuid4())
    r = client_nocsrf.get(f"/review/{ghost}")
    assert r.status_code == 302  # flash + redirect to index
    assert not (PERSIST_DIR / ghost).exists()


def test_download_with_malformed_token_404(client_nocsrf):
    sid = str(uuid.uuid4())
    assert client_nocsrf.get(f"/download/{sid}/junk/css").status_code == 404


def test_download_unknown_token_redirects(client_nocsrf):
    sid, tok = str(uuid.uuid4()), str(uuid.uuid4())
    r = client_nocsrf.get(f"/download/{sid}/{tok}/css")
    assert r.status_code == 302


def test_update_theme_rejects_invalid_session_id(client_nocsrf):
    r = client_nocsrf.post("/update_theme", data={"session_id": "../../etc"})
    assert r.status_code == 302  # flash + redirect, no traceback


def test_download_docx_reports_failed_export(client_nocsrf):
    """A session whose DOCX generation failed must explain, not 'file missing'."""
    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        token = str(uuid.uuid4())
        # A download requires a real session plus the token meta.
        session.session_json.write_text(json.dumps({"filename": "x.docx"}), encoding="utf-8")
        meta = {"session_id": sid, "filename": "x.docx", "docx_ok": False}
        (session.root / f"{token}_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
        r = client_nocsrf.get(
            f"/download/{sid}/{token}/docx", follow_redirects=True
        )
        assert r.status_code == 200
        assert "DOCX export failed" in r.get_data(as_text=True)
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_sessiondir_rejects_non_uuid_ids():
    for bad in ("..", "x", "../../etc", "", "43AA68D0-327E-4D2B-9F08-E5D61A021A28x"):
        with pytest.raises(ValueError):
            SessionDir(bad)


def test_sessiondir_lookup_does_not_create_directory():
    sid = str(uuid.uuid4())
    SessionDir(sid)
    assert not (PERSIST_DIR / sid).exists()


def test_is_valid_session_id():
    assert is_valid_session_id(str(uuid.uuid4()))
    assert not is_valid_session_id("not-a-uuid")
    assert not is_valid_session_id("")
    # UUID-shaped but not v4 must be rejected (version/variant nibbles enforced).
    assert not is_valid_session_id("00000000-0000-0000-0000-000000000000")
    assert not is_valid_session_id("11111111-1111-1111-1111-111111111111")
    assert not is_valid_session_id("11111111-1111-3111-8111-111111111111")  # v3


def test_download_rejects_meta_path_outside_session(client_nocsrf):
    """The download route must not serve a file referenced by meta when that
    path resolves outside the session directory (planted-meta arbitrary read)."""
    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        session.session_json.write_text(json.dumps({"filename": "x.docx"}), encoding="utf-8")
        token = str(uuid.uuid4())
        external = str((PERSIST_DIR.parent / "outside_secret.txt"))
        Path(external).write_text("SENSITIVE", encoding="utf-8")
        for field, kind in [("docx_path", "docx"), ("manual_content_path", "standalone")]:
            (session.root / f"{token}_meta.json").write_text(
                json.dumps({field: external, "filename": "x", "docx_ok": True}),
                encoding="utf-8",
            )
            r = client_nocsrf.get(f"/download/{sid}/{token}/{kind}", follow_redirects=False)
            assert r.status_code == 302, f"{kind}: out-of-session path must not be served"
            body = client_nocsrf.get(f"/download/{sid}/{token}/{kind}", follow_redirects=True).get_data(as_text=True)
            assert "SENSITIVE" not in body
        Path(external).unlink(missing_ok=True)
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_safe_next_rejects_dangerous_redirects():
    from routes.auth_routes import _safe_next
    from word_to_wordpressV4 import app
    with app.test_request_context():
        assert _safe_next("/review/abc") == "/review/abc"
        for bad in ("//evil.com", "https://evil.com", "/\\evil.com",
                    "/x\r\nLocation: https://evil.com", "/x\x00", "\\\\evil"):
            assert _safe_next(bad) == "/", f"should fall back to / for {bad!r}"


def test_font_family_cannot_break_out_of_style_block():
    from core.styling import coerce_theme_settings, build_theme_css
    payload = "x;}</style><script>alert(1)</script><style>{"
    ts, _ = coerce_theme_settings({"font_family": payload}, "chapter")
    assert "</style>" not in build_theme_css(ts)
    # Also when read straight from (attacker-influenced) meta without re-coercion:
    assert "</style>" not in build_theme_css({"font_family": payload})


# ---- Bundle-import manifest path validation ----

def _bundle_with_manifest_files(docx_name, edits_name, extra_members=()):
    """Build a .zip whose manifest['files'] points at the given names."""
    manifest = {
        "document": "x.docx",
        "files": {"docx": docx_name, "edits": edits_name},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in extra_members:
            zf.writestr(name, data)
    buf.seek(0)
    return buf


@pytest.mark.parametrize("malicious", [
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "../../../../etc/passwd",
    "..\\..\\secret.txt",
    "sub/dir/file.docx",
])
def test_bundle_manifest_rejects_non_basename_paths(client_nocsrf, malicious):
    """manifest['files'] entries that are absolute or contain separators/.. must
    be rejected before any join/move/read, even if they point at a real file."""
    secret_dir = tempfile.mkdtemp()
    secret = os.path.join(secret_dir, "secret.txt")
    with open(secret, "w", encoding="utf-8") as f:
        f.write("SENSITIVE")
    try:
        bundle = _bundle_with_manifest_files(malicious, malicious)
        r = client_nocsrf.post(
            "/import_bundle",
            data={"bundle": (bundle, "session.zip")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Malicious bundle detected" in body
        assert os.path.exists(secret), "the external file must not be moved/deleted"
    finally:
        shutil.rmtree(secret_dir, ignore_errors=True)


def test_bundle_manifest_rejects_name_not_in_archive(client_nocsrf):
    """A clean basename that isn't actually a member of the archive is rejected."""
    bundle = _bundle_with_manifest_files("ghost.docx", "ghost.json")
    r = client_nocsrf.post(
        "/import_bundle",
        data={"bundle": (bundle, "session.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Malicious bundle detected" in r.get_data(as_text=True)


def test_bundle_manifest_rejects_directory_basename(client_nocsrf):
    """A manifest pointing docx/edits at a *directory* member's basename must be
    rejected cleanly (not blow up later in compute_sha256/shutil.move)."""
    manifest = {"document": "x.docx", "files": {"docx": "foo", "edits": "edits.json"}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("foo/", "")          # directory entry whose basename is "foo"
        zf.writestr("edits.json", "{}")
    buf.seek(0)
    r = client_nocsrf.post(
        "/import_bundle",
        data={"bundle": (buf, "session.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "Malicious bundle detected" in body
    assert "Import failed" not in body  # rejected by the guard, not an exception


def test_check_min_version_rejects_unparseable_installed():
    """check_min_version must not treat a garbage version string as satisfying
    the minimum (compare_versions returns 0/'unknown' for unparseable input)."""
    from core.pandoc_wrapper import check_min_version
    assert check_min_version("3.9.0.2", "3.9.0.2") is True
    assert check_min_version("3.10", "3.9.0.2") is True
    assert check_min_version("3.8", "3.9.0.2") is False
    assert check_min_version(None, "3.9.0.2") is False
    assert check_min_version("not-a-version", "3.9.0.2") is False


# ---- Review-page link href scheme filtering ----

def test_unsafe_link_schemes_filtered_in_review_data():
    """Unit-level: is_safe_href classifies the schemes the route relies on."""
    from utils.url_policy import is_safe_href
    assert is_safe_href("https://example.com/manual")
    assert is_safe_href("#section-1")
    assert not is_safe_href("javascript:alert(1)")
    assert not is_safe_href("data:text/html,<script>1</script>")
    assert not is_safe_href("vbscript:msgbox(1)")


def test_review_page_filters_unsafe_docx_link_hrefs(client_nocsrf):
    """Route+template level: a javascript: DOCX hyperlink renders as plain text
    (no clickable href), while a safe https link stays clickable. Drives the
    real /review render, so it fails if convert_flow stops filtering."""
    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        session.session_json.write_text(json.dumps({
            "references": [[0, "See Chapter 1.A here.", "Chapter 1.A", 4, "", ""]],
            "docx_links_by_para": {"0": [
                {"href": "javascript:alert(1)", "text": "evil link", "bad": False},
                {"href": "https://ok.example/x", "text": "good link", "bad": False},
            ]},
            "new_headings": {}, "auto_crosswalk": {}, "approved_crosswalk": {},
            "manual_type": "chapter", "filename": "x.docx",
            "mapping_mode": "map_new", "html_import": False,
        }), encoding="utf-8")
        body = client_nocsrf.get(f"/review/{sid}").get_data(as_text=True)
        # Both links render (proves the str/int key coercion works)...
        assert "evil link" in body and "good link" in body
        # ...but the unsafe one is NOT a clickable href anywhere on the page,
        assert "javascript:alert(1)" not in body
        assert "<span>evil link</span>" in body
        # ...and the safe one is.
        assert 'href="https://ok.example/x"' in body
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_review_page_renders_all_reference_paragraphs_without_pagination(client_nocsrf):
    """Reference review should be one form, even when many paragraphs have refs."""
    from bs4 import BeautifulSoup

    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        references = [
            [idx, f"See Chapter {idx}.A here.", f"Chapter {idx}.A", 4, 15, ""]
            for idx in range(70)
        ]
        new_headings = {
            f"Chapter {idx}.A": {
                "full": f"Chapter {idx}.A - Heading {idx}",
                "id": f"chapter-{idx}-a",
            }
            for idx in range(70)
        }
        session.session_json.write_text(json.dumps({
            "references": references,
            "new_headings": new_headings,
            "auto_crosswalk": {ref[2]: ref[2] for ref in references},
            "approved_crosswalk": {},
            "manual_type": "chapter",
            "filename": "x.docx",
            "mapping_mode": "keep_old",
            "html_import": False,
        }), encoding="utf-8")
        body = client_nocsrf.get(f"/review/{sid}").get_data(as_text=True)
        soup = BeautifulSoup(body, "html.parser")
        assert len(soup.select(".reference-review-item")) == 70
        assert "All reference paragraphs shown (70 paragraphs)" in body
        assert soup.find("button", attrs={"name": "next_page"}) is None
        assert soup.find("button", attrs={"name": "prev_page"}) is None
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_review_page_filters_include_status_categories(client_nocsrf):
    """Auto-valid rows still need to be visible through Needs review."""
    from bs4 import BeautifulSoup

    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        session.session_json.write_text(json.dumps({
            "references": [[0, "See Chapter 1.A here.", "Chapter 1.A", 4, 15, ""]],
            "new_headings": {
                "Chapter 1.A": {
                    "full": "Chapter 1.A - Overview",
                    "id": "chapter-1-a",
                },
            },
            "auto_crosswalk": {"Chapter 1.A": "Chapter 1.A"},
            "approved_crosswalk": {},
            "manual_type": "chapter",
            "filename": "x.docx",
            "mapping_mode": "keep_old",
            "html_import": False,
        }), encoding="utf-8")
        body = client_nocsrf.get(f"/review/{sid}").get_data(as_text=True)
        soup = BeautifulSoup(body, "html.parser")
        filters = {
            button.get("data-reference-filter")
            for button in soup.select("[data-reference-filter]")
        }
        assert {"all", "ready", "skipped", "auto", "review", "action"} <= filters
        assert "Hide Reviewed Items" not in body
        assert "Old reference (from text)" not in body
        assert "DOCX citation text" in body
        item = soup.select_one(".reference-review-item")
        assert item["data-is-valid"] == "true"
        assert item["data-is-auto-matched"] == "true"
        assert item["data-is-exact-auto-match"] == "true"
        assert item["data-review-status"] == "unreviewed"
        assert soup.select_one("input[name^='ref_reviewed_']") is not None
        assert soup.select_one("#confirmVisibleReviewed") is not None
        assert soup.select_one("#confirmExactAutoReviewed") is not None
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_reviewed_status_is_persisted_separately_from_link_decision(client_nocsrf):
    """Reviewed is a workflow decision; validation still controls output links."""
    from bs4 import BeautifulSoup
    from core.docx_processor import generate_stable_ref_id

    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    ref = [0, "See Chapter 1.A here.", "Chapter 1.A", 4, 15, ""]
    ref_id = generate_stable_ref_id(ref[0], ref[3], ref[2])
    try:
        session.session_json.write_text(json.dumps({
            "references": [ref],
            "new_headings": {},
            "auto_crosswalk": {},
            "approved_crosswalk": {},
            "manual_type": "chapter",
            "filename": "x.docx",
            "mapping_mode": "map_new",
            "html_import": False,
        }), encoding="utf-8")
        r = client_nocsrf.post(f"/review/{sid}", data={
            "save_edits": "1",
            "page": "1",
            f"ref_reviewed_{ref_id}": "1",
        })
        assert r.status_code == 302
        saved = json.loads(session.edits_json.read_text(encoding="utf-8"))
        assert saved["reference_reviewed"] == {ref_id: True}
        assert saved["reference_validations"] == {ref_id: False}

        body = client_nocsrf.get(f"/review/{sid}").get_data(as_text=True)
        soup = BeautifulSoup(body, "html.parser")
        item = soup.select_one(".reference-review-item")
        reviewed_box = soup.select_one(f"#ref_reviewed_{ref_id}")
        valid_box = soup.select_one(f"#ref_valid_{ref_id}")
        assert item["data-review-status"] == "reviewed"
        assert reviewed_box.has_attr("checked")
        assert not valid_box.has_attr("checked")

        r = client_nocsrf.post(f"/review/{sid}", data={
            "save_edits": "1",
            "page": "1",
            f"ref_edit_{ref_id}": "",
        })
        assert r.status_code == 302
        saved = json.loads(session.edits_json.read_text(encoding="utf-8"))
        assert saved["reference_reviewed"] == {}
    finally:
        shutil.rmtree(session.root, ignore_errors=True)


def test_review_post_does_not_persist_unsafe_external_url(client_nocsrf):
    """A javascript: URL submitted in the External URL field is dropped (not
    written to edits.json); a safe https URL is kept."""
    sid = str(uuid.uuid4())
    session = SessionDir(sid, create=True)
    try:
        session.session_json.write_text(json.dumps({
            "references": [[0, "See Chapter 1.A here.", "Chapter 1.A", 4, "", ""]],
            "new_headings": {}, "auto_crosswalk": {}, "approved_crosswalk": {},
            "manual_type": "chapter", "filename": "x.docx",
            "mapping_mode": "map_new", "html_import": False,
        }), encoding="utf-8")
        r = client_nocsrf.post(f"/review/{sid}", data={
            "save_edits": "1", "page": "1",
            "ref_external_evil": "javascript:alert(1)",
            "ref_external_good": "https://ok.example/x",
        })
        assert r.status_code == 302
        saved = json.loads(session.edits_json.read_text(encoding="utf-8"))
        ext = saved.get("reference_external_urls", {})
        assert ext.get("good") == "https://ok.example/x"
        assert "evil" not in ext, "unsafe scheme must not be persisted"
    finally:
        shutil.rmtree(session.root, ignore_errors=True)
