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
