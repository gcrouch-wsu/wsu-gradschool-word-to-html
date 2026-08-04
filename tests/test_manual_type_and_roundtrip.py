"""Manual-type normalization and fragment round-trip fidelity.

Two defects covered here:

* ``preprocess_docx`` emits a third manual type, "policy", for any document
  whose opening paragraphs mention policies or procedures — the Faculty Manual
  and GSPP both match. Five call sites decided the "Chapter"/"Section" label
  independently and disagreed about what "policy" meant.
* The exporter records the manual's settings on ``.manual-grid`` and reads them
  back on import, but the sanitizer stripped every ``data-*`` first. A
  downloaded fragment therefore lost its numbering mode, TOC depth, theme and
  heading offset, so its ``h1`` chapters stayed demoted to ``h2`` forever.
"""

import io
import json
import re

import pytest

from config import SessionDir
from core.html_processor import (
    apply_css_counter_numbering,
    build_manual_grid_block,
    extract_manual_fragment,
    strip_html_assets,
)
from core.permalinks import ensure_prefixed, is_section_style, manual_prefix, normalize_manual_type

from tests.conftest import pandoc_required


# --- manual_type ---------------------------------------------------------

@pytest.mark.parametrize("manual_type", ["section", "policy", "POLICY", " Policy "])
def test_section_style_types_agree_on_the_section_label(manual_type):
    assert manual_prefix(manual_type) == "Section"
    assert is_section_style(manual_type)
    assert normalize_manual_type(manual_type) == "section"
    assert ensure_prefixed("1.2", manual_type) == "Section 1.2"
    assert "Section 1 - Overview" in apply_css_counter_numbering("<h1>Overview</h1>", manual_type)


@pytest.mark.parametrize("manual_type", ["chapter", "", None, "bogus"])
def test_everything_else_falls_back_to_chapter(manual_type):
    assert manual_prefix(manual_type) == "Chapter"
    assert not is_section_style(manual_type)
    assert normalize_manual_type(manual_type) == "chapter"
    assert ensure_prefixed("1.2", manual_type) == "Chapter 1.2"
    assert "Chapter 1 - Overview" in apply_css_counter_numbering("<h1>Overview</h1>", manual_type)


def test_policy_manual_numbering_matches_its_crosswalk_prefix():
    """The regression itself: numbering said "Section", the crosswalk said "Chapter"."""
    numbered = apply_css_counter_numbering("<h1>Overview</h1>", "policy")
    label = re.search(r"<h1>(\w+)", numbered).group(1)
    assert ensure_prefixed("1", "policy").startswith(label)


def test_grid_attribute_is_normalized_for_css_and_js():
    """The CSS/JS only understand chapter|section; "policy" matched neither."""
    grid = build_manual_grid_block("<p>x</p>", 2, "policy", "css-counters")
    assert 'data-manual-type="section"' in grid


def test_grid_attributes_reject_hostile_values():
    """Grid metadata is re-validated, so an imported value cannot break out."""
    grid = build_manual_grid_block(
        "<p>x</p>", "9; drop", 'x" onmouseover="alert(1)', "javascript:x", heading_offset="1"
    )
    assert 'data-manual-type="chapter"' in grid
    assert 'data-numbering-mode="css-counters"' in grid
    assert 'data-toc-depth="2"' in grid
    assert "onmouseover" not in grid


# --- grid metadata survives sanitization ---------------------------------

def test_grid_settings_survive_the_sanitizer():
    src = (
        '<div class="manual-grid" data-toc-depth="4" data-manual-type="section" '
        'data-numbering-mode="preserve" data-heading-offset="1" data-theme="faculty">'
        '<div class="manual"><h2>Section One</h2></div></div>'
    )
    _frag, meta = extract_manual_fragment(strip_html_assets(src))
    assert meta["manual_type"] == "section"
    assert meta["toc_depth"] == "4"
    assert meta["numbering_mode"] == "preserve"
    assert meta["heading_offset"] == "1"
    assert meta["theme_id"] == "faculty"


def test_sanitizer_still_strips_scripts_and_handlers():
    src = (
        '<div class="manual-grid" data-toc-depth="2" onclick="alert(1)">'
        '<div class="manual"><p onmouseover="alert(2)">hi</p>'
        '<script>alert(3)</script></div></div>'
    )
    cleaned = strip_html_assets(src)
    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "onmouseover" not in cleaned
    assert 'data-toc-depth="2"' in cleaned


# --- end-to-end fragment round trip --------------------------------------

def _convert(client, docx_bytes, **form):
    data = {"docx": (io.BytesIO(docx_bytes), "m.docx"), "mapping_mode": "map_new"}
    data.update(form)
    r = client.post("/convert", data=data, content_type="multipart/form-data")
    sid = r.headers["Location"].rstrip("/").split("/")[-1]
    client.post(f"/heading_review/{sid}", data={})
    client.post(f"/review/{sid}", data={"proceed": "1"})
    client.get(f"/convert/{sid}")
    token = json.loads(SessionDir(sid).session_json.read_text())["token"]
    return sid, token


def _levels(html):
    body = re.search(r'<main class="manual".*?</main>', html, re.S)
    scope = body.group(0) if body else html
    return [int(m) for m in re.findall(r"<h([1-6])[^>]*>", scope)]


@pandoc_required
def test_fragment_round_trip_restores_heading_levels(client_nocsrf, fixture_docx_bytes):
    """Re-importing a downloaded fragment must undo its +1 heading shift."""
    sid, token = _convert(client_nocsrf, fixture_docx_bytes, toc_depth="3")
    fragment = client_nocsrf.get(f"/download/{sid}/{token}/fragment").get_data(as_text=True)
    assert 'data-heading-offset="1"' in fragment
    assert min(_levels(fragment)) == 2, "a fragment is shifted down one level"

    r = client_nocsrf.post(
        "/import_html",
        data={"html_file": (io.BytesIO(fragment.encode()), "f.html")},
        content_type="multipart/form-data",
    )
    sid2 = r.headers["Location"].rstrip("/").split("/")[-1]
    session_data = json.loads(SessionDir(sid2).session_json.read_text())
    assert session_data["toc_depth"] == 3, "TOC depth must survive the round trip"

    client_nocsrf.post(f"/review/{sid2}", data={"proceed": "1"})
    preview = client_nocsrf.get(f"/convert/{sid2}").get_data(as_text=True)
    assert min(_levels(preview)) == 1, "import must restore chapters to h1"


@pandoc_required
def test_fragment_round_trip_is_idempotent(client_nocsrf, fixture_docx_bytes):
    """Fragment -> import -> fragment yields the same levels and anchors."""
    sid, token = _convert(client_nocsrf, fixture_docx_bytes, toc_depth="3")
    first = client_nocsrf.get(f"/download/{sid}/{token}/fragment").get_data(as_text=True)

    r = client_nocsrf.post(
        "/import_html",
        data={"html_file": (io.BytesIO(first.encode()), "f.html")},
        content_type="multipart/form-data",
    )
    sid2 = r.headers["Location"].rstrip("/").split("/")[-1]
    client_nocsrf.post(f"/review/{sid2}", data={"proceed": "1"})
    client_nocsrf.get(f"/convert/{sid2}")
    token2 = json.loads(SessionDir(sid2).session_json.read_text())["token"]
    second = client_nocsrf.get(f"/download/{sid2}/{token2}/fragment").get_data(as_text=True)

    assert _levels(first) == _levels(second)
    assert re.findall(r'<h[1-6] id="([^"]+)"', first) == re.findall(r'<h[1-6] id="([^"]+)"', second)
    assert 'data-toc-depth="3"' in second
