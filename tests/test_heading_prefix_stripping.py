"""Pin the DOM-aware heading-number stripper (core/html_processor.py).

These regexes are dense and have documented edge cases ("don't consume the
first letter of the heading text"); these tests pin the intended behavior so
refactors can't silently change it.
"""
import re

import pytest

from bs4 import BeautifulSoup

from core.html_processor import (
    _heading_slug_from_text,
    process_html_pipeline,
    strip_heading_numbers_dom,
)
from core.permalinks import normalize_heading_signature


def _heading_text(html_out: str) -> str:
    m = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html_out, re.DOTALL)
    assert m, f"no heading found in {html_out!r}"
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


@pytest.mark.parametrize(
    "html_in,expected_text,expected_prefix",
    [
        # Chapter/Section prefixes with the three dash variants and colon
        # (the recorded prefix keeps the trailing separator)
        ("<h1>Chapter 2 - Overview</h1>", "Overview", "Chapter 2 -"),
        ("<h1>Chapter 2 – Overview</h1>", "Overview", "Chapter 2 –"),  # en dash
        ("<h1>Chapter 2 — Overview</h1>", "Overview", "Chapter 2 —"),  # em dash
        ("<h1>Section I: Intro</h1>", "Intro", "Section I:"),
        # Multi-level typed prefixes
        ("<h2>I.A.3. Duties</h2>", "Duties", "I.A.3."),
        ("<h2>1.2.3 Requirements</h2>", "Requirements", "1.2.3"),
        ("<h3>A. Appeals</h3>", "Appeals", "A."),
        # Spelled-out Chapter/Section words (css-counters strip)
        ("<h1>Chapter One Title</h1>", "Title", "Chapter One"),
        ("<h1>Chapter Two: Title</h1>", "Title", "Chapter Two:"),
        ("<h1>Chapter Three – Title</h1>", "Title", "Chapter Three –"),
        ("<h1>Section One Title</h1>", "Title", "Section One"),
    ],
)
def test_prefix_is_stripped(html_in, expected_text, expected_prefix):
    out, old_map = strip_heading_numbers_dom(html_in)
    assert _heading_text(out) == expected_text
    assert list(old_map.values()) == [expected_prefix]


def test_prefix_without_trailing_space_is_not_consumed():
    """'I.A.3.Duties' must not be eaten as the prefix 'I.A.3.D'."""
    out, old_map = strip_heading_numbers_dom("<h2>I.A.3.Duties</h2>")
    assert _heading_text(out) == "I.A.3.Duties"
    assert old_map == {}


def test_prefix_wrapped_in_inline_tags_is_stripped():
    out, old_map = strip_heading_numbers_dom("<h2><strong>I.A.</strong> Duties</h2>")
    assert _heading_text(out) == "Duties"
    assert list(old_map.values()) == ["I.A."]


def test_unnumbered_heading_is_untouched():
    out, old_map = strip_heading_numbers_dom("<h2>Appendix</h2>")
    assert _heading_text(out) == "Appendix"
    assert old_map == {}


def test_headings_receive_ids():
    out, _ = strip_heading_numbers_dom("<h2>1.2 Title</h2>")
    assert re.search(r'<h2 id="[^"]+"', out)


def test_one_title_without_chapter_or_section_is_not_stripped():
    out, old_map = strip_heading_numbers_dom("<h1>One Title</h1>")
    assert _heading_text(out) == "One Title"
    assert old_map == {}


def test_bare_letter_prefix_is_not_stripped():
    out, old_map = strip_heading_numbers_dom("<h1>A Title</h1>")
    assert _heading_text(out) == "A Title"
    assert old_map == {}


def _pipeline_h1(html, **config):
    body, _ = process_html_pipeline(
        html,
        "00000000-0000-4000-8000-000000000001",
        {"toc_depth": 2, "infer_heading_depth": False, **config},
    )
    return BeautifulSoup(body, "html.parser").find("h1")


def test_pipeline_css_counters_strips_chapter_one():
    h = _pipeline_h1("<h1>Chapter One Introduction</h1>", preserve_numbers=False)
    assert h.get_text(strip=True) == "Introduction"
    assert h["id"] == "introduction"
    assert h["id"] == _heading_slug_from_text("Introduction")
    assert h["id"] != "chapter-one-introduction"
    assert normalize_heading_signature(h.get_text()) == "introduction"


def test_pipeline_css_counters_strips_section_one():
    h = _pipeline_h1("<h1>Section One Duties</h1>", preserve_numbers=False)
    assert h.get_text(strip=True) == "Duties"
    assert h["id"] == "duties"


def test_pipeline_preserve_with_inference_off_leaves_chapter_one():
    h = _pipeline_h1("<h1>Chapter One Introduction</h1>", preserve_numbers=True)
    assert h.get_text(strip=True) == "Chapter One Introduction"


def test_stable_map_keys_off_post_strip_signature():
    html = "<h1>Chapter One Introduction</h1>"
    post = normalize_heading_signature("Introduction")
    pre = normalize_heading_signature("Chapter One Introduction")
    assert post != pre

    h = _pipeline_h1(
        html,
        preserve_numbers=False,
        stable_heading_map={post: ["kept-intro-id"]},
    )
    assert h.get_text(strip=True) == "Introduction"
    assert h["id"] == "kept-intro-id"

    h_miss = _pipeline_h1(
        html,
        preserve_numbers=False,
        stable_heading_map={pre: ["old-chapter-one-id"]},
    )
    assert h_miss["id"] == "introduction"
