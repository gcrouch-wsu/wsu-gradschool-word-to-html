"""Regression tests for duplicate-heading stable-map handling.

A flat {signature: id} map dropped all but the last id for headings sharing
normalized text, which made re-applying the regenerated map non-idempotent
(ids drifting overview -> overview-1 -> overview-1-1 on every reconversion).
The map now stores {signature: [ids in document order]}.
"""
import json

from bs4 import BeautifulSoup

from core.html_processor import (
    add_heading_ids,
    parse_heading_id_map_json,
    normalize_heading_signature,
)

DUP = '<div class="manual"><h2>Overview</h2><h2>Overview</h2><h2>Unique</h2></div>'


def _ids(html):
    return [h.get("id") for h in BeautifulSoup(html, "html.parser").find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6"])]


def _build_map(html):
    """Mirror save_stable_heading_map's signature -> [ids] construction."""
    soup = BeautifulSoup(html, "html.parser")
    m = {}
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        hid = (h.get("id") or "").strip()
        if hid:
            m.setdefault(normalize_heading_signature(h.get_text().strip()), []).append(hid)
    return m


def test_duplicate_headings_are_idempotent_across_reruns():
    run1 = add_heading_ids(DUP, stable_map={})
    ids1 = _ids(run1)
    assert ids1 == ["overview", "overview-1", "unique"]

    run2 = add_heading_ids(DUP, stable_map=_build_map(run1))
    run3 = add_heading_ids(DUP, stable_map=_build_map(run2))
    assert _ids(run2) == ids1, "re-applying the regenerated map must be idempotent"
    assert _ids(run3) == ids1, "and stable on further reruns"


def test_saved_map_keeps_every_duplicate_id():
    m = _build_map(add_heading_ids(DUP, stable_map={}))
    assert m["overview"] == ["overview", "overview-1"], "both duplicate ids retained"
    assert m["unique"] == ["unique"]


def test_legacy_flat_map_is_still_accepted():
    """Old {signature: "id"} maps parse into the list form and apply cleanly."""
    parsed = parse_heading_id_map_json(json.dumps({"overview": "overview", "unique": "unique"}))
    assert parsed == {"overview": ["overview"], "unique": ["unique"]}
    out = add_heading_ids(DUP, stable_map=parsed)
    # First Overview keeps the mapped id; the second (beyond the recorded list)
    # gets a fresh distinct slug instead of crashing or colliding.
    ids = _ids(out)
    assert ids[0] == "overview"
    assert ids[1] != ids[0]
    assert ids[2] == "unique"


def test_list_format_round_trips_through_parser():
    m = _build_map(add_heading_ids(DUP, stable_map={}))
    assert parse_heading_id_map_json(json.dumps(m)) == m
