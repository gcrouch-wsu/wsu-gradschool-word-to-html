from core.html_processor import sanitize_manual_html_fragment


def test_sanitize_strips_script():
    raw = '<p onclick="evil()">Hi</p><script>alert(1)</script><a href="javascript:x">x</a>'
    out = sanitize_manual_html_fragment(raw)
    assert "<script" not in out.lower()
    assert "onclick" not in out.lower()
    assert "javascript:" not in out.lower()
