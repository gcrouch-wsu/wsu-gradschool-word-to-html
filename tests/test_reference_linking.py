"""Regression tests for export-time internal reference linking.

Covers the Faculty Manual failure mode (Pandoc/Word hrefs left pointing at
pre-rewrite heading ids) and the permalink early/final id divergence case.
"""
from bs4 import BeautifulSoup

from core.html_processor import (
    generate_stable_ref_id,
    process_html_pipeline,
    _add_heading_ids_impl,
    _rewrite_internal_hrefs,
    apply_reference_edits,
)
from core.permalinks import normalize_heading_signature


def _body_links(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if href.startswith("#") and href not in ("#", "#main-content"):
            out.append((href, (a.get_text() or "").strip()))
    return out


def _ids(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    return {
        (h.get_text() or "").strip(): h.get("id")
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    }


def test_pandoc_heading_id_remap_rewrites_body_hrefs():
    """Faculty-manual failure: Word/Pandoc href keeps periods; app slug does not."""
    html = (
        '<h4 id="i.b.3.-career-track">I.B.3. Career Track</h4>'
        '<p>Eligible per <a href="#i.b.3.-career-track">Section I.B.3</a>.</p>'
    )
    soup = BeautifulSoup(html, "html.parser")
    remap = _add_heading_ids_impl(soup, overwrite_existing=True, stable_map=None)
    assert "i.b.3.-career-track" in remap
    assert remap["i.b.3.-career-track"] == "ib3-career-track"
    _rewrite_internal_hrefs(soup, remap)
    assert soup.find("h4")["id"] == "ib3-career-track"
    assert soup.find("a")["href"] == "#ib3-career-track"


def test_pipeline_rewrites_pandoc_hrefs_with_preserve_numbers():
    html = (
        '<h4 id="i.b.3.-career-track">I.B.3. Career Track</h4>'
        '<p>Eligible per <a href="#i.b.3.-career-track">Section I.B.3</a>.</p>'
        '<p>Also see <a href="#Xdeadbeef1234567890abcdef1234567890abcdef">Chapter 42.52</a>.</p>'
    )
    body, _ = process_html_pipeline(
        html,
        "00000000-0000-4000-8000-000000000001",
        {"preserve_numbers": True, "toc_depth": 2},
    )
    by_text = {text: href for href, text in _body_links(body)}
    assert by_text.get("Section I.B.3") == "#ib3-career-track"
    # Orphan Word-bookmark fragment with no heading target is unwrapped
    assert "Chapter 42.52" not in by_text
    assert "Chapter 42.52" in BeautifulSoup(body, "html.parser").get_text()


def test_docx_para_index_mismatch_still_links_by_text_search():
    """DOCX paragraph index 5 must not skip a ref that only exists as HTML <p>[0]."""
    html = (
        "<h1>Intro</h1><h2>Overview</h2>"
        "<p>See Chapter 1.1 for details about the program.</p>"
    )
    rid = generate_stable_ref_id(5, 4, "Chapter 1.1")
    body, _ = process_html_pipeline(
        html,
        "00000000-0000-4000-8000-000000000001",
        {
            "preserve_numbers": False,
            "toc_depth": 2,
            "references": [(5, "See Chapter 1.1 for details about the program.", "Chapter 1.1", 4)],
            "reference_edits": {},
            "reference_validations": {rid: True},
            "reference_link_targets": {rid: "1.1 - Overview"},
            "new_headings": {
                # Deliberately stale early ids — pipeline must use live soup ids
                "1": {"id": "stale-intro", "full": "1 - Intro", "text": "Intro"},
                "1.1": {"id": "stale-overview", "full": "1.1 - Overview", "text": "Overview"},
            },
            "auto_crosswalk": {"Chapter 1.1": "1.1 - Overview"},
        },
    )
    links = _body_links(body)
    assert links, body
    href, text = links[0]
    assert href == "#overview"
    assert "1.1" in text or "Overview" in text
    assert BeautifulSoup(body, "html.parser").find(id="overview") is not None


def test_auto_crosswalk_without_link_targets_still_creates_anchor():
    html = "<h1>Intro</h1><h2>Overview</h2><p>See Chapter 1.1 for details.</p>"
    rid = generate_stable_ref_id(0, 4, "Chapter 1.1")
    body, _ = process_html_pipeline(
        html,
        "00000000-0000-4000-8000-000000000001",
        {
            "preserve_numbers": False,
            "toc_depth": 2,
            "references": [(0, "See Chapter 1.1 for details.", "Chapter 1.1", 4)],
            "reference_edits": {},
            "reference_validations": {rid: True},
            "reference_link_targets": {},
            "auto_crosswalk": {"Chapter 1.1": "1.1 - Overview"},
            "new_headings": {
                "1": {"id": "intro", "full": "1 - Intro", "text": "Intro"},
                "1.1": {"id": "overview", "full": "1.1 - Overview", "text": "Overview"},
            },
        },
    )
    links = _body_links(body)
    assert links, body
    assert links[0][0] == "#overview"


def test_stable_map_links_use_final_ids_not_early_scrape_ids():
    """Permalink map: early scrape ids must not be baked into hrefs."""
    html = (
        "<h1>Admissions Overview</h1>"
        "<h2>Requirements Detail</h2>"
        "<p>See Chapter 1.1 here.</p>"
    )
    stable = {
        normalize_heading_signature("Admissions Overview"): ["permalink-admissions"],
        normalize_heading_signature("Requirements Detail"): ["permalink-requirements"],
    }
    rid = generate_stable_ref_id(0, 4, "Chapter 1.1")
    body, _ = process_html_pipeline(
        html,
        "00000000-0000-4000-8000-000000000001",
        {
            "preserve_numbers": False,
            "toc_depth": 2,
            "stable_heading_map": stable,
            "references": [(0, "See Chapter 1.1 here.", "Chapter 1.1", 4)],
            "reference_edits": {},
            "reference_validations": {rid: True},
            "reference_link_targets": {rid: "1.1 - Requirements Detail"},
            # Stale early ids (what upload scrape might have stored)
            "new_headings": {
                "1": {
                    "id": "admissions-overview",
                    "full": "1 - Admissions Overview",
                    "text": "Admissions Overview",
                },
                "1.1": {
                    "id": "requirements-detail",
                    "full": "1.1 - Requirements Detail",
                    "text": "Requirements Detail",
                },
            },
            "auto_crosswalk": {"Chapter 1.1": "1.1 - Requirements Detail"},
        },
    )
    ids = _ids(body)
    assert ids["Admissions Overview"] == "permalink-admissions"
    assert ids["Requirements Detail"] == "permalink-requirements"
    links = _body_links(body)
    assert links, body
    assert links[0][0] == "#permalink-requirements"
    soup = BeautifulSoup(body, "html.parser")
    assert soup.find(id=links[0][0][1:]) is not None


def test_existing_anchor_href_updated_not_nested():
    html = (
        '<div class="manual">'
        "<h2 id='overview'>Overview</h2>"
        '<p>See <a href="#stale-id">Chapter 1.1</a> for details.</p>'
        "</div>"
    )
    rid = generate_stable_ref_id(0, 4, "Chapter 1.1")
    out = apply_reference_edits(
        html,
        edits={},
        references=[(0, "See Chapter 1.1 for details.", "Chapter 1.1", 4)],
        validations={rid: True},
        link_targets={rid: "Overview"},
        auto_crosswalk={"Chapter 1.1": "Overview"},
        new_headings={"1.1": {"id": "overview", "full": "Overview", "text": "Overview"}},
    )
    soup = BeautifulSoup(out, "html.parser")
    anchors = soup.find_all("a")
    assert len(anchors) == 1
    assert anchors[0]["href"] == "#overview"
    assert anchors[0].find("a") is None
