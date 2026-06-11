# Maintainer scripts

One-off command-line utilities that are useful when preparing a manual for conversion.
They are not part of the Flask app and are safe to run standalone.

| Script | Usage | Purpose |
|---|---|---|
| `extract_changes.py` | `python scripts/extract_changes.py <file.docx>` | Print every paragraph containing Word tracked changes, with insertions marked `[[NEW: …]]` and deletions marked `[[OLD: …]]`. Useful for reviewing a redlined manual without opening Word. |
| `read_manual.py` | `python scripts/read_manual.py <file.docx> <start_para> <end_para>` | Print a numbered range of paragraphs from a DOCX (0-based indexes). Useful for locating paragraph positions referenced by other tooling. |

Two earlier scripts (`apply_edits.py`, `apply_edits_v2.py`) were removed in June 2026:
they hardcoded paragraph indexes and edit text for one specific revision of the
2026-2027 GSPP manual, and their loose text matching could stamp edit markup onto the
wrong paragraphs if rerun against any other version. If that workflow is needed again,
write the edits against tracked changes (see `extract_changes.py`) rather than
paragraph positions.
