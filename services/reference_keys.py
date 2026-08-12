"""Re-attach saved reference edits to a document that has since been edited.

Reference ids encode *where* a citation sits: ``ref_{paragraph}_{offset}_{hash}``,
where the hash covers the citation label. Insert or delete a paragraph anywhere
above a citation and every id below it shifts, so an operator's curated link
targets and external URLs stop matching and silently do nothing.

**A matching id is not proof of identity.** Because ids are positional, a
citation that moves into the slot another one vacated produces an exact match
with the wrong entry. Deleting the middle of three identical labels made the
surviving third citation inherit the deleted one's URL — silently, and the review
page then saved it. So exact matches are not trusted on their own.

Instead, each label is handled as a group:

* the same number of stored entries and current citations — the group shifted as
  a unit, so pair them in document order (this covers both "nothing moved" and
  "everything moved down three paragraphs");
* a different number — a citation was added or removed, and *which* one is not
  recoverable from positional ids. Any pairing would be a guess, so the group's
  edits are dropped and reported for the operator to redo.

Ambiguous entries are *parked*, not deleted: they move to
``reference_orphaned`` where nothing applies them, and the operator is told. An
earlier version discarded them outright and the review page saved that
immediately — correct in output, but it destroyed curated work with no undo on a
judgement the code was not entitled to make alone.
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

# Where ambiguous entries are parked. Nothing reads this when applying edits.
ORPHAN_KEY = "reference_orphaned"

_REF_ID_RE = re.compile(r"^ref_(\d+)_(\d+)_([0-9a-f]{8})$")


def _parse(ref_id: str):
    """(paragraph, offset, label_hash) for a well-formed id, else None."""
    match = _REF_ID_RE.match(str(ref_id or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3)


def plan_reference_id_changes(references: list, edits_data: dict, *, trust_exact_ids: bool = False):
    """Work out how stored reference ids map onto this document.

    Returns ``(remap, ambiguous_ids)``:

    * ``remap`` — ``{stored_id: current_id}`` for entries that moved.
    * ``ambiguous_ids`` — stored ids whose label gained or lost a citation, so no
      trustworthy pairing exists. Their edits must be discarded, not guessed.

    When ``trust_exact_ids`` is true, exact stored ids that still exist in the
    current document are kept even if the same label appears elsewhere. Use this
    only when an outer boundary proves the document is unchanged (for example, a
    session-bundle doc hash matching the imported DOCX). Without that proof, an
    edited document can move one identical citation into another one's old
    positional id.
    """
    from core.docx_processor import generate_stable_ref_id

    current_by_hash: dict[str, list[str]] = defaultdict(list)
    for ref in sorted(references or [], key=lambda r: (r[0], r[3])):
        para, label, start = ref[0], ref[2], ref[3]
        rid = generate_stable_ref_id(para, start, label)
        parsed = _parse(rid)
        if parsed:
            current_by_hash[parsed[2]].append(rid)

    stored_ids = set()
    for key in REFERENCE_EDIT_KEYS:
        value = edits_data.get(key)
        if isinstance(value, dict):
            stored_ids.update(value.keys())

    stored_by_hash: dict[str, list[str]] = defaultdict(list)
    for rid in sorted(
        (r for r in stored_ids if _parse(r)),
        key=lambda r: (_parse(r)[0], _parse(r)[1]),
    ):
        stored_by_hash[_parse(rid)[2]].append(rid)

    remap: dict[str, str] = {}
    ambiguous: set[str] = set()
    for label_hash, stored in stored_by_hash.items():
        current = current_by_hash.get(label_hash, [])
        if trust_exact_ids:
            current_set = set(current)
            exact = {rid for rid in stored if rid in current_set}
            stored_to_pair = [rid for rid in stored if rid not in exact]
            current_to_pair = [rid for rid in current if rid not in exact]
        else:
            stored_to_pair = stored
            current_to_pair = current

        if not stored_to_pair:
            continue

        if len(stored_to_pair) == len(current_to_pair):
            # The group is intact; document order is a trustworthy pairing.
            for stored_id, current_id in zip(stored_to_pair, current_to_pair):
                if stored_id != current_id:
                    remap[stored_id] = current_id
            continue
        # A citation with this label was added or removed. Positional ids cannot
        # say which, and an exact id match here would be coincidence, so refuse.
        ambiguous.update(stored_to_pair)
        logger.warning(
            "Reference remap: label hash %s has %d saved entr(ies) but %d citation(s) "
            "in the document now; dropping those edits rather than guessing which "
            "citation each belongs to.",
            label_hash, len(stored_to_pair), len(current_to_pair),
        )
    return remap, ambiguous


def remap_reference_edits(
    references: list,
    edits_data: dict,
    *,
    trust_exact_ids: bool = False,
) -> tuple[dict, int, int]:
    """Return ``(edits, moved, dropped)`` with reference ids re-attached.

    ``moved`` counts entries that followed their citation to a new id.
    ``dropped`` counts entries discarded because their label became ambiguous.
    """
    if not references or not isinstance(edits_data, dict):
        return edits_data, 0, 0
    remap, ambiguous = plan_reference_id_changes(
        references, edits_data, trust_exact_ids=trust_exact_ids
    )
    if not remap and not ambiguous:
        return edits_data, 0, 0

    updated = dict(edits_data)
    parked = dict(edits_data.get(ORPHAN_KEY) or {})
    moved = dropped = 0
    for key in REFERENCE_EDIT_KEYS:
        original = edits_data.get(key)
        if not isinstance(original, dict):
            continue
        rebuilt = {}
        for stored_id, value in original.items():
            if stored_id in ambiguous:
                # Keep it, out of the way, so the operator can recover it.
                parked.setdefault(stored_id, {})[key] = value
                dropped += 1
                continue
            target = remap.get(stored_id, stored_id)
            if target != stored_id:
                moved += 1
            rebuilt[target] = value
        updated[key] = rebuilt
    if parked:
        updated[ORPHAN_KEY] = parked

    logger.info(
        "Reference edits after document changes: %d re-attached, %d parked as ambiguous.",
        moved, dropped,
    )
    return updated, moved, dropped
