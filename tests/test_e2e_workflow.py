"""End-to-end workflow tests: upload -> heading review -> convert -> downloads.

Requires Pandoc on PATH (skipped otherwise; CI installs the pinned version).
Drives the real pipeline with a small generated DOCX, then verifies every
download kind and the heading-map permalink-stability contract.
"""
import io
import json
import re
import shutil
from pathlib import Path


from config import PERSIST_DIR
from tests.conftest import pandoc_required

DOWNLOAD_LINK_RE = re.compile(
    r"/download/(?P<sid>[0-9a-f-]{36})/(?P<token>[0-9a-f-]{36})/docx"
)


def _run_conversion(client, docx_bytes, extra_form=None):
    """POST a DOCX through /convert and return (session_id, token, preview_html)."""
    data = {
        "docx": (io.BytesIO(docx_bytes), "manual.docx"),
        "toc_depth": "2",
        "mapping_mode": "map_new",
    }
    if extra_form:
        data.update(extra_form)
    r = client.post("/convert", data=data, content_type="multipart/form-data")
    assert r.status_code == 302, "upload should redirect into the review flow"
    location = r.headers["Location"]
    assert "/heading_review/" in location, f"unexpected redirect: {location}"
    sid = location.rstrip("/").split("/")[-1]

    r = client.get(location)
    assert r.status_code == 200

    r = client.get(f"/convert/{sid}")
    assert r.status_code == 200
    preview = r.get_data(as_text=True)
    m = DOWNLOAD_LINK_RE.search(preview)
    assert m, "preview should contain download links"
    assert m.group("sid") == sid
    return sid, m.group("token"), preview


def _cleanup(*session_ids):
    for sid in session_ids:
        shutil.rmtree(PERSIST_DIR / sid, ignore_errors=True)


@pandoc_required
def test_full_workflow_and_all_download_kinds(client_nocsrf, fixture_docx_bytes):
    sid, token, preview = _run_conversion(client_nocsrf, fixture_docx_bytes)
    try:
        assert "manual-grid" in preview

        for kind in ("standalone", "fragment", "fragment_css", "css", "js", "heading_map"):
            r = client_nocsrf.get(f"/download/{sid}/{token}/{kind}")
            assert r.status_code == 200, f"download kind {kind} failed"
            assert len(r.data) > 0

        # DOCX round-trip output must be a real DOCX (ZIP container)
        r = client_nocsrf.get(f"/download/{sid}/{token}/docx")
        assert r.status_code == 200
        assert r.data[:2] == b"PK"

        # Fragment carries the accessible grid shell
        frag = client_nocsrf.get(f"/download/{sid}/{token}/fragment").get_data(as_text=True)
        assert "manual-grid" in frag
        assert "manual-toc" in frag
    finally:
        _cleanup(sid)


@pandoc_required
def test_heading_review_form_round_trip(client_nocsrf, fixture_docx_bytes):
    """POST the heading-review form back using the field names the template
    actually rendered, pinning the template <-> handler contract."""
    data = {
        "docx": (io.BytesIO(fixture_docx_bytes), "manual.docx"),
        "toc_depth": "2",
        "mapping_mode": "map_new",
    }
    r = client_nocsrf.post("/convert", data=data, content_type="multipart/form-data")
    sid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        page = client_nocsrf.get(f"/heading_review/{sid}").get_data(as_text=True)
        hidden = re.findall(r'name="old_ref_(head_\d+)" value="([^"]*)"', page)
        assert hidden, "heading review should render at least one crosswalk row"

        form = {}
        for heading_id, old_ref in hidden[:3]:
            form[f"valid_{heading_id}"] = "on"
            form[f"old_ref_{heading_id}"] = old_ref
            form[f"new_ref_{heading_id}"] = old_ref
            form[f"new_title_{heading_id}"] = "Edited Title"
        r = client_nocsrf.post(f"/heading_review/{sid}", data=form)
        assert r.status_code == 302
        assert f"/review/{sid}" in r.headers["Location"]
    finally:
        _cleanup(sid)


@pandoc_required
def test_review_page_renders(client_nocsrf, fixture_docx_bytes):
    sid, _, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    try:
        r = client_nocsrf.get(f"/review/{sid}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Review Crosswalk and References" in body
        assert 'name="csrf_token"' in body
        assert "reference-review-item" in body  # at least one reference rendered
    finally:
        _cleanup(sid)


@pandoc_required
def test_table_review_page_and_live_preview(client_nocsrf, fixture_docx_with_table_bytes):
    sid, _, _ = _run_conversion(client_nocsrf, fixture_docx_with_table_bytes)
    try:
        r = client_nocsrf.get(f"/table_review/{sid}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Table Review" in body
        assert "table-review-form" in body

        r = client_nocsrf.post(
            f"/table_review/{sid}/preview",
            json={"table_header_bg": "#981E32", "table_col1_align": "left"},
        )
        assert r.status_code == 200
        j = r.get_json()
        assert j["ok"] is True
        assert "<table" in j["table_html"]
    finally:
        _cleanup(sid)


@pandoc_required
def test_preview_refresh_hits_cache(client_nocsrf, fixture_docx_bytes):
    """Refreshing the preview with unchanged inputs must not re-run the
    conversion: the same token is served from the cached artifacts."""
    sid, token, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    try:
        r = client_nocsrf.get(f"/convert/{sid}")
        assert r.status_code == 200
        m = DOWNLOAD_LINK_RE.search(r.get_data(as_text=True))
        assert m and m.group("token") == token, "unchanged inputs should reuse the cached token"
        assert "manual-grid" in r.get_data(as_text=True)
    finally:
        _cleanup(sid)


@pandoc_required
def test_static_css_change_busts_preview_cache(client_nocsrf, fixture_docx_bytes):
    """A change to the static wordpress.css must invalidate the preview cache
    the refreshed preview reflects the new CSS, not the stale
    token artifact."""
    import core.styling as styling

    sid, _, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    css_path = Path(styling.__file__).parent.parent / "wordpress.css"
    original = css_path.read_text(encoding="utf-8")
    marker = "ZZZ_CACHE_BUST_MARKER_42"
    try:
        css_path.write_text(original + f"\n/* {marker} */\n", encoding="utf-8")
        r = client_nocsrf.get(f"/convert/{sid}")
        assert r.status_code == 200
        assert marker in r.get_data(as_text=True), "preview should reflect updated CSS"
    finally:
        css_path.write_text(original, encoding="utf-8")
        _cleanup(sid)


@pandoc_required
def test_changed_inputs_reconvert_and_clean_up(client_nocsrf, fixture_docx_bytes):
    """Changing an input (theme) invalidates the preview cache: a fresh token
    is issued and the previous token's artifacts are deleted."""
    sid, token, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    try:
        r = client_nocsrf.post(
            "/update_theme",
            data={"session_id": sid, "token": token, "table_header_bg": "#123456"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        m = DOWNLOAD_LINK_RE.search(r.get_data(as_text=True))
        assert m, "preview after theme change should render download links"
        new_token = m.group("token")
        assert new_token != token, "changed inputs should issue a fresh token"
        meta_files = list((PERSIST_DIR / sid).glob("*_meta.json"))
        assert len(meta_files) == 1, "old token artifacts should be deleted on re-convert"
        assert new_token in meta_files[0].name
    finally:
        _cleanup(sid)


@pandoc_required
def test_bundle_export_import_round_trip(client_nocsrf, fixture_docx_bytes):
    """Export a session bundle, re-import it, and land back in the review flow."""
    sid1, _, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    sid2 = None
    try:
        # Save once on the review page so edits.json exists (export requires it)
        r = client_nocsrf.post(f"/review/{sid1}", data={"save_edits": "1", "page": "1"})
        assert r.status_code == 302

        r = client_nocsrf.post(f"/export/{sid1}")
        assert r.status_code == 200
        assert r.data[:2] == b"PK"

        r = client_nocsrf.post(
            "/import_bundle",
            data={"bundle": (io.BytesIO(r.data), "session.zip")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        location = r.headers["Location"]
        assert "/heading_review/" in location
        sid2 = location.rstrip("/").split("/")[-1]
        assert client_nocsrf.get(location).status_code == 200
        assert (PERSIST_DIR / sid2 / "session.json").exists()
    finally:
        _cleanup(sid1, *([sid2] if sid2 else []))


@pandoc_required
def test_keep_old_bundle_import_uses_identity_crosswalk_and_persists_stable_map(
    client_nocsrf, fixture_docx_bytes
):
    """A keep_old bundle must re-import with identity-crosswalk behavior (not
    auto-match) and persist the stable map it actually applied."""
    # Convert in keep_old mode (redirects straight to /review, not heading_review).
    r = client_nocsrf.post(
        "/convert",
        data={"docx": (io.BytesIO(fixture_docx_bytes), "manual.docx"),
              "toc_depth": "2", "mapping_mode": "keep_old"},
        content_type="multipart/form-data",
    )
    sid1 = r.headers["Location"].rstrip("/").split("/")[-1]
    sid2 = None
    try:
        client_nocsrf.get(f"/convert/{sid1}")  # produce artifacts + stable map
        client_nocsrf.post(f"/review/{sid1}", data={"save_edits": "1", "page": "1"})
        bundle = client_nocsrf.post(f"/export/{sid1}").data
        r = client_nocsrf.post(
            "/import_bundle",
            data={"bundle": (io.BytesIO(bundle), "session.zip")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        sid2 = r.headers["Location"].rstrip("/").split("/")[-1]
        sd = json.loads((PERSIST_DIR / sid2 / "session.json").read_text(encoding="utf-8"))
        assert sd["mapping_mode"] == "keep_old"
        # identity crosswalk: every old ref maps to itself
        cw = sd.get("auto_crosswalk", {})
        assert cw and all(k == v for k, v in cw.items()), "keep_old must use identity crosswalk"
        # stable map persisted into the session (finding #6)
        assert sd.get("stable_heading_map"), "imported session must persist the stable map"
    finally:
        _cleanup(sid1, *([sid2] if sid2 else []))


@pandoc_required
def test_import_html_starts_review_session(client_nocsrf, fixture_docx_bytes):
    """A downloaded fragment can be re-imported through the HTML path."""
    sid1, token, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    sid2 = None
    try:
        frag = client_nocsrf.get(f"/download/{sid1}/{token}/fragment")
        assert frag.status_code == 200

        r = client_nocsrf.post(
            "/import_html",
            data={"html_file": (io.BytesIO(frag.data), "manual_fragment.html")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        location = r.headers["Location"]
        assert "/review/" in location
        sid2 = location.rstrip("/").split("/")[-1]
        assert client_nocsrf.get(location).status_code == 200
    finally:
        _cleanup(sid1, *([sid2] if sid2 else []))


@pandoc_required
def test_heading_map_keeps_permalinks_stable(client_nocsrf, fixture_docx_bytes):
    """Core product promise: re-converting the same document with the previous
    heading map yields identical anchor IDs."""
    sid1, token1, _ = _run_conversion(client_nocsrf, fixture_docx_bytes)
    sid2 = None
    try:
        r = client_nocsrf.get(f"/download/{sid1}/{token1}/heading_map")
        assert r.status_code == 200
        map_run1 = json.loads(r.data)
        assert map_run1, "heading map should not be empty"

        sid2, token2, _ = _run_conversion(
            client_nocsrf,
            fixture_docx_bytes,
            extra_form={
                "stable_heading_map_file": (io.BytesIO(r.data), "manual.heading-map.json"),
            },
        )
        r = client_nocsrf.get(f"/download/{sid2}/{token2}/heading_map")
        assert r.status_code == 200
        map_run2 = json.loads(r.data)
        assert map_run2 == map_run1
    finally:
        _cleanup(sid1, *( [sid2] if sid2 else [] ))
