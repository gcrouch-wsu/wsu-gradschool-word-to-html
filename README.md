# Word-to-WordPress Conversion App

A Flask web application that converts Word documents (DOCX) into WordPress-ready HTML for publishing university policy manuals. Built for Washington State University's administrative manuals (Faculty Manual, GSPP, etc.).

## Features

- **DOCX to HTML conversion** via Pandoc with custom post-processing pipeline
- **WordPress-ready output** — generates HTML fragments, CSS, and JS for WordPress deployment
- **Permalink stability** — heading map JSON preserves anchor IDs across editing cycles, so WordPress URLs survive document revisions
- **WCAG 2.1 AA accessible** — skip navigation, ARIA landmarks, table scope attributes, keyboard-navigable TOC
- **Round-trip editing** — exports a clean DOCX for the next Word editing cycle, then re-imports with stable permalinks
- **Searchable TOC** — JavaScript-powered table of contents with live search, scrollspy, and keyboard navigation
- **Reference crosswalk** — converts legacy heading references (Roman numerals, letters) to numeric format
- **Deployable** — runs locally with Flask dev server or on Railway/Docker with gunicorn

---

## Setup & Usage

### Prerequisites

- **Python 3.10+** (uses `str | None` and `list[dict]` type syntax)
- **Pandoc** — required for DOCX-to-HTML and HTML-to-DOCX conversion

### Install Pandoc

Download from https://pandoc.org/installing.html and ensure `pandoc` is on your PATH. The app checks for Pandoc at startup and will not run without it.

Verify:
```bash
pandoc --version
```

### Install Python Dependencies

```bash
pip install flask~=3.0 python-docx~=1.1 beautifulsoup4~=4.12 lxml~=5.1 werkzeug~=3.0
```

> `lxml` is optional but recommended — BeautifulSoup falls back to `html.parser` if lxml is unavailable, but lxml is significantly faster on large documents.

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

See `README_config_generator.md` for details on this tool.

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
```

## Environment Variables (optional)

| Variable | Default | Purpose |
|---|---|---|
| `PERSIST_DIR` | System temp directory | Root for session storage |
| `FLASK_SECRET_KEY` | `dev-secret` | Flask session signing key |
| `SESSION_TTL_HOURS` | `48` | Session expiration (not yet enforced) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Session Data

Sessions are stored under `%TEMP%\docx2html_wsumanual\{session_id}\`. Each session gets a UUID-named directory with uploaded files, intermediate artifacts, and export outputs.

To clear all sessions: delete the `docx2html_wsumanual` directory in your temp folder.

## Key Concepts

### Heading Map (Permalink Stability)

The heading map JSON maps heading content signatures to anchor IDs. When you re-convert an edited document with the previous heading map, headings whose text hasn't changed keep their original anchor IDs. This means WordPress URLs like `yoursite.edu/manual/#chapter-one---administration` survive across editing cycles.

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
