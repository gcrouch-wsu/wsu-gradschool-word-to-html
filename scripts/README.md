# Maintainer scripts

One-off command-line utilities that are useful when preparing a manual for conversion.
They are not part of the Flask app and are safe to run standalone.

| Script | Usage | Purpose |
|---|---|---|
| `extract_changes.py` | `python scripts/extract_changes.py <file.docx>` | Print every paragraph containing Word tracked changes, with insertions marked `[[NEW: …]]` and deletions marked `[[OLD: …]]`. Useful for reviewing a redlined manual without opening Word. |
| `read_manual.py` | `python scripts/read_manual.py <file.docx> <start_para> <end_para>` | Print a numbered range of paragraphs from a DOCX (0-based indexes). Useful for locating paragraph positions referenced by other tooling. |
| `make_password_hash.py` | `python scripts/make_password_hash.py` | Print a scrypt password hash for `AUTH_USERS` (see main `README.md` Authentication). |
