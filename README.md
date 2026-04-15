# Word-to-WordPress Conversion App

A Flask web application that converts Word documents (DOCX) into WordPress-ready HTML for publishing university policy manuals. Built for Washington State University's administrative manuals (Faculty Manual, GSPP, etc.).

Current build and deployment status is tracked in `PROJECT_HANDOFF.md` (including **External re-audit checklist** for second-pass / Gemini reviews). This README describes the intended workflow and local usage, but it should not be treated as the release-readiness source of truth.

For **implementation order**, locked scope, acceptance gates, and the phased build plan, follow **`PROJECT_HANDOFF.md`** — start with the section **How to use this document as a build guide**, then **Build Decisions For This Build** and **Build Plan**.

## Features

- **DOCX to HTML conversion** via Pandoc with custom post-processing pipeline
- **WordPress-ready output** — generates HTML fragments, CSS, and JS for WordPress deployment
- **Permalink stability** — heading map JSON preserves anchor IDs across editing cycles, so WordPress URLs survive document revisions
- **WCAG 2.1 AA accessible** — skip navigation, ARIA landmarks, table scope attributes, keyboard-navigable TOC; the accessible **manual grid shell** (skip link, `nav`, search, `main`) is built in **one place** — `core/html_processor.py` → **`build_manual_grid_block`** (server TOC in preview when applicable; downloads use an empty TOC placeholder filled by **`wordpress.js`**)
- **Intended round-trip editing workflow** — exports a clean DOCX for the next Word editing cycle and supports heading-map-based permalink continuity, with current gaps tracked in `PROJECT_HANDOFF.md`
- **Searchable TOC** — JavaScript-powered table of contents with live search, scrollspy, and keyboard navigation
- **Reference crosswalk** — converts legacy heading references (Roman numerals, letters) to numeric format
- **Local-first runtime with a Railway/Docker deployment path** — see `PROJECT_HANDOFF.md` for production checklists, residual gaps, and CSRF/ZIP/session hardening status

---

## Setup & Usage

### Prerequisites

- **Python 3.12+** recommended (matches Docker and reliable `lxml` wheels on Windows); **3.10+** may work if dependencies install cleanly
- **Pandoc** — required for DOCX-to-HTML and HTML-to-DOCX conversion

### Install Pandoc

Download from https://pandoc.org/installing.html and ensure `pandoc` is on your PATH. The app checks for Pandoc at startup and will not run without it.

Verify:
```bash
pandoc --version
```

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

That installs Flask, Flask-WTF (CSRF), Bleach, python-docx, BeautifulSoup, lxml, Werkzeug, Markdown, Gunicorn, and pytest. On **Windows**, use **Python 3.12 or 3.13** if `lxml` fails to build on very new interpreters (prebuilt wheels lag).

> `lxml` is optional at runtime in some setups—BeautifulSoup can fall back to `html.parser`—but `requirements.txt` includes lxml for speed and consistency with CI/Docker.

### Automated tests

```bash
python -m pytest tests/ -q
```

Optional warning filters for test output live in **`pytest.ini`** (e.g. Bleach CSS sanitizer notices).

## Running the App

### Main Conversion App

```bash
python word_to_wordpressV4.py
```

Opens automatically at http://127.0.0.1:5000. If the browser doesn't launch, navigate there manually.

### Companion Config Generator

```bash
python docx_config_generator.py
```

This companion tool is local-only in the current project scope. See `README_config_generator.md` for usage details, and `PROJECT_HANDOFF.md` for deployment scope.

## Conversion Workflow

### First-Time Conversion (no heading map)

1. Upload your DOCX file
2. Configure settings: manual type (Chapter/Section), TOC depth, numbering mode
3. Optionally check "Edit tables" to review table formatting
4. Click Upload and process through the review screens (headings, references, tables)
5. Click "Proceed with Conversion"
6. Download your outputs:
   - **Standalone HTML** — full page with embedded CSS/JS, for local preview
   - **Fragment** — HTML body only, for pasting into WordPress Custom HTML block
   - **Fragment + CSS** — fragment with embedded styles, for self-contained preview
   - **DOCX** — re-generated Word document for the next editing cycle
   - **CSS** / **JS** — WordPress site-level stylesheet and script
   - **Heading Map** — JSON file preserving permalink IDs (carry forward to next cycle)
   - **Session Bundle** — ZIP of all session artifacts

### Repeat Conversion (with heading map)

1. Upload the edited DOCX
2. Upload the previous `.heading-map.json` file (file picker in the Advanced section, or paste the JSON)
3. Leave "Keep heading numbers" unchecked — the app strips old numbers and renumbers from the current structure
4. Process through reviews and convert
5. Download new HTML + new DOCX + new heading map
6. The heading map preserves permalink IDs: unchanged headings keep their anchor IDs, so WordPress URLs stay stable

### WordPress Deployment

1. Add the **CSS** as site-level custom CSS (Appearance → Customize → Additional CSS, or a custom CSS plugin)
2. Add the **JS** as either:
   - **Site-level JS** (no wrappers needed), or
   - **Code snippet** — must be wrapped in `<script>` tags (see `C:\Python Projects\css_js\FM.js` for an example)
3. Paste the **Fragment** HTML into a WordPress Custom HTML block
4. WordPress strips `<input>`, `<style>`, and `<script>` tags from Custom HTML blocks — the JS includes a fallback that recreates the search input automatically
5. **Fragment + CSS cannot work standalone in WordPress** — WordPress strips embedded `<style>` and `<script>` tags from Custom HTML blocks. CSS and JS must be added separately via site-level settings or code snippets as described above

## File Structure

```
word_to_wordpressV4.py          Main Flask app
docx_config_generator.py        Companion config generator
config.py                       SessionDir, PERSIST_DIR, env-backed settings
wordpress.css                   WordPress stylesheet (WCAG 2.1 AA)
wordpress.js                    WordPress script (TOC, search, scrollspy, list normalization)
core/
  permalinks.py                 Heading signature normalization, SPELLED_NUMS
  html_processor.py             HTML pipeline, Hybrid Rule, heading IDs, grid block builder
  manual_structure.py           Heading scraping, crosswalk, numbering conversion
  reference_linking.py          Reference extraction (6-tuple), external link extraction
  docx_processor.py             DOCX preprocessing, numbering, style maps
  styling.py                    Theme CSS, WordPress CSS/JS loaders
  pandoc_wrapper.py             Pandoc invocation
utils/
  helpers.py                    roman_to_int, normalize_hex_color, clamp_number, sanitize_theme_id
  url_policy.py                 External href allowlist for export / DOCX links
tests/                          Pytest suite (`python -m pytest tests/ -q`)
```

## Environment Variables

For local development, the defaults below are usable. For any deployed environment, do not rely on default secrets; follow `PROJECT_HANDOFF.md` for the required production posture.

| Variable | Default | Purpose |
|---|---|---|
| `PERSIST_DIR` | System temp directory | Root for session storage |
| `FLASK_SECRET_KEY` | `dev-secret` for local dev only | Flask session signing key; must be overridden in production |
| `SESSION_TTL_HOURS` | `48` | Stale session directories are pruned on a throttled schedule (see `PROJECT_HANDOFF.md`); set `0` to disable |
| `ZIP_MAX_UNCOMPRESSED_BYTES` / `ZIP_MAX_FILES` | Defaults in `config.py` | Caps bundle import before `extractall` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Session Data

Sessions are stored under `%TEMP%\docx2html_wsumanual\{session_id}\`. Each session gets a UUID-named directory with uploaded files, intermediate artifacts, and export outputs.

To clear all sessions: delete the `docx2html_wsumanual` directory in your temp folder.

## Key Concepts

### Heading Map (Permalink Stability)

The heading map JSON maps heading content **signatures** (normalized heading text) to anchor IDs. When you re-convert an edited document with the previous heading map, headings whose **normalized text still matches** keep the same ID—this fixes the early “anchors jump every conversion” problem. WordPress URLs with `#anchors` therefore survive when heading wording is unchanged.

**Strict matching:** There is **no fuzzy** or approximate signature match. If you change heading text (or, with **Keep heading numbers in text**, change embedded numbers), the signature may change and the map may assign a **new** ID unless you update the map deliberately.

### The Hybrid Rule

When assigning IDs to headings, the app follows this priority:
1. Match heading text signature against the uploaded heading map → use stored ID
2. If no match → generate a new slug from the heading text

### Numbering Conversion

The crosswalk system converts old-style heading references (Roman numerals, letters) to new-style numeric:
- `Chapter 1.D.4` → `Chapter 1.4.4`
- `Section I.A.2.b` → `Section 1.1.2.2`
- `Chapter One` → `Chapter 1`

## Troubleshooting

| Problem | Solution |
|---|---|
| App won't start | Verify Pandoc is installed: `pandoc --version` |
| 405 Method Not Allowed on conversion | Clear browser cache — this was a fixed bug |
| Search doesn't show on WordPress | Update the JS code snippet with the latest version from `wordpress.js` |
| Tables not editable | Check "Edit tables" checkbox on the upload form before uploading |
| Heading map not loading | Use the file picker (not just the paste box) in the Advanced section |
| Session data lost | Sessions live in temp — restart doesn't clear them, but OS cleanup might |
