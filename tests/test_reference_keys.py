"""Re-attaching saved reference edits after the document has been edited.

Reference ids encode paragraph position, so inserting or deleting a paragraph
shifts every id below it and an operator's curated link targets and external URLs
silently stop applying.

Note on history: an earlier version of this module trusted an exact id match as
proof of identity, and this file asserted that behaviour. It was wrong — a
citation that moves into a slot another one vacated produces an exact match with
the wrong entry. The cases below now assert the group-based rule instead. See
tests/test_codex_review_findings.py for the reproduction that forced the change.
"""

from core.docx_processor import generate_stable_ref_id
from services.reference_keys import plan_reference_id_changes, remap_reference_edits


def _ref(para, start, label, text="body"):
    return (para, text, label, start, start + len(label), False)


def _rid(para, start, label):
    return generate_stable_ref_id(para, start, label)


def _edits(**by_id):
    return {"reference_external_urls": dict(by_id)}


def test_untouched_document_is_left_alone():
    refs = [_ref(10, 5, "Section IV.G.8")]
    data = _edits(**{_rid(10, 5, "Section IV.G.8"): "https://wsu.edu/a"})
    out, moved, dropped = remap_reference_edits(refs, data)
    assert (moved, dropped) == (0, 0)
    assert out is data, "an unchanged document should not be rewritten"


def test_a_shifted_citation_keeps_its_edits():
    """Three paragraphs inserted above: same citation, new id."""
    stored_id = _rid(10, 5, "Section IV.G.8")
    refs = [_ref(13, 5, "Section IV.G.8")]
    out, moved, dropped = remap_reference_edits(refs, _edits(**{stored_id: "https://wsu.edu/a"}))
    assert (moved, dropped) == (1, 0)
    assert out["reference_external_urls"] == {
        _rid(13, 5, "Section IV.G.8"): "https://wsu.edu/a"
    }


def test_repeated_labels_keep_their_order():
    """Two copies of a label must not swap URLs when both move."""
    first, second = _rid(10, 5, "Section IV.G.8"), _rid(40, 9, "Section IV.G.8")
    refs = [_ref(12, 5, "Section IV.G.8"), _ref(42, 9, "Section IV.G.8")]
    out, moved, _dropped = remap_reference_edits(
        refs, _edits(**{first: "https://first", second: "https://second"})
    )
    assert moved == 2
    urls = out["reference_external_urls"]
    assert urls[_rid(12, 5, "Section IV.G.8")] == "https://first"
    assert urls[_rid(42, 9, "Section IV.G.8")] == "https://second"


def test_every_edit_dictionary_is_remapped_together():
    stored_id = _rid(10, 5, "Section III.C")
    refs = [_ref(11, 5, "Section III.C")]
    data = {
        "reference_edits": {stored_id: "Section III.C"},
        "reference_validations": {stored_id: True},
        "reference_link_targets": {stored_id: "Section III.C - Workload"},
        "reference_ignored": {},
        "reference_external_urls": {stored_id: "https://wsu.edu/x"},
        "document": "manual.docx",
    }
    out, moved, _dropped = remap_reference_edits(refs, data)
    new_id = _rid(11, 5, "Section III.C")
    assert moved == 4
    for key in ("reference_edits", "reference_validations",
                "reference_link_targets", "reference_external_urls"):
        assert list(out[key]) == [new_id], key
    assert out["document"] == "manual.docx", "unrelated keys must survive"


def test_a_changed_citation_count_is_refused_not_guessed():
    """Which copy was removed is unknowable from positional ids."""
    a, b = _rid(10, 5, "Section IV.G.8"), _rid(40, 5, "Section IV.G.8")
    refs = [_ref(12, 5, "Section IV.G.8")]
    remap, ambiguous = plan_reference_id_changes(refs, _edits(**{a: "https://a", b: "https://b"}))
    assert remap == {}
    assert ambiguous == {a, b}


def test_an_exact_id_match_is_not_trusted_on_its_own():
    """The regression: a moved citation landing on a stale id looked like a match."""
    kept = _rid(10, 5, "Section IV.G.8")
    orphan = _rid(99, 5, "Section IV.G.8")
    refs = [_ref(10, 5, "Section IV.G.8")]
    remap, ambiguous = plan_reference_id_changes(
        refs, _edits(**{kept: "https://keep", orphan: "https://other"})
    )
    assert remap == {}
    assert ambiguous == {kept, orphan}, "two saved entries, one citation — both are suspect"


def test_trusted_same_document_keeps_partial_repeated_label_edits(caplog):
    """A bundle may store decisions for only some copies of a repeated label.

    When the bundle hash proves the DOCX is unchanged, exact ids still present in
    the current extraction are safe to keep. Comparing saved decisions against
    total citations for the label incorrectly parked real work from GSPP:
    three reviewed Chapter 12.7.8 cites among nine total looked ambiguous even
    though the document had not changed.
    """
    saved = _rid(30, 5, "Section IV.G.8")
    refs = [
        _ref(10, 5, "Section IV.G.8"),
        _ref(20, 5, "Section IV.G.8"),
        _ref(30, 5, "Section IV.G.8"),
    ]
    data = _edits(**{saved: "https://wsu.edu/a"})
    out, moved, dropped = remap_reference_edits(refs, data, trust_exact_ids=True)
    assert (moved, dropped) == (0, 0)
    assert out is data
    assert "dropping those edits" not in caplog.text


def test_a_different_label_is_never_matched():
    """The label hash is the anchor — a moved citation must keep its identity."""
    stored_id = _rid(10, 5, "Section IV.G.8")
    refs = [_ref(12, 5, "Section III.D.5")]
    remap, ambiguous = plan_reference_id_changes(refs, _edits(**{stored_id: "https://a"}))
    assert remap == {}
    assert ambiguous == {stored_id}


def test_malformed_ids_are_ignored():
    refs = [_ref(10, 5, "Section IV.G.8")]
    out, moved, dropped = remap_reference_edits(refs, _edits(**{"not-a-ref-id": "https://a"}))
    assert (moved, dropped) == (0, 0)
    assert out["reference_external_urls"] == {"not-a-ref-id": "https://a"}


def test_empty_inputs_are_safe():
    assert remap_reference_edits([], {"reference_edits": {}}) == ({"reference_edits": {}}, 0, 0)
    assert remap_reference_edits(None, None) == (None, 0, 0)
