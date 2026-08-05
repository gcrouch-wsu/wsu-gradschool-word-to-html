"""Regressions for defects an independent review found in the 2026-08-05 fixes.

Each was reproduced before being fixed; the numbering matches that report.
"""

import pytest
from bs4 import BeautifulSoup

from core.docx_processor import generate_stable_ref_id as rid
from core.html_processor import (
    format_manual_tables,
    normalize_table_headers,
    process_html_pipeline,
)
from services.reference_keys import remap_reference_edits
from utils.url_policy import is_safe_href, normalize_external_href

LABEL = "Section IV.G.8"


def _ref(para, label=LABEL, start=5):
    return (para, "body text", label, start, start + len(label), False)


def _urls(**kw):
    return {"reference_external_urls": dict(kw)}


# --- 1. remapping must not hand a URL to the wrong citation ---------------

def test_deleting_one_of_several_identical_labels_drops_rather_than_guesses():
    """The surviving citation used to inherit the deleted one's URL, silently."""
    stored = _urls(**{
        rid(10, 5, LABEL): "URL-A",
        rid(20, 5, LABEL): "URL-B-deleted",
        rid(30, 5, LABEL): "URL-C",
    })
    out, moved, dropped = remap_reference_edits([_ref(10), _ref(20)], stored)
    assert dropped == 3 and moved == 0
    assert out["reference_external_urls"] == {}, "no citation may inherit another's URL"


def test_adding_a_citation_also_refuses_to_guess():
    stored = _urls(**{rid(10, 5, LABEL): "URL-A"})
    _out, moved, dropped = remap_reference_edits([_ref(10), _ref(40)], stored)
    assert (moved, dropped) == (0, 1)


def test_a_uniform_shift_still_re_attaches_in_order():
    """The common case — paragraphs inserted above — must keep working."""
    stored = _urls(**{
        rid(10, 5, LABEL): "URL-A",
        rid(20, 5, LABEL): "URL-B",
        rid(30, 5, LABEL): "URL-C",
    })
    out, moved, dropped = remap_reference_edits([_ref(13), _ref(23), _ref(33)], stored)
    assert (moved, dropped) == (3, 0)
    assert [out["reference_external_urls"][rid(p, 5, LABEL)] for p in (13, 23, 33)] == [
        "URL-A", "URL-B", "URL-C",
    ]


def test_an_unchanged_document_is_untouched():
    stored = _urls(**{rid(10, 5, LABEL): "URL-A"})
    out, moved, dropped = remap_reference_edits([_ref(10)], stored)
    assert (moved, dropped) == (0, 0)
    assert out is stored


def test_labels_are_handled_independently():
    """One ambiguous label must not discard a different label's edits."""
    other = "Section III.C"
    stored = _urls(**{
        rid(10, 5, LABEL): "A", rid(20, 5, LABEL): "B",
        rid(50, 5, other): "keep-me",
    })
    out, _moved, dropped = remap_reference_edits([_ref(10), _ref(53, other)], stored)
    assert dropped == 2
    assert out["reference_external_urls"] == {rid(53, 5, other): "keep-me"}


# --- 2/3. reference linking ----------------------------------------------

HEAD = (
    "<body><div class='manual'><h1>Section II: Discipline</h1>"
    "<h2>II.F. Corrective Action</h2><p>x</p>"
    "<h3>II.F.6. Temporary Reassignment</h3><p>y</p>"
)


def _run(body_html, references):
    validations = {rid(r[0], r[3], r[2]): True for r in references}
    config = {
        "toc_depth": 2, "preserve_numbers": True, "mapping_mode": "keep_old",
        "references": references, "reference_edits": {},
        "reference_validations": validations, "reference_link_targets": {},
        "reference_ignored": {}, "reference_external_urls": {},
        "auto_crosswalk": {r[2]: r[2] for r in references}, "new_headings": {},
    }
    body, _toc = process_html_pipeline(HEAD + body_html + "</div></body>", "s", config)
    return BeautifulSoup(body, "html.parser")


def test_an_authors_external_link_is_never_retargeted():
    """Split-anchor repair is for Word cross-references, not deliberate links."""
    para = "See Section II.F.6 now."
    soup = _run(
        "<p>See <a href='https://author.example/ref'>Section II.F</a>.6 now.</p>",
        [(3, para, "Section II.F.6", para.index("Section II.F.6"), 0, False)],
    )
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    assert "https://author.example/ref" in hrefs, hrefs


def test_a_word_cross_reference_is_still_repaired():
    para = "See Section II.F.6 now."
    soup = _run(
        "<p>See <a href='#iif-corrective-action'>Section II.F</a>.6 now.</p>",
        [(3, para, "Section II.F.6", para.index("Section II.F.6"), 0, False)],
    )
    assert [(a.get_text(), a["href"]) for a in soup.find_all("a", href=True)] == [
        ("Section II.F.6", "#iif6-temporary-reassignment")
    ]


@pytest.mark.parametrize("suffix", ["-1", "‑1a", "–1", "—1"])
def test_a_short_label_does_not_match_a_dash_joined_longer_one(suffix):
    para = f"See Section II.F{suffix} for the appendix."
    soup = _run(f"<p>{para}</p>", [(3, para, "Section II.F", para.index("Section II.F"), 0, False)])
    assert soup.find_all("a", href=True) == [], f"must not link inside Section II.F{suffix}"


@pytest.mark.parametrize("citation,text", [
    ("34.05.446", "review the factors in RCW 34.05.446(3) when deciding"),
    ("42.52.010", "an officer as defined in 42.52.010(11)."),
    ("42.52.150", "from a person prohibited by 42.52.150[4] from giving"),
])
def test_a_parenthetical_subsection_does_not_block_the_base_citation(citation, text):
    """Real Faculty Manual statute citations — the link belongs on the base.

    A review proposed treating "(" and "[" as label continuations so
    "Section II.F(1)" would not match "Section II.F". Applied literally that
    unlinked three curated, already-published citations, because RCW citations
    qualify subsections parenthetically. Constructed cases lose to real ones.
    """
    from core.html_processor import _ref_flexible_pattern
    assert _ref_flexible_pattern(citation).search(text)


def test_a_label_followed_by_a_spaced_dash_still_links():
    para = "See Section II.F — the appendix explains it."
    soup = _run(f"<p>{para}</p>", [(3, para, "Section II.F", para.index("Section II.F"), 0, False)])
    assert len(soup.find_all("a", href=True)) == 1


# --- 4. spanning header rows ---------------------------------------------

def test_a_data_row_under_a_spanning_title_is_not_promoted_to_header():
    table = (
        "<table><thead><tr><th colspan='2'>Eligibility Criteria</th></tr></thead>"
        "<tbody><tr><td>GPA</td><td>3.0</td></tr>"
        "<tr><td>Credits</td><td>72</td></tr></tbody></table>"
    )
    out = BeautifulSoup(normalize_table_headers(table), "html.parser")
    assert out.find("caption").get_text() == "Eligibility Criteria"
    assert out.find("thead") is None, "GPA / 3.0 is data, not a header row"


def test_a_header_row_containing_a_number_is_no_longer_misjudged():
    """The heuristic refused "Requirement | 1 | 2"; nothing guesses now."""
    table = (
        "<table><thead><tr><th colspan='3'>Scoring</th></tr></thead>"
        "<tbody><tr><td>Requirement</td><td>1</td><td>2</td></tr>"
        "<tr><td>Credits</td><td>12</td><td>24</td></tr></tbody></table>"
    )
    auto = BeautifulSoup(normalize_table_headers(table), "html.parser")
    assert auto.find("caption").get_text() == "Scoring"
    assert auto.find("thead") is None, "auto must not decide"
    chosen = BeautifulSoup(normalize_table_headers(table, {"0": "title_row"}), "html.parser")
    assert [c.get_text() for c in chosen.find("thead").find_all("th")] == ["Requirement", "1", "2"]


def test_a_person_row_is_no_longer_promoted_just_for_lacking_numbers():
    table = (
        "<table><thead><tr><th colspan='2'>Committee Membership</th></tr></thead>"
        "<tbody><tr><td>Avery Jones</td><td>Professor</td></tr></tbody></table>"
    )
    out = BeautifulSoup(normalize_table_headers(table), "html.parser")
    assert out.find("thead") is None, "a data row of names must not become headers"


def test_the_operator_can_promote_a_numeric_header_row():
    table = (
        "<table><thead><tr><th colspan='2'>Eligibility Criteria</th></tr></thead>"
        "<tbody><tr><td>GPA</td><td>3.0</td></tr></tbody></table>"
    )
    out = BeautifulSoup(normalize_table_headers(table, {"0": "title_row"}), "html.parser")
    assert [c.get_text() for c in out.find("thead").find_all("th")] == ["GPA", "3.0"]


# --- 5. colspan and column identity --------------------------------------

def test_alignment_keys_on_the_visual_column_not_the_cell_position():
    table = (
        "<table><tbody>"
        "<tr><td colspan='2'>Combined text</td><td>100</td></tr>"
        "<tr><td>Other</td><td>More notes</td><td>200</td></tr>"
        "</tbody></table>"
    )
    rows = []
    for tr in BeautifulSoup(format_manual_tables(table), "html.parser").find_all("tr"):
        rows.append([
            next(c.replace("manual-align-", "") for c in cell.get("class", [])
                 if c.startswith("manual-align-"))
            for cell in tr.find_all(["td", "th"])
        ])
    assert rows[1][1] == "left", "prose in column 2 must not inherit column 3's centring"
    assert rows[0][1] == "center" and rows[1][2] == "center", "the numeric column is centred"


# --- 6. deceptive URL authorities ----------------------------------------

@pytest.mark.parametrize("value", [
    "https://facsen.wsu.edu@evil.example/manual",
    "http://wsu.edu@evil.example/x",
    "//facsen.wsu.edu@evil.example/x",
    "https://рolicies.wsu.edu/x",
])
def test_misleading_authorities_are_refused(value):
    assert normalize_external_href(value) == ""


@pytest.mark.parametrize("value", [
    "https://policies.wsu.edu/prf/bppm-10-65",
    "http://wsu.edu/x",
    "policies.wsu.edu/x",
    "wsu.edu:8080/a?b=1#c",
])
def test_ordinary_urls_are_unaffected(value):
    out = normalize_external_href(value)
    assert out and is_safe_href(out)
