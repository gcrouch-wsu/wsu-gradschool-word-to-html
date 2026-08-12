import re
from pathlib import Path


CSS = (Path(__file__).resolve().parent.parent / "wordpress.css").read_text(encoding="utf-8")


def _rule_body(selector: str) -> str:
    pattern = re.compile(r"(?m)^" + re.escape(selector) + r"\s*\{(?P<body>.*?)\}", re.DOTALL)
    match = pattern.search(CSS)
    assert match, f"{selector} rule is missing"
    return match.group("body")


def test_manual_links_have_a_single_css_underline():
    body = _rule_body(".manual a")
    assert "text-decoration: none !important" in body
    assert "border-bottom: 1px solid #A60F2D !important" in body


def test_word_underlines_inside_manual_links_are_neutralized():
    body = _rule_body(".manual a u")
    assert "text-decoration: none !important" in body
