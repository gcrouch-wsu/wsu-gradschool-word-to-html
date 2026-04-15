"""Regression tests for bundle-import HTML rebuild (preserve_numbers vs strip)."""

from word_to_wordpressV4 import _bundle_import_post_pandoc_pipeline


def test_bundle_pipeline_preserve_true_differs_from_strip():
    html = '<div class="manual"><h1>Section I.A Introduction</h1></div>'
    manifest_strip = {
        "preserve_numbers": False,
        "mapping_mode": "map_new",
        "infer_heading_depth": False,
    }
    manifest_preserve = {
        "preserve_numbers": True,
        "mapping_mode": "map_new",
        "infer_heading_depth": False,
    }
    out_strip = _bundle_import_post_pandoc_pipeline(html, manifest_strip, "chapter")
    out_preserve = _bundle_import_post_pandoc_pipeline(html, manifest_preserve, "chapter")
    assert out_strip != out_preserve


def test_bundle_pipeline_keep_old_matches_preserve_for_strip_skip():
    """keep_old forces preserve semantics so numeric prefixes are not stripped before CSS pass."""
    html = '<div class="manual"><h1>Chapter 1 Example</h1></div>'
    out_keep = _bundle_import_post_pandoc_pipeline(
        html,
        {"mapping_mode": "keep_old", "preserve_numbers": False, "infer_heading_depth": False},
        "chapter",
    )
    out_preserve = _bundle_import_post_pandoc_pipeline(
        html,
        {"mapping_mode": "map_new", "preserve_numbers": True, "infer_heading_depth": False},
        "chapter",
    )
    assert out_keep == out_preserve


def test_bundle_pipeline_infer_branch_runs_when_flag_set():
    manifest = {
        "mapping_mode": "map_new",
        "infer_heading_depth": True,
        "infer_style_map": {},
        "preserve_numbers": False,
    }
    html = '<div class="manual"><h1>Test</h1></div>'
    out = _bundle_import_post_pandoc_pipeline(html, manifest, "chapter")
    assert "<h1" in out
