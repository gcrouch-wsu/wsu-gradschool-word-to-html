"""Round-trip: exported-style manual container is discoverable."""

from core.html_processor import extract_manual_fragment


def test_extract_manual_prefers_main_manual_in_grid():
    html = (
        '<div class="manual-grid" data-manual-type="chapter" data-toc-depth="2">'
        '<nav class="manual-toc"></nav>'
        '<main class="manual" id="main-content"><p>BodyInside</p></main>'
        "</div>"
    )
    frag, meta = extract_manual_fragment(html)
    assert "BodyInside" in frag
    assert meta.get("manual_type") == "chapter"
