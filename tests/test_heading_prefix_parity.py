"""Pin the three _HEADING_PREFIX_RE copies so they can't drift apart.

core/html_processor and core/docx_processor must behave identically, including
spelled-out Chapter/Section words ("Chapter One"). The config generator's copy
additionally matches bare letter prefixes ("A Title") but must agree on
everything else, including all separators.
"""
import random

import pytest

from core.html_processor import _HEADING_PREFIX_RE as HP
from core.docx_processor import _HEADING_PREFIX_RE as DP
import docx_config_generator as g

GEN = g._HEADING_PREFIX_RE

SEPARATOR_CASES = [
    "Chapter 2. Title",
    "Chapter 2 - Title",
    "Chapter 2 – Title",   # en dash
    "Chapter 2 — Title",   # em dash
    "Chapter 2: Title",
    "Chapter 2 Title",
    "Section I.A. Duties",
    "I.A.3. Duties",
]

SPELLED_OUT_CASES = [
    "Chapter One Title",
    "Chapter Two: Title",
    "Chapter Three – Title",
    "Section One Title",
]


def _m(rx, s):
    m = rx.match(s)
    return m.group(0) if m else None


@pytest.mark.parametrize("text", SEPARATOR_CASES)
def test_html_and_docx_prefix_regex_agree(text):
    assert _m(HP, text) == _m(DP, text), text


@pytest.mark.parametrize("text", SEPARATOR_CASES)
def test_generator_agrees_on_documented_separators(text):
    assert _m(GEN, text) == _m(HP, text), text


@pytest.mark.parametrize("text", SPELLED_OUT_CASES)
def test_all_three_copies_match_spelled_out_chapter_section_words(text):
    assert _m(HP, text) is not None, text
    assert _m(HP, text) == _m(DP, text) == _m(GEN, text), text


def test_spelled_out_words_without_chapter_or_section_do_not_match():
    assert _m(HP, "One Title") is None
    assert _m(DP, "One Title") is None


def test_pipeline_copies_do_not_strip_bare_letter_prefixes():
    """Generator may match 'A Title'; html/docx processors require 'A. Title'."""
    assert _m(HP, "A Title") is None
    assert _m(DP, "A Title") is None
    assert _m(GEN, "A Title") == "A "
    dotted = _m(HP, "A. Title")
    assert dotted == "A. "
    assert dotted == _m(DP, "A. Title") == _m(GEN, "A. Title")


def test_html_and_docx_are_behaviorally_identical_under_fuzzing():
    rng = random.Random(1234)
    toks = ["Chapter", "Section", "1", "2", "12", "I", "II", "XIV", "A", "AA",
            "a", "b", "3", ".", "-", "–", "—", ":", ")", " ", "Title",
            "One", "Two", "Twenty"]
    for _ in range(5000):
        s = "".join(rng.choice(toks) for _ in range(rng.randint(1, 6)))
        assert _m(HP, s) == _m(DP, s), repr(s)
