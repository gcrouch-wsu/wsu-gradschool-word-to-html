import pytest

from utils.url_policy import is_safe_href, sanitize_external_href


@pytest.mark.parametrize(
    "href,expected",
    [
        ("https://example.com/path?q=1", True),
        ("http://localhost/", True),
        ("mailto:a@b.co", True),
        ("#section", True),
        ("", False),
        ("javascript:alert(1)", False),
        ("data:text/html,<x>", False),
        ("vbscript:x", False),
    ],
)
def test_is_safe_href(href, expected):
    assert is_safe_href(href) is expected


def test_sanitize_external_href_blocks_javascript():
    assert sanitize_external_href("javascript:void(0)") == ""


# --- colour values reach a generated stylesheet, so they must be real hex ---

def test_a_non_hex_colour_is_rejected_not_passed_through():
    """"a;}x{y" is six characters, which the old length-only check accepted.

    Theme colours are interpolated into the generated <style> block, so the
    value closed the declaration and opened a rule of its own — reachable from a
    crafted session bundle, whose theme settings flow into the CSS download that
    gets pasted site-wide.
    """
    from utils.helpers import normalize_hex_color

    assert normalize_hex_color("a;}x{y") == "#000000"
    assert normalize_hex_color("#ZZZZZZ") == "#000000"
    assert normalize_hex_color("#12345") == "#000000"


def test_real_hex_values_still_work():
    from utils.helpers import normalize_hex_color

    assert normalize_hex_color("#a1b2c3") == "#A1B2C3"
    assert normalize_hex_color("#ABC") == "#AABBCC"
    assert normalize_hex_color("  #a1b2c3  ") == "#A1B2C3"


def test_the_generated_stylesheet_cannot_be_broken_out_of():
    """Checked at the render point too — meta and manifest bypass coercion."""
    from core.styling import build_theme_css, coerce_theme_settings

    settings, _ = coerce_theme_settings(
        {"primary_color": "a;}x{y", "link_color": "#ZZZZZZ"}, "chapter"
    )
    assert "A;}X{Y" not in build_theme_css(settings)
    # ...and with coercion skipped entirely, as a stored theme dict does
    raw = {"primary_color": "a;}x{y", "link_color": "q;}z{", "font_family": "sans-serif"}
    css = build_theme_css(raw)
    assert "A;}X{Y" not in css and "Q;}Z{" not in css
