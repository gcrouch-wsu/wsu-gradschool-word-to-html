from core.permalinks import normalize_heading_signature


def test_normalize_heading_signature_collapses_nbsp_like_space():
    a = normalize_heading_signature("Chapter\u00a0One Title")
    b = normalize_heading_signature("Chapter One Title")
    assert a == b
