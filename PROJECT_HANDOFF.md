# Project Handoff — Word-to-WordPress Conversion Suite

> **Single source of truth.** Read this before touching any code.
> **Last updated:** 2026-04-07 (Session 3)

---

## 1. Hard Limitations — Do Not Attempt to Fix

These are confirmed external-tool or platform limitations. Multiple sessions have established they cannot be solved from this codebase.

### 1.1 Pandoc `--reference-doc` Produces Corrupt DOCX Files

**Workaround in use:** DOCX export uses plain Pandoc with no `--reference-doc`. Users get generic Word styling but a valid file.

### 1.2 WordPress Theme List Markers Cannot Be Overridden

**Workaround in use:** `wordpress.js` calls `forceListStyles()` as a post-load correction at multiple timeouts. This causes visible list rendering flicker. Do not attempt to "fix" it by removing the timeouts; the flicker is the least-bad option.

---

## 2. Current State (Post-Repair — 2026-04-07)

**Active app:** `word_to_wordpressV4.py` (monolithic Flask script)
**Companion app:** `docx_config_generator.py` (~2,600 lines, second Flask script)
**Original V4 backup:** `C:\Python Projects\originalWord_HTML\Word_HTMLV4\word_to_wordpressV4.py` (8,772 lines — source of truth for function bodies)

### Modular Structure

Gemini moved code into `core/` modules. The directory structure is correct; function bodies were incomplete. Claude restored function bodies from the original V4 during two repair sessions (2026-04-06 and 2026-04-07).

```
core/
├── permalinks.py          ← SPELLED_NUMS, normalize_heading_signature, normalize_heading_ref, ensure_prefixed
├── html_processor.py      ← add_heading_ids (Hybrid Rule), parse_heading_id_map_json (3-shape), process_html_pipeline, build_manual_grid_block, format_manual_tables (with WCAG scope attrs)
├── manual_structure.py    ← scrape_heading_structure_from_html, build_heading_crosswalk_from_map, convert_old_numbering_to_new, roman_to_int, auto_match_old_to_new_references, lookup_heading_title, heading sort helpers
├── reference_linking.py   ← extract_references_from_html (6-tuple, searches p/li/td/blockquote/dt/dd), extract_external_links_from_html, extract_external_links_from_reference_text
├── docx_processor.py      ← DOCX preprocessing, numbering extraction, style map, heading inference, Pandoc post-processing
├── styling.py             ← get_wp_css_text, get_wp_js_text, build_theme_css, default_theme_settings, contrast_ratio
├── pandoc_wrapper.py      ← Pandoc invocation
└── __init__.py
```

### What Works

- DOCX upload → heading review → reference review → table review → export
- HTML import + reference review
- Heading map JSON upload (file picker or paste) for stable IDs
- DOCX export with internal/external links preserved (plain Pandoc)
- Table review and table alignment controls (checkbox must be ticked on upload form)
- Reference review modes: keep original / map new numeric
- Seven download options after conversion: Standalone, Fragment, Fragment + CSS, DOCX, CSS, JS, Heading Map, Session Bundle
- Browser auto-launches on app start
- WCAG 2.1 AA accessibility: skip link, ARIA landmarks, table scope attributes, aria-live TOC filtering, focus indicators, reduced-motion support
- WordPress search input JS fallback (recreates `<input>` stripped by Custom HTML blocks)

### What Was Fixed (2026-04-06 — Claude Session 1)

| Fix | Location |
|---|---|
| `get_wp_css_text`/`get_wp_js_text` not imported | V4 import block |
| Double `session_id` in convert route | V4 line ~967 deleted |
| `heading_edits` NameError in do_convert | Added from session_data |
| 3-tuple vs 6-tuple in extract_references_from_html | Rewrote to 6-tuple format |
| `find_heading_by_full` returned bare values, callers expected 2-tuple | Fixed returns |
| POL prefix appearing in UI | Fixed ensure_prefixed, build_heading_crosswalk_from_map |

### What Was Fixed (2026-04-07 — Claude Session 2)

| Fix | Location |
|---|---|
| `parse_heading_id_map_json` only handled flat dict | Restored 3-shape parser (structured, list, flat) from V4 |
| `add_heading_ids` / `_add_heading_ids_impl` incomplete | Restored full Hybrid Rule from V4 with `overwrite_existing=True` default |
| `convert_old_numbering_to_new` was a stub | Restored full Roman/letter conversion from V4 |
| `roman_to_int` missing | Added from V4 |
| `build_heading_crosswalk_from_map` used fabricated CH./POL. prefixes | Replaced with V4 version using `ensure_prefixed` + `convert_old_numbering_to_new` |
| `lookup_heading_title` was a trivial stub | Restored multi-candidate normalized lookup from V4 |
| `scrape_heading_structure_from_html` returned wrong dict shape | Replaced with V4 version producing `{text, full, level, id, order}` |
| `parse_heading_key` / `heading_sort_key` / `heading_dropdown_sort` stripped CH./POL. | Replaced with V4 versions (Roman-aware, order-first sort) |
| `find_heading_by_full` didn't handle nbsp or `full`/`text` fields | Replaced with V4 version |
| Empty "Link target" dropdown on review page | Caused by wrong dict shape from scrape function — fixed above |
| No heading map file upload on home page | Added file input to DOCX form and HTML import form |
| "Proceed with Conversion" → 405 Method Not Allowed | Route was POST-only; redirect is GET. Changed to `methods=["GET"]` matching V4 |
| Table review never triggered | `edit_tables` re-read from POST form (always False). Now reads from session_data |
| Missing download buttons (DOCX, CSS, JS) | Added all 6 buttons to export actions bar |
| `wordpress.js` was older stripped version | Replaced with original V4 (960 lines, WCAG accessible, full TOC with expand/collapse) |
| No "Fragment + CSS" download option | Added `fragment_css` kind with embedded `<style>` + `<script>` blocks |

### What Was Fixed (2026-04-07 — Claude Session 3)

| Fix | Location |
|---|---|
| `build_manual_grid_block` missing entirely (NameError at export) | Added to `core/html_processor.py` with WCAG accessibility (tabindex, aria-live, skip link) |
| `extract_references_from_html` only searched `<p>` tags | Restored V1 version: searches p/li/td/blockquote/dt/dd, broader regex, NavigableString position tracking |
| `auto_match_old_to_new_references` was 7-line stub | Restored V1 version: candidate generation, numbering conversion, Chapter/Section swaps, validation (~100 lines) |
| `extract_external_links_from_html` returned wrong shape | Restored V1 version: returns `{block_idx: [url, ...]}` matching how V4.py consumes it |
| `extract_external_links_from_reference_text` was simplified | Restored V1 version: finds URLs embedded in paragraph text |
| Tables missing `scope` attributes (WCAG 1.3.1) | `format_manual_tables` now adds `scope="col"` or `scope="row"` to all `<th>` elements |
| No `aria-live` on TOC list (WCAG 4.1.3) | Added `aria-live="polite"` to TOC `<ul>` in both HTML template and JS |
| Search input focus outline inconsistent (WCAG 2.4.7) | Changed `outline-offset: 0` to `2px` in `wordpress.css` |
| `_HEADING_PREFIX_RE` FutureWarning in docx_processor.py | Fixed ambiguous `[:.\---]` character classes to `[:.\\-\u2013\u2014]` |
| FM WordPress search not showing | JS fallback added to FM.js/GSPP.js/wordpress.js — creates `<input>` if WordPress stripped it |

### Known Issues (Low Priority)

| Issue | Impact | Status |
|---|---|---|
| Session stores absolute file paths | Paths break if temp dir is cleaned mid-session | Aspirational: store relative to session dir. Only affects interrupted sessions. |
| BeautifulSoup re-parsed 15+ times per request | 3–8 sec overhead on large docs | Aspirational: `_impl` pattern is in place for future single-pass refactor. Not blocking. |
| `export_session` is POST but could be GET | Minor REST convention | Leaving as POST — prevents browser prefetch of large ZIPs. |
| ~~`_HEADING_PREFIX_RE` FutureWarning~~ | ~~Cosmetic~~ | **Fixed** in Session 3 |
| ~~ZIP path traversal uses `startswith`~~ | ~~Negligible~~ | **Already fixed** — code appends `os.sep` |

---

## 3. Primary Workflow & Permalink Stability

The app supports a repeating edit cycle where **permalinks must remain stable across document versions**:

```
1. Edit in Word → Upload to app (with heading map if available) → Export HTML + DOCX
2. (months later) Edit the DOCX export → Upload to app with previous heading map → Export new version
3. Repeat indefinitely
```

### How Permalink Stability Works

| System | What It Tracks | Purpose |
|---|---|---|
| **Stable Heading Map** | Heading signature → Anchor ID | Preserves permalinks (`#chapter-one---administration-of-graduate-programs`) |
| **Crosswalk** | OLD ref number → NEW ref number | Updates link *text* ("Section I.A.2" → "Section I.A.3") |

The heading map keys by **content signature** (normalized heading text), not by reference number. When I.A.2 becomes I.A.3, the signature still matches → same anchor ID → old links work.

### The Hybrid Rule (Restored — Working)

`add_heading_ids` in `core/html_processor.py` implements the three-branch priority chain:

1. **Keep existing ID** — Only when `overwrite_existing=False` (opt-in). Default is True, giving stable_map authority.
2. **Match signature against stable map** — Normalize heading text via `normalize_heading_signature`, look up in loaded map. If found, use the stored ID.
3. **Generate slug** — Slugify text, deduplicate within document.

### Heading Map JSON Schema (v1 — In Production)

```json
{
  "version": 1,
  "source": "GSPP.HTML",
  "entries": [
    {
      "id": "chapter-one---administration-of-graduate-programs",
      "signature": "chapter one  administration of graduate programs",
      "last_seen_heading": "Chapter One - Administration of Graduate Programs",
      "last_seen_level": 2
    }
  ]
}
```

`parse_heading_id_map_json` accepts three shapes: structured `{entries: [...]}`, bare list `[{...}]`, flat dict `{"sig": "id"}`.

### Reference Number Conversion

`convert_old_numbering_to_new` handles Roman/letter → numeric conversion:
- `Chapter 1.D.4` → `Chapter 1.4.4`
- `Section I.A.2.b` → `Section 1.1.2.2`
- `Chapter One` → `Chapter 1` (via SPELLED_NUMS)

First-level Roman numerals are treated as Roman; sub-level single letters are treated as ordinals (A=1, B=2).

---

## 4. Key Files

| File | Status | Role |
|---|---|---|
| `word_to_wordpressV4.py` | Active | Main Flask app — routes, templates, orchestration |
| `core/permalinks.py` | Restored from V4 | Heading normalization, ensure_prefixed, SPELLED_NUMS |
| `core/html_processor.py` | Restored from V4 | Hybrid Rule, heading map parser, HTML pipeline |
| `core/manual_structure.py` | Restored from V4 | Heading scraping, crosswalk, numbering conversion, sort |
| `core/reference_linking.py` | Restored from V4 | 6-tuple reference extraction |
| `core/styling.py` | Verified | CSS/JS text loaders, theme builder, contrast ratio |
| `core/docx_processor.py` | Verified (Session 3) | DOCX preprocessing, numbering, style map — 52 functions, no stubs |
| `core/pandoc_wrapper.py` | Working | Pandoc invocation |
| `docx_config_generator.py` | Active | Companion config generator app |
| `wordpress.css` | Identical to V4 | WordPress styles — WCAG 2.1 AA |
| `wordpress.js` | Replaced with V4 | WordPress scripts — TOC, scrollspy, copy-link, list normalization |
| `config.py` | Working | SessionDir helper, PERSIST_DIR |
| `*.heading-map.json` | Input artifacts | v1-schema heading maps from original V4 |

### Original V4 Backup Location

`C:\Python Projects\originalWord_HTML\Word_HTMLV4\word_to_wordpressV4.py`

This is the authoritative source for any function body that is uncertain. V3 was never complete — Gemini overwrote V4 with V3 content. Always reference V4.

---

## 5. Remaining Work

### Priority 1: All core modules audited — COMPLETE

All `core/` modules have been verified against the original V4. No remaining stubs or missing function bodies. `table_processor.py` does not exist as a separate file — table formatting is handled by `format_manual_tables` in `html_processor.py`.

### Priority 2: Future improvements (aspirational, not blocking)

- **Session relative paths:** Store file paths relative to session root instead of absolute. Medium effort (~15-20 spots in V4.py). Only matters if temp dir is cleaned mid-session.
- **Single-pass BeautifulSoup pipeline:** The `_impl` functions already support operating on a shared soup object. Switching V4.py call sites from string wrappers to `_impl` chains would eliminate 15+ re-parses. Medium effort, high regression risk.
- **Variable renaming:** `heading_map` is used for three distinct concepts (numbering-title map, stable ID map, crosswalk upload). Confusing but functional.
- Move templates from `render_template_string` to Jinja2 `.html` files
- Split routes into separate files
- Session cleanup on startup
- Progress indicator during Pandoc conversion

---

## 6. How to Reset Saved State

- Delete `%TEMP%\docx2html_wsumanual\{session_id}\` to clear one session.
- Delete `%TEMP%\docx2html_wsumanual\` entirely to reset all sessions.

---

## 7. History

- **V4 original:** 8,772-line monolithic Flask app — fully working
- **Gemini refactor:** Moved code to `core/` modules but left stubs instead of real function bodies. Overwrote V4 with V3 content.
- **Claude Session 1 (2026-04-06):** Audited Gemini's work, found 10+ defects, fixed crash-level issues
- **Claude Session 2 (2026-04-07):** Restored all heading map pipeline functions from original V4, fixed empty dropdown, route method, table review, download links, replaced JS
- **Claude Session 3 (2026-04-07):** Restored reference/crosswalk pipeline from V1, added missing `build_manual_grid_block`, WCAG 2.1 AA accessibility fixes (table scope, aria-live, focus outline), fixed regex FutureWarning, verified all core modules — no remaining stubs
