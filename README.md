# Word-to-WordPress Conversion App

A Flask web application that converts Word documents (DOCX) into WordPress-ready HTML for publishing university policy manuals. Built for Washington State University's administrative manuals (Faculty Manual, GSPP, etc.).

This README describes the intended workflow and local usage. It is **not** a substitute for production security review, threat modeling, or formal release sign-off.

For the authoritative description of the architecture, module layout, security model, caching, design invariants, scope/non-goals, and the deployment/operational contract, see **`PROJECT_SPEC.md`**. Organization-specific release sign-off, secrets management, and threat modeling remain your own process.

## Features

- **DOCX to HTML conversion** via Pandoc with custom post-processing pipeline
- **WordPress-ready output** — generates HTML fragments, CSS, and JS for WordPress deployment
- **Permalink stability** — heading map JSON preserves anchor IDs across editing cycles, so WordPress URLs survive document revisions
- **WCAG 2.1 AA accessible** — skip navigation, ARIA landmarks, table scope attributes, keyboard-navigable TOC; the accessible **manual grid shell** (skip link, `nav`, search, `main`) is built in **one place** — `core/html_processor.py` → **`build_manual_grid_block`** (server TOC in preview when applicable; downloads use an empty TOC placeholder filled by **`wordpress.js`**)
- **Intended round-trip editing workflow** — exports a clean DOCX for the next Word editing cycle and supports heading-map-based permalink continuity; known limitations are handled through structured review steps in the app
- **Searchable TOC** — JavaScript-powered table of contents with live search, scrollspy, and keyboard navigation
- **Reference crosswalk** — converts legacy heading references (Roman numerals, letters) to numeric format
- **Print-ready** — the exported CSS includes a print stylesheet, so browser Print / Save as PDF drops the sidebar TOC and search box, repeats table headers across page breaks, and prints external link targets
- **Local-first runtime with a Railway/Docker deployment path** — treat internet-facing deployment as a separate hardening exercise (secrets, CSRF, container `PORT`, ZIP/session limits); validate against your own checklist before going public

---

## Setup & Usage

### Prerequisites

- **Python 3.12+** recommended (matches Docker and reliable `lxml` wheels on Windows); **3.10+** may work if dependencies install cleanly
- **Pandoc 3.9.0.2** — pinned known-good version; see **Pandoc version policy** below

### Install Pandoc

Download **Pandoc 3.9.0.2** from https://github.com/jgm/pandoc/releases/tag/3.9.0.2 and ensure `pandoc` is on your PATH. The app checks for Pandoc at startup: running `python word_to_wordpressV4.py` exits immediately if Pandoc is missing. (Under Gunicorn the check runs on the first request and is logged rather than exiting.)

Verify:
```bash
pandoc --version
```

### Pandoc version policy

The app pins a known-good Pandoc version (**3.9.0.2**) in `config.py` (`PANDOC_PINNED_VERSION`) and in the `Dockerfile`. It **does not auto-upgrade**. When the app starts it:

1. Logs the installed Pandoc version at `INFO`.
2. Warns (`WARNING`) if the installed version is older than the pin.
3. Checks the Pandoc GitHub releases API (throttled by `PANDOC_UPDATE_CHECK_TTL_HOURS`, default 7 days) and emits an `INFO` line if a newer upstream release exists. The check has a short network timeout, caches the result under `PERSIST_DIR/pandoc_update_cache.json`, and is skipped silently on any network failure — it will never block startup.

The checks run once per worker process: eagerly under `python word_to_wordpressV4.py`, and on the first request under Gunicorn. On ephemeral-disk hosts (Railway, fresh CI containers) the cache is recreated on every cold boot, so the GitHub lookup may run per container rather than strictly weekly — set `PANDOC_UPDATE_CHECK_ENABLED=0` to disable it in those environments.

When a newer release is announced, review the release notes, upgrade your local Pandoc manually, bump the pin in **three places together** (`PANDOC_PINNED_VERSION` in `config.py`, `ARG PANDOC_VERSION` in the `Dockerfile`, and the prerequisite version in this README), rerun the tests, and commit.

### Install Python Dependencies

```bash
pip install -r requirements.txt        # runtime dependencies (ranged)
pip install -r requirements-dev.txt    # runtime + test dependencies (pytest)
```

`requirements.lock.txt` pins the exact runtime versions the **Docker image** installs (reproducible builds, resolved for py3.12/manylinux). CI deliberately installs the ranged files instead, so an incompatible upstream release shows up there first. To bump dependencies: edit the ranges in `requirements.txt`, regenerate the lock (command in the lockfile header), run the tests, and commit both files together.

The runtime set is Flask, Flask-WTF (CSRF), Flask-Login (auth), Bleach (+tinycss2 for inline-style sanitization), python-docx, BeautifulSoup, lxml, Werkzeug, Markdown, and Gunicorn. On **Windows**, use **Python 3.12 or 3.13** if `lxml` fails to build on very new interpreters (prebuilt wheels lag).

> `lxml` is optional at runtime in some setups—BeautifulSoup can fall back to `html.parser`—but `requirements.txt` includes lxml for speed and consistency with CI/Docker.

### Automated tests

```bash
python -m pytest tests/ -q
```

The same suite runs in GitHub Actions on every push and pull request (`.github/workflows/ci.yml`).

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

This companion tool is local-only in the current project scope. See `README_config_generator.md` for usage details.

## Conversion Workflow

### First-Time Conversion (no heading map)

1. Upload your DOCX file
2. Configure settings: heading mapping mode (map to new numeric headings, or keep original), TOC depth, and whether to keep heading numbers in text. (Manual type — chapter vs. section — is detected automatically from the document.)
3. Optionally check "Edit tables" to review table formatting and header rows
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

1. Add the **CSS** as site-level custom CSS (Appearance → Customize → Additional CSS, or a custom CSS plugin).
   - **Append, don't replace.** If the site already has unrelated custom CSS in that box, paste the manual stylesheet *below* it — replacing the whole box deletes the site's own fixes.
   - The stylesheet is page-agnostic: it targets `body:has(.manual-grid)`, so publishing a second manual on a different page needs no CSS edit.
   - It includes a print stylesheet, so browser **Print / Save as PDF** drops the sidebar TOC, search box, and back-to-top button, repeats table headers across pages, and prints external link targets.
2. Add the **JS** as either:
   - **Site-level JS** (no wrappers needed), or
   - **Code snippet** — must be wrapped in `<script>` tags
3. Paste the **Fragment** HTML into a WordPress Custom HTML block
4. WordPress strips `<input>`, `<style>`, and `<script>` tags from Custom HTML blocks — the JS includes a fallback that recreates the search input automatically
5. **Fragment + CSS cannot work standalone in WordPress** — WordPress strips embedded `<style>` and `<script>` tags from Custom HTML blocks. CSS and JS must be added separately via site-level settings or code snippets as described above

## File Structure

```
word_to_wordpressV4.py          Entry point (Gunicorn target: word_to_wordpressV4:app)
webapp.py                       Flask app object, config, CSRF, login gate, lifecycle hooks
auth.py                         Tier-1 auth: env accounts, Flask-Login, per-session ownership
routes/
  auth_routes.py                Login / logout
  pages.py                      Home, instructions, /healthz
  convert_flow.py               Upload, heading/reference/table review, conversion
  downloads.py                  Artifact downloads, theme updates, bundle export
  imports.py                    HTML import, session-bundle import
  common.py                     Shared request-parsing helpers
services/
  session_state.py              session.json / edits.json load-save helpers
  docx_session.py               Shared DOCX pipeline + canonical session_data builder
docx_config_generator.py        Companion config generator
config.py                       SessionDir, PERSIST_DIR, env-backed settings
wordpress.css                   WordPress stylesheet (WCAG 2.1 AA)
wordpress.js                    WordPress script (TOC, search, scrollspy, list normalization)
core/
  permalinks.py                 Heading signatures, ref normalization, manual_type prefix
  html_processor.py             HTML pipeline, Hybrid Rule, heading IDs, table headers, grid block
  manual_structure.py           Heading scraping, crosswalk, numbering conversion
  reference_linking.py          Reference extraction (6-tuple), external link extraction
  docx_processor.py             DOCX preprocessing, numbering, style maps
  styling.py                    Theme CSS, WordPress CSS/JS loaders
  pandoc_wrapper.py             Pandoc invocation
utils/
  helpers.py                    roman_to_int, normalize_hex_color, clamp_number, sanitize_theme_id
  url_policy.py                 External href allowlist (output) + input normalization
templates/                      Jinja templates (home, instructions, heading/reference/table review)
scripts/                        Standalone maintainer utilities (see scripts/README.md)
tests/                          Pytest suite (`python -m pytest tests/ -q`)
```

## Environment Variables

For local development, the defaults below are usable. For any deployed environment, do not rely on default secrets; set a strong `FLASK_SECRET_KEY`, review session persistence and ZIP import limits in `config.py`, and apply your organization’s production checklist.

| Variable | Default | Purpose |
|---|---|---|
| `PERSIST_DIR` | System temp directory | Root for session storage |
| `FLASK_SECRET_KEY` | `dev-secret` for local dev only | Flask session/login cookie signing key; must be overridden in production |
| `AUTH_OWNER_EMAIL` / `AUTH_OWNER_PASSWORD` | unset | A single login account (plaintext password, hashed in memory at startup). Setting these turns authentication on. See **Authentication** below. |
| `AUTH_USERS` | unset | Additional accounts as a comma/newline list of `email:password_hash`. Setting this turns authentication on. |
| `SESSION_TTL_HOURS` | `48` | When greater than `0`, stale session directories are pruned on a throttled schedule in the main app; set `0` to disable |
| `ZIP_MAX_UNCOMPRESSED_BYTES` / `ZIP_MAX_FILES` | Defaults in `config.py` | Caps bundle import before `extractall` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `PANDOC_PINNED_VERSION` | `3.9.0.2` | Minimum known-good Pandoc; startup warns if older |
| `PANDOC_UPDATE_CHECK_ENABLED` | `1` | Set `0` to disable the weekly upstream-release check |
| `PANDOC_UPDATE_CHECK_TTL_HOURS` | `168` | Cache duration for the upstream-release check (hours) |
| `PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS` | `3.0` | Network timeout for the upstream-release check |

## Authentication

The app ships with optional **Tier-1 authentication** (env-configured accounts; no database). It is **off by default** — with no accounts set, the app runs open, which is fine for local use. Set accounts to require login; this is the recommended baseline for any shared or Railway deployment.

**Enable it** one of two ways (you can combine them):

- **Quick single account** — set both:
  ```
  AUTH_OWNER_EMAIL=you@wsu.edu
  AUTH_OWNER_PASSWORD=a-strong-password
  ```
- **Multiple accounts** — generate a hash per user and list them in `AUTH_USERS`:
  ```bash
  python scripts/make_password_hash.py        # prints a scrypt hash
  ```
  ```
  AUTH_USERS="alice@wsu.edu:scrypt:...,bob@wsu.edu:scrypt:..."
  ```

When enabled, every page requires sign-in (except `/healthz` and the login page), passwords are scrypt-hashed, the login cookie is httpOnly/SameSite=Lax (and Secure when deployed), and each conversion session is **owned by the user who created it** — one user cannot open another's session.

**Deployment notes:** set a strong, stable `FLASK_SECRET_KEY` (it signs the login cookie; if it changes, everyone is logged out). This Tier-1 model fits a **small trusted team on a single instance**. Self-service accounts, password reset, or campus SSO are deliberately out of scope — see `PROJECT_SPEC.md` §16 for the multi-user/SSO trajectory.

## Session Data

Sessions are stored under `%TEMP%\docx2html_wsumanual\{session_id}\`. Each session gets a UUID-named directory with uploaded files, intermediate artifacts, and export outputs.

To clear all sessions: delete the `docx2html_wsumanual` directory in your temp folder.

## Key Concepts

### Heading Map (Permalink Stability)

The heading map JSON maps heading content **signatures** (normalized heading text) to anchor IDs — specifically `{signature: [ids in document order]}`, a list per signature so headings that share the same text each keep a distinct, stable anchor. When you re-convert an edited document with the previous heading map, headings whose **normalized text still matches** keep the same ID—this fixes the early “anchors jump every conversion” problem. WordPress URLs with `#anchors` therefore survive when heading wording is unchanged. (Older flat `{signature: id}` maps from earlier versions still upload and apply.)

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
| Table header row is wrong | Word decides which row lands in `<thead>` and is often wrong. In Table Review, set that table to **Column headers**, **Title → caption**, or **Ordinary data** |
| An External URL wasn't saved | Only `http(s)`, `mailto:`, and `#anchor` links are stored. A bare host like `policies.wsu.edu/x` is promoted to `https://` automatically; anything else is reported in a warning after saving |
| Heading map not loading | Attach the `.json` via the file picker, or paste its contents in the Advanced section — either works (if both are filled, the pasted text wins) |
| Session data lost | Sessions live in temp — restart doesn't clear them, but OS cleanup might |
