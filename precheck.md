# DOCX Precheck Before Upload

Use this runbook before uploading a Word manual into the Flask app. It relies on
the app's existing parsing and conversion helpers, so there is no need to rescan
the repo first.

## Scope

This precheck is read-only for the source DOCX. It writes only temporary files
inside Python's temporary directory, then removes them automatically.

If the DOCX is outside the workspace, request approval for a read-only command
because the sandbox cannot read Desktop/Downloads paths by default.

## Quick Command

From the repo root, set `DOCX_PATH` and run:

```powershell
$env:DOCX_PATH = "C:\path\to\manual.docx"
@'
from pathlib import Path
import json
import tempfile
import uuid
import zipfile
from collections import Counter

from bs4 import BeautifulSoup
from docx import Document

from config import PANDOC_PINNED_VERSION
from core.docx_processor import (
    count_tracked_changes,
    detect_manual_type_from_docx,
    extract_docx_hyperlinks,
    extract_heading_structure_and_references,
    extract_style_map_from_reference,
    fix_numbering_xml,
    has_tables_in_docx,
    preprocess_docx,
    relocate_body_level_bookmarks,
    sanitize_docx_styles,
)
from core.html_processor import (
    add_heading_ids,
    apply_css_counter_numbering,
    describe_tables,
    extract_body,
    normalize_spaces,
    normalize_typed_lists,
    process_html_pipeline,
    sanitize_docx_ids_for_export,
    strip_heading_numbers_dom,
    strip_images_and_figures,
    strip_pandoc_styles,
    strip_toc_sections_dom,
)
from core.manual_structure import (
    auto_match_old_to_new_references,
    scrape_heading_structure_from_html,
)
from core.pandoc_wrapper import (
    check_min_version,
    get_pandoc_version,
    run_pandoc,
    run_pandoc_html_to_docx,
)

src = Path(__import__("os").environ["DOCX_PATH"])
print(f"path={src}")
print(f"exists={src.exists()}")
if not src.exists():
    raise SystemExit("DOCX not found")
print(f"size_bytes={src.stat().st_size}")
print(f"zip_ok={zipfile.is_zipfile(src)}")

pandoc_version = get_pandoc_version()
print(f"pandoc_version={pandoc_version or 'missing'}")
print(f"pandoc_meets_pin={check_min_version(pandoc_version, PANDOC_PINNED_VERSION)}")
print(f"pandoc_pin={PANDOC_PINNED_VERSION}")

tracked = count_tracked_changes(src)
print(f"tracked_changes={tracked}")

doc = Document(src)
paragraphs = [p.text for p in doc.paragraphs]
nonempty = [p.strip() for p in paragraphs if p.strip()]
heading_map, references = extract_heading_structure_and_references(doc)
links = extract_docx_hyperlinks(doc)
style_map, sequence_map = extract_style_map_from_reference(src)

print(f"paragraphs={len(paragraphs)}")
print(f"nonempty_paragraphs={len(nonempty)}")
print(f"tables={len(doc.tables)}")
print(f"has_tables={has_tables_in_docx(src)}")
print(f"detected_manual_type={detect_manual_type_from_docx(doc)}")
print(f"heading_count={len(heading_map)}")
print(f"reference_count={len(references)}")
print(f"docx_hyperlink_paragraphs={len(links)}")
print(f"docx_hyperlinks={sum(len(v) for v in links.values())}")
print(f"bad_docx_hyperlinks={sum(1 for rows in links.values() for v in rows if v.get('bad'))}")
print("style_map=" + json.dumps(style_map, ensure_ascii=False, default=str))
print("sequence_map=" + json.dumps({"|".join(k): v for k, v in sequence_map.items()}, ensure_ascii=False))
print("top_references=" + json.dumps(Counter(r[2] for r in references).most_common(20), ensure_ascii=False))

with tempfile.TemporaryDirectory(prefix="docx_upload_precheck_") as td:
    td = Path(td)
    pre = td / "source.pre.docx"
    raw_html = td / "source.temp.html"
    docx_html = td / "docx_source.html"
    roundtrip_docx = td / "roundtrip.docx"

    old_headings, old_crosswalk, refs, manual_type = preprocess_docx(src, pre, {}, {})
    run_pandoc(pre, raw_html)
    raw = raw_html.read_text(encoding="utf-8", errors="ignore")

    normalized = strip_pandoc_styles(normalize_spaces(raw))
    normalized = strip_images_and_figures(normalized)
    normalized = normalize_typed_lists(f'<div class="manual">{extract_body(normalized)}</div>')
    normalized = strip_toc_sections_dom(normalized)
    stripped, _ = strip_heading_numbers_dom(normalized)
    numbered = add_heading_ids(apply_css_counter_numbering(stripped, manual_type, preserve=False))
    new_headings = scrape_heading_structure_from_html(numbered)
    auto_crosswalk = auto_match_old_to_new_references(refs, new_headings, manual_type=manual_type)

    final_html, toc_html = process_html_pipeline(raw, str(uuid.uuid4()), {
        "toc_depth": 2,
        "mapping_mode": "map_new",
        "preserve_numbers": False,
        "infer_heading_depth": False,
        "infer_style_map": {},
        "stable_heading_map": {},
        "heading_edits": {},
        "table_align_mode": "auto",
        "table_col1_align": None,
        "table_col2_align": None,
        "table_col3_align": None,
        "table_coln_align": None,
        "table_header_align": None,
        "table_headers": {},
        "table_aligns": {},
        "table_blocks": {},
        "references": refs,
        "reference_edits": {},
        "reference_validations": {},
        "reference_link_targets": {},
        "reference_ignored": {},
        "reference_external_urls": {},
        "auto_crosswalk": auto_crosswalk,
        "new_headings": new_headings,
        "skip_linked_text": False,
        "rebuild_links": False,
    })

    soup = BeautifulSoup(final_html, "html.parser")
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    anchors = soup.find_all("a", href=True)
    bad_hrefs = [
        a.get("href") for a in anchors
        if (a.get("href") or "").lower().startswith(("javascript:", "data:", "vbscript:", "file:"))
    ]
    unmatched = [r for r in refs if r[2] not in auto_crosswalk]

    roundtrip_ok = True
    roundtrip_error = ""
    try:
        numbered_docx_html = apply_css_counter_numbering(final_html, manual_type, preserve=False)
        numbered_docx_html = sanitize_docx_ids_for_export(numbered_docx_html)
        docx_html.write_text(f"<!doctype html><html><body>{numbered_docx_html}</body></html>", encoding="utf-8")
        run_pandoc_html_to_docx(docx_html, roundtrip_docx)
        fix_numbering_xml(roundtrip_docx)
        sanitize_docx_styles(roundtrip_docx)
        relocate_body_level_bookmarks(roundtrip_docx)
    except Exception as exc:
        roundtrip_ok = False
        roundtrip_error = str(exc)

    print(f"dry_manual_type={manual_type}")
    print(f"dry_old_heading_count={len(old_headings)}")
    print(f"dry_new_heading_count={len(new_headings)}")
    print(f"dry_final_heading_count={len(headings)}")
    print(f"dry_reference_count={len(refs)}")
    print(f"dry_auto_crosswalk_matches={len(auto_crosswalk)}")
    print(f"dry_unmatched_reference_instances={len(unmatched)}")
    print("dry_unmatched_unique=" + json.dumps(Counter(r[2] for r in unmatched).most_common(), ensure_ascii=False))
    print(f"dry_tables={len(soup.find_all('table'))}")
    print(f"dry_anchors={len(anchors)}")
    print(f"dry_bad_final_hrefs={len(bad_hrefs)}")
    print(f"dry_roundtrip_docx_ok={roundtrip_ok}")
    if roundtrip_error:
        print(f"dry_roundtrip_docx_error={roundtrip_error[:300]}")

    print("dry_first_headings=")
    for h in headings[:12]:
        print(f"{h.name}#{h.get('id', '')} :: {h.get_text(' ', strip=True)}")

    print("dry_table_descriptions=")
    for table in describe_tables(raw_html):
        slim = {
            "index": table["index"],
            "columns": table["columns"],
            "row_count": table["row_count"],
            "has_header": table["has_header"],
            "looks_like_title_row": table["looks_like_title_row"],
            "head_cells": table["head_cells"],
            "first_body_cells": table["first_body_cells"],
        }
        print(json.dumps(slim, ensure_ascii=False))
'@ | python -
```

## Pass Criteria

- `exists=True`, `zip_ok=True`.
- `pandoc_version` is present and `pandoc_meets_pin=True`.
- `tracked_changes=0`. If greater than zero, open the DOCX in Word, accept or
  reject all tracked changes, save, then run the precheck again.
- `heading_count`, `dry_new_heading_count`, and `dry_final_heading_count` are
  nonzero and roughly agree.
- `dry_bad_final_hrefs=0`.
- `dry_roundtrip_docx_ok=True`. If false, HTML export may still work, but the
  app's DOCX download will likely fail.

## Upload Guidance

- Use the detected manual type unless the result is clearly wrong.
- If `tables` or `dry_tables` is greater than zero, check **Open table review
  before export** in the app.
- Any `dry_table_descriptions` entry with `looks_like_title_row=True` should be
  reviewed in Table Review; the first row may be a table title rather than a
  column-header row.
- `dry_unmatched_unique` is not automatically fatal. Review those citations in
  the app: choose an internal heading, add an external URL, or mark the cite as
  skipped.
- If `style_map={}` and `sequence_map={}`, do not use the source style-map
  inference option unless you intentionally add a Converter Style Map section to
  the DOCX.

## Notes

- The precheck uses the default upload behavior: Auto manual type, Map to new
  numbering, TOC depth 2, no preserved heading numbers, and no heading map.
- Existing heading-map continuity still needs to be checked during upload by
  supplying the previous `.heading-map.json`.
- Raw Word XML can contain tags whose names start with `<w:ins` inside styles;
  rely on `tracked_changes`, which scans the document, footnote, and endnote
  revision parts used by the app's upload guard.
