"""Pin the crosswalk logic (core/manual_structure.py): old->new numbering
conversion, auto-matching of references, and heading scraping. This is the
machinery that decides whether permalinks survive a re-conversion.
"""
import pytest

from core.manual_structure import (
    auto_match_old_to_new_references,
    convert_old_numbering_to_new,
    scrape_heading_structure_from_html,
)


@pytest.mark.parametrize(
    "old,new",
    [
        # README-documented conversions
        ("Chapter 1.D.4", "Chapter 1.4.4"),
        ("Section I.A.2.b", "Section 1.1.2.2"),
        ("Chapter One", "Chapter 1"),
        # Mixed alphanumeric without dots
        ("Chapter 1D", "Chapter 1.4"),
        # Already numeric: unchanged
        ("Chapter 5", "Chapter 5"),
        ("Section 1.4.8", "Section 1.4.8"),
    ],
)
def test_convert_old_numbering_to_new(old, new):
    assert convert_old_numbering_to_new(old) == new


def test_convert_leaves_non_references_alone():
    assert convert_old_numbering_to_new("see also") == "see also"


def _ref(text):
    """References are 6-tuples; only index 2 (the reference string) matters here."""
    return (0, 0, text, "", "", "")


def test_auto_match_prefers_existing_heading():
    new_structure = {
        "Chapter 1.4": {
            "text": "Graduate Faculty",
            "full": "Chapter 1.4 - Graduate Faculty",
            "level": "h2",
            "id": "graduate-faculty",
            "order": 1,
        },
    }
    crosswalk = auto_match_old_to_new_references(
        [_ref("Chapter 1.D")], new_structure, manual_type="chapter"
    )
    assert crosswalk == {"Chapter 1.D": "Chapter 1.4"}


def test_auto_match_predicts_when_no_heading_matches():
    crosswalk = auto_match_old_to_new_references(
        [_ref("Chapter 2.D.2.d")], {}, manual_type="chapter"
    )
    assert crosswalk == {"Chapter 2.D.2.d": "Chapter 2.4.2.4"}


def test_auto_match_skips_unreasonably_high_numbers():
    crosswalk = auto_match_old_to_new_references(
        [_ref("Chapter 99.A")], {}, manual_type="chapter"
    )
    assert "Chapter 99.A" not in crosswalk


def test_auto_match_skips_non_references():
    crosswalk = auto_match_old_to_new_references(
        [_ref("the following table")], {}, manual_type="chapter"
    )
    assert crosswalk == {}


def test_scrape_heading_structure_builds_hierarchical_keys():
    html = (
        '<div class="manual">'
        '<h1 id="ch1">Chapter 1 - Administration</h1>'
        '<h2 id="gov">1.1 Governance</h2>'
        "</div>"
    )
    scraped = scrape_heading_structure_from_html(html)
    assert scraped["Chapter 1"] == {
        "text": "Administration",
        "full": "Chapter 1 - Administration",
        "level": "h1",
        "id": "ch1",
        "order": 0,
    }
    assert scraped["Chapter 1.1"]["text"] == "Governance"
    assert scraped["Chapter 1.1"]["id"] == "gov"
