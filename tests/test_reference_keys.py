"""Re-attaching saved reference edits after the document has been edited.

Reference ids encode paragraph position, so inserting or deleting a paragraph
shifts every id below it and an operator's curated link targets and external
URLs silently stop applying. Restoring 25 hand-curated URLs to the WSU Faculty
Manual needed paragraph-text matching for exactly this reason.
"""

from core.docx_processor import generate_stable_ref_id
from services.reference_keys import build_reference_id_remap, remap_reference_edits


def _ref(para, start, label, text="body"):
    return (para, text, label, start, start + len(label), False)


def _rid(para, start, label):
    return generate_stable_ref_id(para, start, label)


def _edits(**by_id):
    return {"reference_external_urls": dict(by_id)}


def test_untouched_document_is_left_alone():
    refs = [_ref(10, 5, "Section IV.G.8")]
    data = _edits(**{_rid(10, 5, "Section IV.G.8"): "https://wsu.edu/a"})
    out, moved = remap_reference_edits(refs, data)
    assert moved == 0
    assert out is data, "an unchanged document should not be rewritten"


def test_a_shifted_citation_keeps_its_edits():
    """Three paragraphs inserted above: same citation, new id."""
    stored_id = _rid(10, 5, "Section IV.G.8")
    refs = [_ref(13, 5, "Section IV.G.8")]
    out, moved = remap_reference_edits(refs, _edits(**{stored_id: "https://wsu.edu/a"}))
    assert moved == 1
    assert out["reference_external_urls"] == {
        _rid(13, 5, "Section IV.G.8"): "https://wsu.edu/a"
    }


def test_repeated_labels_are_paired_in_document_order():
    """Two copies of a label must not swap their URLs when both move."""
    first, second = _rid(10, 5, "Section IV.G.8"), _rid(40, 9, "Section IV.G.8")
    refs = [_ref(12, 5, "Section IV.G.8"), _ref(42, 9, "Section IV.G.8")]
    out, moved = remap_reference_edits(
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
    out, moved = remap_reference_edits(refs, data)
    new_id = _rid(11, 5, "Section III.C")
    assert moved == 4
    for key in ("reference_edits", "reference_validations",
                "reference_link_targets", "reference_external_urls"):
        assert list(out[key]) == [new_id], key
    assert out["document"] == "manual.docx", "unrelated keys must survive"


def test_a_deleted_citation_does_not_inherit_a_neighbours_edits():
    """Two stored entries, one surviving citation — only one may match."""
    a, b = _rid(10, 5, "Section IV.G.8"), _rid(40, 5, "Section IV.G.8")
    refs = [_ref(12, 5, "Section IV.G.8")]
    remap = build_reference_id_remap(refs, _edits(**{a: "https://a", b: "https://b"}))
    assert len(remap) == 1
    assert remap[a] == _rid(12, 5, "Section IV.G.8"), "earliest stored pairs with earliest current"
    assert b not in remap


def test_a_different_label_is_never_matched():
    """The label hash is the anchor — a moved citation must keep its identity."""
    stored_id = _rid(10, 5, "Section IV.G.8")
    refs = [_ref(12, 5, "Section III.D.5")]
    assert build_reference_id_remap(refs, _edits(**{stored_id: "https://a"})) == {}


def test_exactly_matching_ids_are_not_stolen_by_an_orphan():
    """A citation already claimed by an exact match is not reassigned."""
    exact = _rid(10, 5, "Section IV.G.8")
    orphan = _rid(99, 5, "Section IV.G.8")
    refs = [_ref(10, 5, "Section IV.G.8")]
    remap = build_reference_id_remap(refs, _edits(**{exact: "https://keep", orphan: "https://other"}))
    assert remap == {}, "the only current citation is already matched exactly"


def test_malformed_ids_are_ignored():
    refs = [_ref(10, 5, "Section IV.G.8")]
    out, moved = remap_reference_edits(refs, _edits(**{"not-a-ref-id": "https://a"}))
    assert moved == 0


def test_empty_inputs_are_safe():
    assert remap_reference_edits([], {"reference_edits": {}}) == ({"reference_edits": {}}, 0)
    assert remap_reference_edits(None, None) == (None, 0)
