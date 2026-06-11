"""Pin the three _HEADING_PREFIX_RE copies so they can't drift apart.

core/html_processor and core/docx_processor must behave identically; the config
generator's copy additionally matches spelled-out chapter words ("Chapter One")
but must agree on everything else, including all separators.
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


def _m(rx, s):
    m = rx.match(s)
    return m.group(0) if m else None


@pytest.mark.parametrize("text", SEPARATOR_CASES)
def test_html_and_docx_prefix_regex_agree(text):
    assert _m(HP, text) == _m(DP, text), text


@pytest.mark.parametrize("text", SEPARATOR_CASES)
def test_generator_agrees_on_documented_separators(text):
    assert _m(GEN, text) == _m(HP, text), text


def test_generator_extends_with_spelled_out_chapter_words():
    # The one intentional difference: the generator strips "Chapter One".
    assert _m(GEN, "Chapter One Title") == "Chapter One "
    assert _m(HP, "Chapter One Title") is None


def test_html_and_docx_are_behaviorally_identical_under_fuzzing():
    rng = random.Random(1234)
    toks = ["Chapter", "Section", "1", "2", "12", "I", "II", "XIV", "A", "AA",
            "a", "b", "3", ".", "-", "–", "—", ":", ")", " ", "Title"]
    for _ in range(5000):
        s = "".join(rng.choice(toks) for _ in range(rng.randint(1, 6)))
        assert _m(HP, s) == _m(DP, s), repr(s)
