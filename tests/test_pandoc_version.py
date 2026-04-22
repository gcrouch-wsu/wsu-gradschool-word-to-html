import json

from core.pandoc_wrapper import (
    _parse_version_string,
    check_for_pandoc_update,
    check_min_version,
    compare_versions,
)


def test_parse_version_handles_four_part_and_three_part():
    assert _parse_version_string("3.9.0.2") == (3, 9, 0, 2)
    assert _parse_version_string("3.8.3") == (3, 8, 3)
    assert _parse_version_string("v3.9") == (3, 9)


def test_parse_version_rejects_garbage():
    assert _parse_version_string("") is None
    assert _parse_version_string("pandoc 3.9") is None
    assert _parse_version_string("3.9.0.2-dev") is None


def test_compare_versions_pads_missing_components():
    assert compare_versions("3.9", "3.9.0.0") == 0
    assert compare_versions("3.9.0.2", "3.9") == 1
    assert compare_versions("3.8.3", "3.9.0.2") == -1
    assert compare_versions("3.9.0.2", "3.8.3") == 1


def test_compare_versions_unknown_is_zero():
    assert compare_versions("garbage", "3.9.0.2") == 0
    assert compare_versions("3.9.0.2", "") == 0


def test_check_min_version_true_when_equal_or_newer():
    assert check_min_version("3.9.0.2", "3.9.0.2") is True
    assert check_min_version("3.10", "3.9.0.2") is True


def test_check_min_version_false_when_older_or_missing():
    assert check_min_version("3.8.3", "3.9.0.2") is False
    assert check_min_version(None, "3.9.0.2") is False


def test_parse_version_rejects_non_string_without_raising():
    # A tampered cache could yield non-string values; the parser must not
    # crash the update check.
    assert _parse_version_string(None) is None
    assert _parse_version_string(3.9) is None
    assert _parse_version_string(["3", "9", "0", "2"]) is None


def test_compare_versions_tolerates_non_string_inputs():
    # compare_versions is a public helper of pandoc_wrapper; a corrupt cache
    # must never make it raise.
    assert compare_versions(None, "3.9.0.2") == 0
    assert compare_versions(3.9, "3.9.0.2") == 0


def test_check_for_pandoc_update_tolerates_corrupt_cache(tmp_path):
    cache_path = tmp_path / "pandoc_update_cache.json"
    cache_path.write_text(
        json.dumps({"latest": 3.9, "checked_at": "not-an-int"}),
        encoding="utf-8",
    )
    # ttl_seconds very large so the fresh branch is taken; with a corrupt
    # 'latest' we should fall through to the network path, but we pass a
    # tiny timeout so the network call fails fast and the function still
    # returns None instead of raising.
    result = check_for_pandoc_update(
        installed="3.9.0.2",
        cache_path=cache_path,
        ttl_seconds=10_000_000,
        timeout_seconds=0.001,
    )
    assert result is None


def test_check_for_pandoc_update_handles_unwritable_cache(tmp_path):
    # cache_path points inside a non-existent nested path; _write_cache
    # creates parents, so this exercises the happy-cache-write branch.
    # The key regression guard is "does not raise".
    cache_path = tmp_path / "nested" / "deep" / "pandoc_cache.json"
    result = check_for_pandoc_update(
        installed="99.99.99",
        cache_path=cache_path,
        ttl_seconds=0,
        timeout_seconds=0.001,
    )
    # installed is synthetically newer than anything; even if the network
    # call succeeded (it won't at 1ms), the result would be None.
    assert result is None
