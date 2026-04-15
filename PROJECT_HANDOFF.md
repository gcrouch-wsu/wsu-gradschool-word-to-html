# Project Handoff - Word-to-HTML

Last updated: 2026-04-19

This file is the single source of truth for the current state of this repo.

## How to use this document as a build guide

Use the sections below in this order when turning the repo into a releasable build:

1. **Lock scope** — Read **Build Decisions For This Build** first. Do not expand scope (CSV/XLSX heading maps, companion on Railway, new persistence backends, or “trusted internal only” security) without updating this file and the **Definition Of Done**.
2. **Execute by phase** — Follow the **Build Plan** (Phases 1–5) in order. The **Priority Order** list is a short execution checklist; it is aligned with those phases.
3. **Map work to Required Fixes** — Implement **Required Fixes** 1–10 as you go; each phase’s **Work** bullets name the owning files and outcomes.
4. **Gate merges on acceptance** — After each phase, satisfy the matching **Acceptance Criteria** subsections before treating that slice as done.
5. **Close the build** — Finish only when **Definition Of Done**, **Required Regression Tests**, and the **Railway Release Checklist** are all satisfied, and `README.md` matches shipped behavior.
6. **Update docs with code** — If implementation changes scope or user-visible behavior, edit this handoff and `README.md` in the same change set so they stay authoritative.

**Quick map:** current gaps → **Required Fixes** + **Current Status** / **Railway Deployment**; locked choices → **Build Decisions For This Build**; release bar → **Definition Of Done** + **Acceptance Criteria** + **Railway Release Checklist**.

## Purpose

This project converts policy/manual documents into WordPress-ready output.

Primary goals:

- Convert DOCX manuals into reviewed, publishable HTML.
- Preserve stable heading IDs across edit cycles so existing WordPress permalinks keep working.
- Let editors review heading mappings, references, and table formatting before export.
- Export the assets needed for WordPress publishing:
  - HTML fragment
  - standalone HTML
  - CSS
  - JS
  - DOCX
  - heading map
  - session bundle
- Support a repeatable workflow:
  1. Upload DOCX
  2. Review/fix headings and references
  3. Export HTML + DOCX + heading map
  4. Re-edit later and re-import with the prior heading map

## Current Repo Layout

- `word_to_wordpressV4.py`
  Main Flask app. Routes, review UI, conversion orchestration, export/import flow.
- `docx_config_generator.py`
  Companion Flask app for DOCX style/config generation. **Local-only for this build** (not on the default Railway target); see **Build Decisions For This Build** and `README_config_generator.md`.
- `core/html_processor.py`
  HTML cleanup, TOC/body wrapping, heading IDs, list normalization, reference application, table formatting, and **`build_manual_grid_block`** (single accessible shell for preview + downloads; optional **`toc_html=`** for server-rendered TOC vs empty placeholder for JS-built TOC).
- `core/docx_processor.py`
  DOCX preprocessing, hyperlink extraction, numbering/bookmark/style helpers.
- `core/manual_structure.py`
  Heading scraping, crosswalk generation, numbering conversion, heading lookup/sort helpers.
- `core/reference_linking.py`
  Reference extraction and external-link extraction.
- `core/styling.py`
  Theme CSS helpers and WordPress CSS/JS loaders.
- `config.py`
  Environment-backed settings and session directory helper.
- `Dockerfile`
  Container build for deployment.
- `wordpress.css`, `wordpress.js`
  Output assets used by exports and preview.
- `tests/`
  Pytest regression suite (`pytest` from repo root).

## Current Status

The main converter has had a **code-level hardening pass** (security, bundle fidelity, CSRF, Docker `$PORT`, session/ZIP limits, heading-map path cleanup). Treat the repo as **not production-declared** until you finish **operational** Railway checks (real secrets, smoke on `$PORT`, representative document runs). See **Residual gaps** below and **Railway release checklist**.

### Shipped in code (audit anchors)

| Area | Where to look |
|------|----------------|
| HTML sanitization (import / strip paths) | `core/html_processor.py` — `sanitize_manual_html_fragment`, `strip_html_assets` |
| `main.manual` / `div.manual` round-trip | `core/html_processor.py` — `find_manual_container`, `extract_manual_fragment`; tests: `tests/test_manual_fragment.py` |
| CSV/XLSX heading maps removed | `word_to_wordpressV4.py` — heading review form (JSON stable map only) |
| Bundle manifest + stable map on disk | `word_to_wordpressV4.py` — `export_session`, `import_bundle`; prefers `stable_heading_map.json` over manifest |
| Bundle rebuild preserve/strip order | `word_to_wordpressV4.py` — `_bundle_import_post_pandoc_pipeline` (aligned with `convert()`); tests: `tests/test_bundle_import_pipeline.py` |
| Session write vs stable map | `word_to_wordpressV4.py` — `do_convert` saves map then reloads into `session.json` |
| Duplicate same-text refs | `core/html_processor.py` — offset-based replacement |
| External URL allowlist + noopener | `utils/url_policy.py`; reference / DOCX link paths |
| ZIP limits | `word_to_wordpressV4.py` — `_zip_archive_within_limits`; `config.py` — `ZIP_MAX_*` |
| Session pruning | `word_to_wordpressV4.py` — `_prune_stale_sessions_if_due`, `SESSION_TTL_HOURS` |
| CSRF | `word_to_wordpressV4.py` — `CSRFProtect`, form tokens, table preview `X-CSRFToken` |
| Docker / PORT | `Dockerfile` — `CMD` binds `0.0.0.0:${PORT}` |
| Regression tests (partial suite) | `tests/` — `pytest` |
| Accessible manual chrome (one builder) | `core/html_processor.py` — `build_manual_grid_block` with optional `toc_html=`; `word_to_wordpressV4.py` — `do_convert` uses it (no duplicate grid markup) |

### Residual gaps (next audit / backlog)

- **Full bundle E2E:** No CI test runs Pandoc on a real DOCX through export → import (slow; needs fixtures or manual smoke).
- **Duplicate-ref paragraph E2E:** No end-to-end pytest for two identical strings with distinct edits through save → `do_convert`.
- **`/update_theme`:** POST route exists; **no in-repo HTML form** currently submits to it—if UI is added, include CSRF like other forms.
- **Download lookup:** Still scans session directories under `PERSIST_DIR` (pruning limits growth; not a btree index).
- **Companion app:** Still **local-only** per build decisions.
- **Fuzzy / approximate permalink signatures:** Not implemented. IDs map from **normalized exact** heading text (plus stable map). Looser matching would be a **product decision** (collision and wrong-anchor risks); see **README.md** / **instructions.md** under heading map.

What is not true anymore:

- Older handoff notes that implied the repo was fully repaired and core-audited are stale.
- `next_build.md` and `next_build_validation.md` have been consolidated into this file and should not be recreated as parallel sources of truth.

## External re-audit checklist (Gemini / second reviewer)

Use after pulling latest sources. In your report, cite **file + symbol/route** for each row.

1. **Spec mapping:** Walk **Required Fixes** (1–10) and **Acceptance Criteria**; mark each **Met / Partial / Missing** vs current code.
2. **HTML safety:** Trace import → review → preview for unsanitized strings and `|safe`; grep for `onclick`, `javascript:`, `onerror` in emitted HTML paths.
3. **Bundle fidelity:** Confirm `_bundle_import_post_pandoc_pipeline` only strips headings when `preserve_numbers` is false and `mapping_mode` is not `keep_old`; confirm `stable_heading_map.json` overrides manifest on import; confirm `export_session` manifest fields match session.
4. **CSRF:** Enumerate `methods=["POST"]` routes; verify token field or document intentional gap (`/update_theme` if unused).
5. **Docker:** `Dockerfile` installs `requirements.txt`; `CMD` honors `$PORT`.
6. **Commands:** From repo root: `python -m compileall word_to_wordpressV4.py core utils` and `python -m pytest tests/ -q` (Python **3.12** recommended on Windows for prebuilt `lxml` wheels).
7. **Accessible shell:** Confirm preview and download paths both use **`build_manual_grid_block`**; with **`toc_html`** only where the server injects TOC HTML, else empty `<ul>` for **`wordpress.js`**.

**Past external audits:** (1) Bundle import called `strip_heading_numbers_dom` before honoring `preserve_numbers`—**fixed**; see `tests/test_bundle_import_pipeline.py`. (2) Second pass: **`_HEADING_PREFIX_RE`** used an ambiguous `[:.\---]` character class (Python `FutureWarning`)—**fixed** to explicit `[:\.\u2013\u2014\-]` in `word_to_wordpressV4.py`. (3) **README** vs handoff Python version—**aligned** (README now recommends 3.12+). (4) **Bleach** `NoCssSanitizerWarning` noise in tests—**suppressed** via `pytest.ini` `filterwarnings` (not a security relaxation). (5) **Accessibility shell drift:** `do_convert` duplicated the manual grid markup instead of **`build_manual_grid_block`**—**fixed** by optional **`toc_html=`** in `core/html_processor.py:build_manual_grid_block` and tests in `tests/test_build_manual_grid.py`. (6) **NBSP in heading signatures:** `normalize_heading_signature` collapses NBSP via `\s+`—covered by `tests/test_permalink_signature.py`.

## Confirmed Hard Limitations

These are still useful context and should not be re-opened casually:

1. Pandoc `--reference-doc` has produced corrupt DOCX output in this project history.
   Current workaround: DOCX export uses plain Pandoc output plus local post-processing.
   Note: `core/pandoc_wrapper.py` still exposes an optional `reference_doc` parameter, but the current app flow does not pass one.

2. Some WordPress theme list-marker behavior is still corrected in JS after load.
   Current workaround: `wordpress.js` forces list styles after render, which may cause visible flicker.

## Deployment Verdict

Code-level items from **Required Fixes** are largely implemented (see **Shipped in code**). **Production** still requires you to satisfy **Railway release checklist** on a real deploy (secrets, `$PORT` smoke, representative documents) and accept **Residual gaps** or schedule follow-up work.

## Railway Deployment

Railway is the key deployment target for this repo.

What should be deployed:

- Deploy the main app, `word_to_wordpressV4.py`.
- Do not treat `docx_config_generator.py` as part of the default Railway deployment unless it is separately hardened and intentionally exposed.

Current deployment model:

- The repo ships a Docker-based deployment path.
- The image installs Pandoc, which is required for DOCX <-> HTML conversion.
- The intended web server inside the container is Gunicorn serving `word_to_wordpressV4:app`.

Current Railway-specific reminders (operations):

1. **`FLASK_SECRET_KEY`** must be set in Railway—do not rely on `config.py` defaults in production.
2. **`PERSIST_DIR`** is instance-local filesystem storage; sessions and exports are not durable across instance replacement unless you add external storage (out of scope for this build).
3. Run the **Railway release checklist** on a real preview/staging deploy before calling the service production-ready.

Required Railway deployment contract:

- The container must bind to the injected `PORT`.
- `FLASK_SECRET_KEY` must be explicitly set in Railway.
- Pandoc must remain present in the runtime image.
- The deployed service must assume filesystem state is local-instance state, not durable shared storage.

Environment variables that matter for Railway:

- `FLASK_SECRET_KEY`
  Required in production. Do not rely on the default from `config.py`.
- `PERSIST_DIR`
  Optional override for session storage root. If left unset, the app uses temp storage.
- `SESSION_TTL_HOURS`
  Throttled session-directory pruning uses this value (see `word_to_wordpressV4.py`). Set `0` to disable pruning.
- `LOG_LEVEL`
  Optional logging verbosity.
- `PORT`
  Injected by Railway. The container path must honor it.

Filesystem and persistence notes for Railway:

- Current session/export/import state is stored on the local filesystem under `PERSIST_DIR`.
- That storage should be treated as instance-local and operationally temporary.
- In-progress sessions, exported bundles, and generated artifacts should not be assumed durable across redeploys, restarts, or instance replacement.
- Because of that, session lifecycle management is not just cleanup work; it is part of deployment correctness.

Railway release checklist:

1. Confirm Gunicorn binding uses injected `$PORT` in the built image (`Dockerfile`).
2. Set `FLASK_SECRET_KEY` in Railway.
3. Decide whether `PERSIST_DIR` should remain temp-backed or point to a deliberate writable location.
4. Confirm session pruning and ZIP import limits are acceptable for your traffic (`SESSION_TTL_HOURS`, `ZIP_MAX_*` in `config.py`).
5. Run a startup smoke check that proves:
   - the container starts
   - Pandoc is available
   - the app is listening on `$PORT`
6. Verify the deployed service is only the main converter unless there is an explicit decision to expose the companion app.

## Required Fixes

> **April 2026:** Items **1–10** are implemented in the codebase unless noted *Partial* in the subsection. Older “Current problem / Needed work” text is kept for history—use **Shipped in code** and **Residual gaps** for executive status.

### 1. Sanitize imported and rendered HTML properly

Status: **Shipped** (Bleach allowlist + import stripping); keep auditing any `|safe` or new string-built HTML.

Current problem:

- HTML cleanup only strips a small subset of tags.
- Dangerous attributes and URL schemes can survive import.
- Review/preview pages build HTML using document-derived strings with incomplete escaping.
- Preview renders `body_html|safe`.

Why it matters:

- This is the highest-risk security gap in the repo.
- A malicious HTML import or crafted document content can become executable HTML in review or preview output.

Needed work:

- Add real sanitization/allowlisting for imported HTML.
- Escape all document-derived strings before injecting them into review pages.
- Reject unsafe URL schemes before render/export.

### 2. Fix HTML round-trip compatibility for exporter output

Status: **Shipped** in `find_manual_container` / `extract_manual_fragment`; verify end-to-end on your templates.

Current problem:

- Exported manual markup uses `<main class="manual">`.
- Several processors and the HTML import helper expect `div.manual`.
- Re-importing this app's own grid-wrapped HTML is currently broken.

Why it matters:

- This breaks the app's own HTML round-trip story.
- The mismatch affects more than one helper, so this is not just a single-function bug.

Needed work:

- Support both `main.manual` and `div.manual` consistently.
- Fail clearly if no manual body is found instead of returning `'None'`.
- Verify export -> import -> review works for app-generated HTML.
- Fix downstream processors that still scope to `div.manual`, including reference application.

### 3. Remove broken CSV/XLSX heading-map upload and keep JSON support

Status: **Shipped**

Current problem:

- `load_heading_map_file(...)` is called but not defined anywhere in the repo.

Why it matters:

- The CSV/XLSX heading-review upload path is a runtime `NameError`.
- The JSON stable heading map path works. The CSV/XLSX path does not.

Needed work:

- Remove or disable the CSV/XLSX heading-map upload path for this build.
- Keep JSON stable heading-map upload as the supported path and update UI/docs to match.

### 4. Make session bundle export/import lossless

Status: **Shipped** (manifest fields, disk-preferred stable map, `do_convert` ordering, `_bundle_import_post_pandoc_pipeline`); full faithfulness still depends on manifest completeness and Pandoc reproducibility.

Current problems:

- ~~Session metadata is written before the fresh stable heading map file is saved.~~ *(Addressed in `do_convert`.)*
- ~~Manifest export can contain stale `stable_heading_map` data.~~ *(Export prefers on-disk JSON when present.)*
- ~~Important session fields are omitted from the manifest.~~ *(Expanded manifest.)*
- ~~Bundle import rebuilds from manifest values instead of preferring the extracted `stable_heading_map.json`.~~ *(Prefers file.)*
- ~~Bundle import currently ignores `preserve_numbers` intent when rebuilding HTML.~~ *(Fixed; see tests.)*

Why it matters:

- Export/import is not a faithful restore.
- Permalink continuity and conversion settings can drift silently.

Needed work:

- Treat `stable_heading_map.json` as authoritative when present.
- Export all conversion-critical settings.
- Keep manifest/session state aligned with the saved stable map.
- Honor preserved-numbering settings during import rebuild.

### 5. Fix duplicate same-text reference replacement

Status: **Shipped** in processor; paragraph-level automated test still *Partial* (see **Residual gaps**).

Current problem:

- Reference replacement sorts by stored start offset, but the actual replacement logic still replaces the first matching occurrence in the paragraph.

Why it matters:

- If the same reference text appears twice in one paragraph, edits can attach to the wrong occurrence.
- That makes the review UI untrustworthy for real documents.

Needed work:

- Replace references by actual offset/range, not first text match.

### 6. Restrict unsafe external URLs from DOCX and HTML flows

Status: **Shipped** (`utils/url_policy.py`, DOCX validation, reference pipeline `rel` on `_blank`).

Current problems:

- DOCX hyperlink validation allows `javascript:` and other unsafe schemes.
- Those links can be copied into review state and then exported back out.
- Exported external links created by the reference pipeline do not currently add `rel="noopener noreferrer"` when opening a new tab.

Why it matters:

- Security issue
- Content integrity issue

Needed work:

- Allowlist external link schemes, ideally `http` and `https` only.
- Reject or strip everything else unless there is a deliberate supported case.
- Add `rel="noopener noreferrer"` to exported external links that use `_blank`.

### 7. Fix Railway container binding and deployment defaults

Status: **Shipped** for `$PORT` + `requirements.txt` in Docker; **ops** still required to set `FLASK_SECRET_KEY` in Railway (code cannot force a secret).

Current problems:

- ~~`Dockerfile` hard-binds Gunicorn to `0.0.0.0:8080`.~~ *(Superseded: `CMD` uses `${PORT}`.)*
- ~~Railway expects the container to listen on `0.0.0.0:$PORT`.~~ *(Addressed in `Dockerfile`.)*
- Main app secret still falls back to `dev-secret` if not configured *(deployment must override).*

Why it matters:

- Container portability is incorrect.
- A misconfigured deployment can be insecure by default.

Needed work:

- ~~Bind Gunicorn to the injected `$PORT`.~~ *(Done.)*
- Require a real `FLASK_SECRET_KEY` in deployment *(Railway env; not hardcoded).*
- Verify the deploy path being used is the container path, not just the local Flask path.

### 8. Add archive-bomb protection and real session cleanup

Status: **Shipped** for ZIP limits + throttled session pruning; download route still scans session dirs (mitigated by pruning).

Current problems:

- Upload validation is mostly extension-based before deeper parsing.
- ~~ZIP bundle import checks traversal but not decompressed size or entry count.~~ *(Limits added: `_zip_archive_within_limits`.)*
- ~~`SESSION_TTL_HOURS` exists but is unused.~~ *(Throttled prune hook added.)*
- Download lookup scans all session directories with no cleanup strategy *(pruning reduces volume; scan pattern unchanged).*

Why it matters:

- Disk/memory exhaustion risk
- Long-lived storage growth
- Latency degradation over time

Needed work:

- ~~Enforce archive size/file-count limits before extraction.~~ *(Done.)*
- ~~Implement session pruning based on `SESSION_TTL_HOURS`.~~ *(Done.)*
- Reduce reliance on full-directory scans for download lookup *(future optimization).*

### 9. Add a minimum regression test suite

Status: **Partial** — `tests/` exists with URL policy, sanitization, CSRF, bundle pipeline, and manual-fragment coverage; full Pandoc bundle E2E and duplicate-ref paragraph E2E are still manual or future work.

Current problem:

- ~~There are no automated tests in the repo.~~ *(Superseded: see `tests/`.)*

Why it matters:

- Several currently confirmed bugs are exactly the kind that regress silently.

Minimum coverage needed:

- HTML sanitization *(partially automated)*
- Exported HTML re-import *(partially automated — fragment extraction; not full Pandoc round-trip)*
- Heading-map upload path handling *(JSON path; CSV/XLSX removed)*
- Duplicate same-text reference replacement *(processor logic; no full UI E2E)*
- Session bundle round-trip *(settings + pipeline helpers; no full zip E2E in CI)*
- External URL policy *(automated)*
- CSRF behavior *(automated)*
- Deployment startup smoke test *(manual / CI TBD)*

### 10. Add CSRF protection for the deployed main app

Status: **Shipped** for all user-facing mutating forms and the table preview JSON POST (`X-CSRFToken`). **`/update_theme`** remains without an in-repo form—add a token if you wire UI to it.

Current problem:

- ~~The main converter uses plain Flask form posts with no CSRF protection.~~ *(Superseded for wired forms.)*

Why it matters:

- The build decision for this repo is to prepare the main converter for internet-facing Railway deployment.
- Without CSRF controls, mutating routes can be driven by cross-site requests from another origin.

Needed work:

- ~~Add CSRF protection to the deployed main app's mutating form flows.~~ *(Done for current UI.)*
- Ensure the chosen approach fits the current Flask form pattern without silently breaking the workflow.

## Important Enhancements

These are not the first blockers to fix, but they are worth doing after the required fixes:

1. Move away from `render_template_string` toward normal template files.
2. Reduce repeated BeautifulSoup reparsing where practical.
3. Store more session state relative to session root instead of absolute paths.
4. ~~Wire the Docker image to `requirements.txt` or clearly document intentional drift.~~ *(Dockerfile uses `requirements.txt`.)*
5. ~~Clean up the regex patterns that still emit `FutureWarning` in the entrypoints.~~ *(`_HEADING_PREFIX_RE` character class fixed; re-run with `-W error::FutureWarning` if new patterns are added.)*
6. Add a progress indicator for slow conversions.
7. **Companion app (post-this-build):** `docx_config_generator.py` is **local-only for this build** (see **Build Decisions For This Build**). Treat any future “deploy the companion on Railway” work as a **separate** initiative with its own security review and handoff update—not part of this release.

## Priority Order

Recommended implementation order:

1. HTML safety and unsafe URL handling
2. `main.manual` vs `div.manual` compatibility
3. Duplicate reference replacement by offset
4. Remove broken CSV/XLSX heading-map upload path
5. Session bundle fidelity and preserved-numbering import behavior
6. Railway `$PORT`, deployment-secret, and CSRF hardening
7. ZIP/session lifecycle protections
8. Regression tests
9. Follow-up refactors and UX improvements

## Build Decisions For This Build

These decisions are locked for the next build so implementation does not stall on scope ambiguity:

1. CSV/XLSX heading-map path:
   - Do not implement CSV/XLSX support in this build.
   - Remove or disable any broken CSV/XLSX upload path and keep JSON heading-map support as the only supported format.

2. Companion app deployment status:
   - `docx_config_generator.py` is local-only for this build.
   - It is not part of the Railway deployment target and should not be treated as internet-ready.

3. Railway persistence strategy:
   - Keep the current local-instance/session-directory model for this build.
   - Add cleanup, limits, and explicit documentation instead of introducing a new persistence architecture in this pass.

4. Security posture:
   - The main converter is being prepared for internet-facing Railway deployment.
   - CSRF protection, production secret configuration, and HTML/input hardening are in scope for this build.

## Build Plan

This is the recommended execution plan for turning the current repo into a releasable build.

### Phase 1 - Security and Input Safety

Scope:

- `core/html_processor.py`
- `word_to_wordpressV4.py`
- `core/docx_processor.py`
- `core/reference_linking.py` if URL parsing behavior changes

Work:

- Add HTML sanitization/allowlisting for import paths.
- Escape document-derived strings in heading and reference review pages.
- Restrict external links to an explicit scheme allowlist.
- Add `rel="noopener noreferrer"` for exported `_blank` links.

### Phase 2 - HTML Round-Trip and Reference Correctness

Scope:

- `core/html_processor.py`
- `word_to_wordpressV4.py`

Work:

- Fix `main.manual` vs `div.manual` assumptions.
- Fix `extract_manual_fragment()` returning `'None'`.
- Fix duplicate same-text reference replacement to honor the intended occurrence.
- Verify export/import/reference-review paths against app-generated HTML.

### Phase 3 - Heading Map and Bundle Fidelity

Scope:

- `word_to_wordpressV4.py`
- `core/html_processor.py`
- any related UI/docs that still expose the broken CSV/XLSX path

Work:

- Remove or disable the broken CSV/XLSX heading-map path.
- Make bundle export/import lossless.
- Align manifest contents with actual saved session state.
- Make imported `stable_heading_map.json` authoritative when present.
- Honor `preserve_numbers` and related settings during bundle-import rebuild.

### Phase 4 - Railway and Runtime Hardening

Scope:

- `Dockerfile`
- `config.py`
- `word_to_wordpressV4.py`
- deployment docs as needed

Work:

- Fix Gunicorn binding to use Railway `$PORT`.
- Require production secret configuration.
- Add CSRF protection for the deployed main app.
- Implement session pruning and archive-size/file-count protections.
- Confirm Pandoc remains available in the deployed image.

### Phase 5 - Regression Coverage and Release Readiness

Scope:

- new test files and test tooling
- any supporting fixtures

Work:

- Add minimum regression tests for the confirmed bugs.
- Add a startup/deployment smoke check.
- Reconcile `README.md` with the final supported behavior.

## Acceptance Criteria

The build should not be considered complete unless all of the following are true.

### 1. HTML Safety

- Imported HTML no longer preserves event handlers such as `onerror`.
- Unsafe URL schemes such as `javascript:` do not survive import, review, or export.
- Review pages render literal markup-looking source text as text, not executable HTML.
- Preview output is safe for the chosen deployment threat model.

### 2. HTML Round-Trip

- Exported grid-wrapped HTML can be re-imported without producing `'None'`.
- Code paths that scope to the manual container work with the actual exported structure.
- Export -> import -> review completes successfully on representative sample output.

### 3. Heading Map Paths

- The broken CSV/XLSX upload path is removed or disabled.
- The UI and docs no longer claim CSV/XLSX heading-map upload works.
- JSON stable heading map upload continues to work.

### 4. Bundle Fidelity

- Session bundle export includes all settings needed for faithful restore.
- Imported bundles prefer the extracted stable heading map artifact when present.
- `preserve_numbers` behavior survives export/import correctly.
- Exported and re-imported bundles produce equivalent review/conversion state for the same input.

### 5. Reference Editing Correctness

- Two identical references in one paragraph can be edited independently.
- The correct occurrence is replaced in final output.
- External-link overrides and internal-link overrides remain deterministic.

### 6. Railway Deployment

- The deployed container listens on Railway `$PORT`.
- `FLASK_SECRET_KEY` is required/set in production.
- Pandoc is available in the running image.
- Startup succeeds in the actual container path, not only in local Flask mode.

### 7. Session and Archive Safety

- Bundle import rejects archives that exceed configured size/file-count limits.
- Stale sessions are pruned according to the selected lifecycle rules.
- Download lookup does not rely indefinitely on unbounded stale-session accumulation.

### 8. Test Coverage

- Regression coverage exists for every currently confirmed material bug.
- The test suite passes in a clean environment.

### 9. CSRF Protection

- Mutating routes in the deployed main app reject requests without valid CSRF state.
- The selected CSRF approach does not break the supported review and conversion flow.

## Required Regression Tests

At minimum, the build should add automated coverage for:

1. HTML sanitization:
   - event handler stripping
   - unsafe URL stripping/rejection

2. HTML round-trip:
   - `build_manual_grid_block(...)` output can be re-imported
   - manual container handling works with `main.manual`

3. Heading-map path:
   - broken CSV/XLSX route/UI path is absent or disabled
   - JSON heading-map upload still works

4. Duplicate reference replacement:
   - two identical references in one paragraph map to the correct occurrences

5. Session bundle round-trip:
   - export -> import preserves heading-map and numbering-related state

6. Preserve-numbers bundle import:
   - imported bundle rebuild respects preserved numbering behavior

7. External URL policy:
   - `javascript:` and similar schemes are rejected
   - allowed schemes still work

8. CSRF behavior:
   - protected mutating routes reject requests without valid CSRF state

9. Railway/container smoke:
   - container starts
   - Pandoc is available
   - app listens on injected `$PORT`

## Railway Release Checklist

Use this before calling the build deployable on Railway:

1. Confirm `Dockerfile` binds Gunicorn to `0.0.0.0:$PORT`.
2. Confirm Railway environment includes:
   - `FLASK_SECRET_KEY`
   - any chosen `PERSIST_DIR` override
   - optional `LOG_LEVEL`
   - optional `SESSION_TTL_HOURS`
3. Start the built image in a Railway-like environment and confirm:
   - process boots successfully
   - Pandoc is present
   - health check passes
   - app is reachable on `$PORT`
4. Verify session storage behavior is understood:
   - instance-local vs persistent
   - cleanup behavior
   - impact of restart/redeploy
5. Verify only the intended app is deployed:
   - main converter yes
   - companion config generator only if explicitly supported
6. Verify no insecure default secret is being used.
7. Verify mutating routes enforce the chosen CSRF protection in the deployed app.
8. Verify archive limits and session pruning are active.
9. Verify README and handoff match the actual supported deployment behavior.

## Definition Of Done

**Code vs ops:** Most **Required Fixes** (1–10) are **implemented in code** as of the April 2026 hardening pass; **production “done”** still requires the **Railway release checklist** on a real environment, acceptable **Residual gaps**, and passing **`pytest`** where automated.

The build is done only when:

- all required fixes in this document are implemented or intentionally removed from scope with matching code/doc updates
- acceptance criteria above are satisfied
- regression tests for the confirmed bug set exist and pass
- Railway deployment checklist has been completed successfully
- `PROJECT_HANDOFF.md` and `README.md` match the actual shipped behavior
- no known release-blocking issues remain in the main converter path

If any of those are still open, the repo may be improved, but it is not build-complete.

## Operational Notes

- The main app uses `PERSIST_DIR` under temp storage by default.
- Session directories are **pruned** when older than `SESSION_TTL_HOURS` (throttled, on incoming requests)—not a guarantee of immediate deletion.
- The companion config generator is **local-only for this build** (see **Build Decisions For This Build**); do not deploy it on Railway unless a future handoff explicitly expands scope and hardening.
- The JSON stable heading map path is the supported permalink-continuity mechanism today.
- If a function body is uncertain, the historical monolith backup may still be a useful reference:
  - `C:\Python Projects\originalWord_HTML\Word_HTMLV4\word_to_wordpressV4.py`

## What To Trust

Trust **this handoff** for:

- What the **code does today** versus what is **broken or unsafe**
- **Locked build decisions**, **phase plan**, **acceptance criteria**, **definition of done**, and **Railway** expectations

Trust **`README.md`** for:

- Local setup, operator workflow, file layout, and environment variable **descriptions** — it explicitly defers **release readiness** and **current blockers** to this file (see the README introduction and links here)

**Conflict rule:** If `README.md` and this file disagree on **whether the app is production-ready**, **what is in scope for this build**, or **what is currently broken**, **this handoff wins** until both documents are updated together (usually at the end of the build per **Definition Of Done**).

Do not trust old claims that:

- all core modules are fully verified and complete
- the repo is already deployment-ready **without** running the Railway / smoke checklists
- CSV/XLSX heading-map upload is supported *(removed; JSON only)*
- automated tests cover every acceptance criterion *(see **Residual gaps** and fix **#9 Partial**)* 

## Next Step

For **new implementation work**, use **Priority Order** and **Residual gaps**. For **verification**, run **External re-audit checklist** and **Railway release checklist**. When closing a release, satisfy **Definition Of Done** and refresh **`README.md`** alongside this file.
