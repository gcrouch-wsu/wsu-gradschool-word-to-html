"""Re-attach saved reference edits to a document that has since been edited.

Reference ids encode *where* a citation sits: ``ref_{paragraph}_{offset}_{hash}``,
where the hash covers the citation label. Insert or delete a paragraph anywhere
above a citation and every id below it shifts, so an operator's curated link
targets and external URLs stop matching and silently do nothing. This is not
hypothetical — restoring 25 hand-curated URLs to the WSU Faculty Manual needed
matching on paragraph text rather than the saved ids.

The id format is deliberately left alone: changing it would strand every
existing session bundle. Instead this module re-attaches stored keys to the
current document. The label hash is the stable part of an id, so entries are
grouped by label and matched to the current references for that same label in
document order — which is what a human does when they say "these are the same
three citations, they just moved down a page".

Only entries whose exact id is missing are remapped, so an untouched document is
unaffected.
"""
import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# The edits dictionaries that are keyed by reference id.
REFERENCE_EDIT_KEYS = (
    "reference_edits",
    "reference_validations",
    "reference_link_targets",
    "reference_ignored",
    "reference_external_urls",
)

_REF_ID_RE = re.compile(r"^ref_(\d+)_(\d+)_([0-9a-f]{8})$")


def _parse(ref_id: str):
    """(paragraph, offset, label_hash) for a well-formed id, else None."""
    match = _REF_ID_RE.match(str(ref_id or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3)


def build_reference_id_remap(references: list, edits_data: dict) -> dict[str, str]:
    """Map stored reference ids onto the ids this document produces now.

    Returns ``{stored_id: current_id}`` for entries that moved. Ids that still
    match a current reference are left alone and absent from the result.
    """
    from core.docx_processor import generate_stable_ref_id

    current = []
    for ref in references or []:
        para, label, start = ref[0], ref[2], ref[3]
        current.append((generate_stable_ref_id(para, start, label), para, start, label))
    current_ids = {rid for rid, _p, _s, _l in current}

    stored_ids = set()
    for key in REFERENCE_EDIT_KEYS:
        value = edits_data.get(key)
        if isinstance(value, dict):
            stored_ids.update(value.keys())

    orphans = [rid for rid in stored_ids if rid not in current_ids and _parse(rid)]
    if not orphans:
        return {}

    # Group both sides by label hash, in document order.
    current_by_hash = defaultdict(list)
    for rid, para, start, _label in sorted(current, key=lambda c: (c[1], c[2])):
        parsed = _parse(rid)
        if parsed:
            current_by_hash[parsed[2]].append(rid)
    # A current id that some stored entry already matches exactly is spoken for.
    for bucket in current_by_hash.values():
        bucket[:] = [rid for rid in bucket if rid not in stored_ids]

    orphans_by_hash = defaultdict(list)
    for rid in sorted(orphans, key=lambda r: (_parse(r)[0], _parse(r)[1])):
        orphans_by_hash[_parse(rid)[2]].append(rid)

    remap: dict[str, str] = {}
    for label_hash, stored in orphans_by_hash.items():
        available = current_by_hash.get(label_hash, [])
        # Pair them off in document order. Surplus on either side is left
        # unmapped rather than guessed at — a citation that genuinely went away
        # should lose its edits, not inherit a neighbour's.
        for stored_id, current_id in zip(stored, available):
            remap[stored_id] = current_id
        if len(stored) != len(available):
            logger.info(
                "Reference remap: %d stored entr(ies) and %d current reference(s) "
                "share label hash %s; %d matched.",
                len(stored), len(available), label_hash, min(len(stored), len(available)),
            )
    return remap


def remap_reference_edits(references: list, edits_data: dict) -> tuple[dict, int]:
    """Return a copy of ``edits_data`` with reference ids re-attached.

    The second element is how many entries moved, for reporting.
    """
    if not references or not isinstance(edits_data, dict):
        return edits_data, 0
    remap = build_reference_id_remap(references, edits_data)
    if not remap:
        return edits_data, 0

    updated = dict(edits_data)
    moved = 0
    for key in REFERENCE_EDIT_KEYS:
        original = edits_data.get(key)
        if not isinstance(original, dict):
            continue
        rebuilt = {}
        for stored_id, value in original.items():
            target = remap.get(stored_id, stored_id)
            if target != stored_id:
                moved += 1
            rebuilt[target] = value
        updated[key] = rebuilt

    logger.info(
        "Re-attached %d reference edit(s) to %d moved citation(s) after document changes.",
        moved, len(remap),
    )
    return updated, moved
