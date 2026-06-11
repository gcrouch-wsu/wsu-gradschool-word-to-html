"""Pin the DOM-aware heading-number stripper (core/html_processor.py).

These regexes are dense and have documented edge cases ("don't consume the
first letter of the heading text"); these tests pin the intended behavior so
refactors can't silently change it.
"""
import re

import pytest

from core.html_processor import strip_heading_numbers_dom


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
