from core.html_processor import build_manual_grid_block


def test_build_manual_grid_injects_server_toc_when_provided():
    toc = '<ul class="toc-list" aria-labelledby="toc-heading"><li><a href="#a">X</a></li></ul>'
    out = build_manual_grid_block(
        "<p>Body</p>",
        2,
        "chapter",
        "css-counters",
        toc_html=toc,
    )
    assert "toc-list" in out
    assert "Body</p>" in out
    assert "skip-to-main" in out


def test_build_manual_grid_empty_ul_when_no_toc_html():
    out = build_manual_grid_block("<p>Body</p>", 2, "chapter", "css-counters")
    assert 'aria-live="polite"></ul>' in out
    assert "toc-list" not in out
