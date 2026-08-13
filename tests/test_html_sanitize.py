from bs4 import BeautifulSoup

from core.html_processor import build_manual_grid_block, sanitize_manual_html_fragment


def test_sanitize_strips_script():
    raw = '<p onclick="evil()">Hi</p><script>alert(1)</script><a href="javascript:x">x</a>'
    out = sanitize_manual_html_fragment(raw)
    assert "<script" not in out.lower()
    assert "onclick" not in out.lower()
    assert "javascript:" not in out.lower()


def test_sanitize_returns_fragment_without_parser_wrappers(monkeypatch):
    import core.html_processor as html_processor

    monkeypatch.setattr(html_processor, "bleach", None)
    out = html_processor.sanitize_manual_html_fragment("<p>Body</p>")
    assert "<html" not in out.lower()
    assert "<body" not in out.lower()
    assert out == "<p>Body</p>"


def test_sanitize_unwraps_underlines_inside_links():
    out = sanitize_manual_html_fragment('<p><a href="https://wsu.edu"><u>WSU</u></a></p>')
    assert "<u>" not in out.lower()
    assert '<a href="https://wsu.edu">WSU</a>' in out


def test_sanitize_unwraps_underlines_around_links():
    out = sanitize_manual_html_fragment('<p><u><a href="https://wsu.edu">WSU</a></u></p>')
    assert "<u>" not in out.lower()
    assert '<a href="https://wsu.edu">WSU</a>' in out


def test_sanitize_preserves_manual_search_controls():
    out = sanitize_manual_html_fragment(
        '<nav class="manual-toc"><div class="manual-search">'
        '<input type="text" class="manual-search-input" placeholder="Search headings and content..." '
        'aria-label="Search table of contents" aria-describedby="search-help" role="searchbox">'
        '<button type="button" class="manual-search-clear" aria-label="Clear search">X</button>'
        '</div></nav>'
    )
    soup = BeautifulSoup(out, "html.parser")

    search = soup.select_one(".manual-search")
    assert search is not None
    assert search.select_one("input.manual-search-input[role='searchbox']") is not None
    clear = search.select_one("button.manual-search-clear")
    assert clear is not None
    assert clear.get_text(strip=True) == "X"


def test_sanitize_strips_unsafe_control_attributes():
    out = sanitize_manual_html_fragment(
        '<input class="manual-search-input" type="text" name="q" value="secret" onclick="evil()">'
        '<button class="manual-search-clear" type="button" onclick="evil()" data-x="1">X</button>'
    )
    assert "onclick" not in out.lower()
    assert "name=" not in out.lower()
    assert "value=" not in out.lower()
    assert "data-x" not in out.lower()


def test_manual_grid_block_does_not_nest_document_tags():
    out = build_manual_grid_block(
        "<html><body><h1>Chapter 1</h1><p>Body</p></body></html>",
        toc_depth=2,
        manual_type="chapter",
        numbering_mode="preserve",
    )
    soup = BeautifulSoup(out, "html.parser")
    main = soup.find("main", class_="manual")
    assert main is not None
    assert main.find("html") is None
    assert main.find("body") is None
    assert main.find("h1").get_text(strip=True) == "Chapter 1"
