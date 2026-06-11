# Project Specification — WSU Manual Converter

Authoritative description of what this application **is** and the invariants it
upholds. It documents current behavior, architecture, and the design decisions
behind them. Keep it in sync with the code: when a change alters user-visible
behavior, an invariant, or the module layout, update this file in the same
change set.

For setup and step-by-step usage see `README.md`; for the in-app editor guide
see `instructions.md`; for the companion config generator see
`README_config_generator.md`.

---

## 1. Purpose

A Flask web application that converts Word (DOCX) policy/procedure manuals into
WordPress-ready HTML for Washington State University's administrative manuals.

Core goals:

- Convert DOCX manuals into reviewed, publishable HTML via Pandoc plus a
  custom post-processing pipeline.
- **Preserve stable heading anchor IDs across editing cycles** so existing
  WordPress permalinks keep working when a manual is revised.
- Let an editor review heading number mappings, internal references, and table
  formatting before export.
- Export the full asset set for WordPress publishing: HTML fragment, standalone
  HTML, fragment+CSS, site CSS, site JS, regenerated DOCX, heading map, and a
  session bundle (ZIP of all session state).

Runtime posture: **local-first, small trusted team.** A Railway/Docker path
exists; treat large-scale/internet-facing deployment as a separate hardening
exercise. **Tier-1 authentication** (env-configured accounts + per-session
ownership) is implemented and enabled by setting `AUTH_OWNER_*`/`AUTH_USERS`; it
is off by default for local dev (see §8 and §16).

### Scope & non-goals

Deliberate boundaries — changing any of these is a product decision, not a bug fix:

- **Heading maps are JSON only.** CSV/XLSX upload is not supported.
- **Permalink matching is exact**, on normalized heading text (plus the stable
  map). There is no fuzzy/approximate signature matching — looser matching would
  risk wrong-anchor collisions.
- **The companion config generator is local-only** and not part of the
  deployment target; exposing it would be a separate, separately-hardened
  initiative.
- **Session/export state is instance-local** (local filesystem under
  `PERSIST_DIR`). There is no external/durable persistence backend; state is not
  preserved across instance replacement.
- **DOCX export uses plain Pandoc output plus local post-processing**, never
  `--reference-doc` (see §15 hard constraints).

---

## 2. Architecture & module layout

The application is split by responsibility. The Gunicorn / CLI entry point is
`word_to_wordpressV4:app`.

```
word_to_wordpressV4.py    Entry point only (≈40 lines): imports the app, registers
                          routes, runs startup checks, launches the dev server.
webapp.py                 Flask app object, configuration, CSRF, before_request
                          hooks (session prune, one-shot Pandoc startup check),
                          RequestEntityTooLarge handler, startup Pandoc checks.
config.py                 Env-backed settings, PERSIST_DIR, SessionDir, UUID
                          validation (is_valid_session_id).
auth.py                   Tier-1 auth: env accounts, Flask-Login manager, the
                          login gate's helpers, per-session ownership checks.

routes/                   HTTP layer. Plain @app.route registration (no
                          blueprints) so every url_for endpoint name is stable.
  auth_routes.py            /login, /logout
  pages.py                  /  (home), /instructions, /healthz
  convert_flow.py           /convert, /heading_review, /review, /table_review,
                            /table_review/.../preview, /convert/<id> (do_convert)
  downloads.py              /download/..., /update_theme, /export/<id>
  imports.py                /import_html, /import_bundle
  common.py                 Shared request parsing (heading-map upload).

services/                 Reusable non-HTTP logic.
  session_state.py          load/save session.json and edits.json.
  docx_session.py           Shared DOCX→HTML pre-pipeline and the single
                            canonical session_data builder.

core/                     Conversion machinery (no Flask imports).
  pandoc_wrapper.py         Pandoc invocation (both directions), version checks,
                            throttled upstream-release check.
  docx_processor.py         DOCX preprocessing, numbering, hyperlink extraction,
                            style maps, DOCX post-fixups.
  html_processor.py         HTML pipeline, heading IDs, prefix stripping, CSS
                            counter numbering, sanitization, grid block builder,
                            stable heading map.
  manual_structure.py       Heading scraping, crosswalk, numbering conversion.
  reference_linking.py      Reference / external-link extraction.
  styling.py                Theme CSS, table CSS, WP CSS/JS loaders.
  permalinks.py             Heading signature normalization, ref normalization.

utils/
  helpers.py                roman_to_int, int_to_roman/letters, number formatting.
  url_policy.py             External href allowlist (is_safe_href).

templates/                Jinja templates (autoescaped): home, instructions,
                          heading_review, review, table_review.

docx_config_generator.py  Standalone companion Flask app (local-only) for building
                          DOCX style/config previews. Shares canonical helpers
                          with core/ and utils/ (see §11).

scripts/                  Standalone maintainer CLI utilities (see scripts/README.md).
tests/                    Pytest suite (see §13).
```

**Invariant:** `core/` and `utils/` contain no Flask imports and no HTTP
concerns; routes hold HTTP/session logic; `services/` holds logic shared by more
than one route. **Page and form HTML lives in `templates/`** (Jinja-autoescaped),
not built by Python string concatenation. The only HTML assembled in Python is
the *generated manual output* — the accessible grid/TOC block, export fragments,
standalone wrappers, and asset tags — produced by `core/html_processor` and the
download route.

---

## 3. HTTP endpoints

| Method | Route | Handler | Purpose |
|---|---|---|---|
| GET | `/` | `index` | Home / upload page (and preview after conversion). |
| GET | `/instructions` | `instructions` | Renders `instructions.md`. |
| GET | `/healthz` | `healthz` | Liveness probe → `{"status":"ok"}`. |
| GET/POST | `/login` | `login` | Sign-in form / credential check (when auth is enabled). |
| POST | `/logout` | `logout` | Sign out. |
| POST | `/convert` | `convert` | Upload DOCX, start a session, run the pre-pipeline. |
| GET/POST | `/heading_review/<uuid>` | `heading_review` | Review/edit the heading crosswalk. |
| GET/POST | `/review/<uuid>` | `review` | Review/edit internal references. |
| GET/POST | `/table_review/<uuid>` | `table_review` | Table formatting options. |
| POST | `/table_review/<uuid>/preview` | `table_review_preview` | Live table-style preview (JSON). |
| GET | `/convert/<uuid>` | `do_convert` | Run the conversion and render the preview. |
| GET | `/download/<uuid:session_id>/<uuid:token>/<kind>` | `download` | Download an export artifact. |
| POST | `/update_theme` | `update_theme` | Persist theme settings; redirect to re-convert. |
| POST | `/export/<uuid>` | `export_session` | Build and return a session-bundle ZIP. |
| POST | `/import_html` | `import_html` | Import a saved HTML page, start a session. |
| POST | `/import_bundle` | `import_bundle` | Import a session-bundle ZIP. |

All session routes use Flask's `<uuid:...>` converter; download tokens are also
`<uuid:...>`. CSRF protection (Flask-WTF) covers every POST form. When
authentication is enabled (§8), every endpoint except `/login`, `/logout`,
`/healthz`, and static assets requires a signed-in session.

---

## 4. Conversion workflow

### DOCX path (`/convert` → review steps → `/convert/<id>`)

1. **Upload** (`convert`): save the DOCX, create the session, run the shared
   pre-pipeline (`services/docx_session.run_docx_prepipeline`): preprocess DOCX
   → Pandoc DOCX→HTML → normalize whitespace/images/lists → strip TOC sections.
2. **Heading numbering**: optionally infer heading depth from a style map; strip
   typed heading numbers unless "keep numbers" is set; apply CSS-counter
   numbering.
3. **Scrape + match** (`scrape_new_structure`): assign heading IDs (honoring any
   uploaded stable map), scrape the new heading structure, then either
   auto-match old→new references (`map_new` mode) or build an identity crosswalk
   (`keep_old` mode).
4. **Review steps**: heading crosswalk → references → (optional) table review.
5. **Convert** (`do_convert`): run the unified single-pass BeautifulSoup
   pipeline (`process_html_pipeline`), build the accessible grid block, write the
   export artifacts, regenerate the DOCX, and render the preview.

### HTML import (`/import_html`)

Imports a previously exported HTML page (standalone/fragment/WordPress) instead
of a DOCX. The page is asset-stripped and sanitized, the manual fragment is
located, heading IDs and references are derived, and the flow lands directly in
reference review.

### Session bundle import (`/import_bundle`)

Restores a full session exported earlier (DOCX + edits + manifest, optionally
the stable map). After ZIP validation (§8) and a manifest-path check, it
re-runs the same shared pre-pipeline as `/convert`, driven by the manifest
rather than form fields.

**Invariant:** `/convert`, `/import_html`, and `/import_bundle` all produce a
`session_data` dict through the single builder
`services/docx_session.build_session_data` — the three cannot drift apart.

---

## 5. Session & data model

Sessions are isolated directories under
`PERSIST_DIR` (`%TEMP%/docx2html_wsumanual/<uuid>/` by default), managed by
`config.SessionDir`.

- **`SessionDir(session_id)`** validates the id as a canonical UUID4 (raises
  `ValueError` otherwise) and is **read-only by default**: it creates
  directories only when constructed with `create=True`, which only the three
  session-creating routes do. Looking up an unknown/expired id never writes to
  disk.
- **Stable per-session paths** (properties): `source.docx`, `source.pre.docx`,
  `source.temp.html`, `edits.json`, `stable_heading_map.json`, `manifest.json`,
  `export/output.html`, `export/output.docx`, `session.json`.
- **Per-conversion (token) artifacts**: each `do_convert` issues a fresh
  `uuid` token and writes `{token}_manual.html`, `{token}_manual_raw.html`,
  `{token}_toc.html`, `{token}_wordpress.css`, `{token}_standalone.html`,
  `{token}_docx_source.html`, `{token}_*_numbered.docx`, and `{token}_meta.json`.
  The fragment / fragment+CSS outputs are **built on demand** by the download
  route from `{token}_manual.html`, not persisted. The previous token's artifacts
  are deleted on each re-convert, so a session holds exactly one set.
- **`session.json`** holds workflow state; **`edits.json`** holds the persisted
  reference edits/validations/link-targets. Both are accessed only through
  `services/session_state` (`load_session_data` / `save_session_data` /
  `load_edits_data` / `save_edits_data`).

**Concurrency:** session files are read-modify-written with **no locking**. The
tool assumes a single operator working one session at a time; two tabs on the
same session can clobber each other's last save. `services/session_state` is the
documented chokepoint to add locking if that assumption ever changes.

**Pruning:** a throttled `before_request` hook removes session directories older
than `SESSION_TTL_HOURS` (default 48; `0` disables).

---

## 6. Permalink stability (heading map)

The product's core promise: re-converting an edited manual keeps anchor IDs
stable so WordPress `#anchor` URLs survive.

- A heading's **signature** is its normalized text
  (`core/permalinks.normalize_heading_signature`).
- `core/html_processor.save_stable_heading_map` writes
  `stable_heading_map.json` as **`{signature: [ids in document order]}`** — a
  list per signature, not a single id.
- `_add_heading_ids_impl` consumes the **Nth id for the Nth heading** of a given
  signature; occurrences beyond the recorded list fall through to fresh slug
  generation.
- `parse_heading_id_map_json` accepts structured, bare-list, legacy flat
  `{sig: id}`, and current `{sig: [ids]}` shapes, always returning the list form.

**Invariant (idempotency):** applying the regenerated stable map to the same
document yields identical IDs across reruns, **including documents with
duplicate heading text**. (A flat `{sig: id}` map was lossy for duplicates and
made IDs drift `overview` → `overview-1` → `overview-1-1` on each rerun; the
list form prevents this and the preview cache relies on it.)

**Compatibility:** the on-disk/downloaded heading map is the list form. Old
flat-format maps still upload and apply (coerced to one-element lists).

---

## 7. Preview caching

`GET /convert/<id>` is idempotent for unchanged inputs and does not re-run
Pandoc on every refresh.

- `_preview_cache_key()` (in `routes/convert_flow.py`) is a sha256 over **every
  output-affecting input**: the full `pipeline_config` (crosswalk, reference and
  heading edits, stable map, table alignment), theme settings/id, manual type,
  filename, the source-file content hash (`source.pre.docx` or `import.html`),
  and an `assets_hash` of `wordpress.css` + `wordpress.js`.
- On a key match the preview is re-rendered from the saved `{token}_*`
  artifacts (zero Pandoc runs, same token). Any review save, theme change,
  source change, or static-asset edit changes the key → re-convert with a fresh
  token and old-artifact cleanup.
- After each real conversion the stored key is recomputed using the
  just-regenerated stable map, so the very next refresh is a cache hit rather
  than a wasted reconversion (safe because §6 guarantees idempotency).

**Known limitation:** Python pipeline *code* changes are not part of the key, so
a deploy that changes pipeline logic without changing any input can serve a
stale same-session preview until an input changes. Acceptable because a deploy
restarts the process and sessions are short-lived temp directories.

---

## 8. Security model

- **Authentication (Tier 1, `auth.py`).** Optional, env-configured accounts with
  Flask-Login signed-cookie sessions (keyed by `FLASK_SECRET_KEY`). Auth is
  **enabled only when at least one account is configured** (`AUTH_OWNER_EMAIL`/
  `AUTH_OWNER_PASSWORD`, and/or `AUTH_USERS` = `email:hash` entries); with none
  set the app runs open (local-dev default). When enabled, a global
  `before_request` gate requires a signed-in session for every endpoint except
  `/login`, `/logout`, `/healthz`, and static. Passwords are scrypt-hashed
  (`werkzeug.security`); the login cookie is httpOnly, SameSite=Lax, and Secure
  when deployed (`PORT` set). This is account-list auth for a small trusted team,
  not an identity provider — see §16 for the SSO/multi-user trajectory.
- **Per-session ownership.** Each converter session records the creating user
  (`owner` in `session.json`); session and download routes reject access when the
  signed-in user is not the owner (no-op when auth is disabled). This isolates
  one user's in-progress conversions from another's.
- **Session/token identifiers** are server-generated UUID4s. Routes use
  `<uuid:...>` converters (malformed → 404 before handler code); `SessionDir`
  rejects non-UUID ids; `update_theme` validates its form-supplied id with
  `is_valid_session_id`.
- **Bundle ZIP import** rejects archive members with absolute paths, `..`
  segments, or any resolved target outside `session.root`, and caps uncompressed
  size and file count (`ZIP_MAX_UNCOMPRESSED_BYTES`, `ZIP_MAX_FILES`) before
  `extractall`.
- **Bundle manifest paths** are a second trust boundary (their contents are
  arbitrary JSON). `manifest["files"]["docx"|"edits"]` must be a plain basename
  (`nm == os.path.basename(nm)`, not `.`/`..`) **and** an actual file member of
  the archive, checked before any `session.root` join / `compute_sha256` /
  `shutil.move`. This blocks the pathlib absolute-join escape
  (`session.root / "/abs/path"` → `/abs/path`).
- **HTML sanitization**: imported/exported manual HTML passes through
  `sanitize_manual_html_fragment` (bleach) with an allowlist of tags/attributes,
  `http`/`https`/`mailto` protocols, and a `CSSSanitizer` (tinycss2) permitting
  only the two inline properties the pipeline emits (`list-style-type`,
  `text-align`).
- **External hrefs**: links surfaced in the review UI and applied to exports are
  filtered through `utils/url_policy.is_safe_href` (internal anchors, http(s),
  mailto only); unsafe schemes (`javascript:`, `data:`, …) are dropped/rendered
  as plain text.
- **Template output** is Jinja-autoescaped. Server-built HTML strings (e.g. the
  reference-highlight markup) escape their components before assembling and are
  wrapped in `Markup` only after.
- **CSRF** protection applies to all POST forms; **upload limits**:
  `MAX_CONTENT_LENGTH` 200 MB (file uploads), `MAX_FORM_MEMORY_SIZE` 16 MB
  (non-file fields).
- **Pandoc** is invoked with argument lists (never shell strings); stderr is
  captured and logged on failure.
- **Secrets**: `FLASK_SECRET_KEY` defaults to `dev-secret` for local use only and
  must be overridden in any deployed environment.

---

## 9. Pandoc version policy

- A known-good version is pinned: `PANDOC_PINNED_VERSION` (default `3.9.0.2`) in
  `config.py`, `ARG PANDOC_VERSION` in the `Dockerfile`, and the prerequisite in
  `README.md` — bump all three together.
- At startup the app logs the installed version, warns if older than the pin,
  and (throttled, cached, network-failure-silent) emits an INFO line if a newer
  upstream release exists. It never auto-upgrades and never blocks startup.
- The startup check runs once per worker (eagerly under `python
  word_to_wordpressV4.py`, lazily on first request under Gunicorn).
- `check_min_version` returns `False` for a `None`, older, or **unparseable**
  installed version (it does not treat an unknown version as satisfying the pin).

**Adopting a newer Pandoc (human-gated):** review the Pandoc changelog for
changes to DOCX reading, HTML/DOCX writing, table handling, or heading IDs; bump
the pin in all three places in one commit; upgrade the local install; rerun the
suite and smoke-test a real manual; rebuild the image and smoke-test the deploy
target.

---

## 10. Templates & rendering

All pages render from `templates/` with Jinja autoescaping; the route
handlers build plain data structures (row dicts, per-paragraph reference dicts)
and hand them to templates. CSRF tokens come from Flask-WTF's `csrf_token()`
Jinja global.

**Allowed exception:** the home/preview routes (`routes/pages.py:index`,
`do_convert`) wrap the app's own trusted `wordpress.css` / `wordpress.js` text in
`<style>`/`<script>` tags and pass them through `|safe` for the live preview,
and the download route assembles the generated manual output (grid/TOC block,
export fragments, standalone wrapper). These are generated-output/asset tags
built from trusted local content, not user-derived page HTML — consistent with
the §2 invariant.

---

## 11. Companion config generator

`docx_config_generator.py` is a separate, local-only Flask app for building DOCX
style/config previews (see `README_config_generator.md`). It imports the
**canonical** implementations of shared helpers from `core/` and `utils/`
(`is_heading_style`, `serialize_sequence_map`, `_extract_numbering_defs`,
heading-prefix token helpers, `_norm_char`/`_normalized`, `_int_to_roman`,
`_int_to_letters`) rather than carrying its own copies. `tests/` asserts these are
the *same objects* so the two apps cannot drift.

It deliberately keeps a few generator-specific helpers (e.g. a `_HEADING_PREFIX_RE`
that additionally strips spelled-out chapter words like "Chapter One" for style
previews; preview-only prefix helpers). The three `_HEADING_PREFIX_RE` copies
(html_processor, docx_processor, generator) are pinned by a parity test;
html_processor and docx_processor are behaviorally identical.

---

## 12. Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `PERSIST_DIR` | system temp | Root for session storage. |
| `FLASK_SECRET_KEY` | `dev-secret` | Session/login cookie signing key; override in production. |
| `AUTH_OWNER_EMAIL` / `AUTH_OWNER_PASSWORD` | (unset) | A single convenience account (plaintext password, hashed at load). Enables auth. |
| `AUTH_USERS` | (unset) | Additional accounts: comma/newline list of `email:password_hash` (hashes from `scripts/make_password_hash.py`). Enables auth. |
| `SESSION_TTL_HOURS` | `48` | Prune sessions older than this (`0` disables). |
| `ZIP_MAX_UNCOMPRESSED_BYTES` | 200 MB | Bundle import uncompressed cap. |
| `ZIP_MAX_FILES` | `5000` | Bundle import file-count cap. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `PANDOC_PINNED_VERSION` | `3.9.0.2` | Minimum known-good Pandoc. |
| `PANDOC_UPDATE_CHECK_ENABLED` | `1` | Disable the upstream-release check with `0`. |
| `PANDOC_UPDATE_CHECK_TTL_HOURS` | `168` | Cache duration for that check. |
| `PANDOC_UPDATE_CHECK_TIMEOUT_SECONDS` | `3.0` | Network timeout for that check. |
| `PORT` | (unset → 5000 local) | Server port; presence selects deployed mode. |

---

## 13. Testing

`python -m pytest tests/ -q` — **131 tests.** Runtime deps in
`requirements.txt`; test deps add `pytest` via `requirements-dev.txt`. CI
(`.github/workflows/ci.yml`) installs the pinned Pandoc and the ranged
requirements and runs the suite on every push to `main` and every PR.

Coverage by area:

- **Unit/pipeline**: heading-prefix stripping and three-way regex parity;
  crosswalk numbering conversion and auto-matching; permalink signatures;
  duplicate-aware stable map (idempotency, legacy back-compat); HTML
  sanitization; URL policy; manual-grid/fragment building; config-generator
  dedup (same-object assertions); Pandoc version comparison.
- **Routes/e2e** (Pandoc required; skipped with the detected version named if the
  installed Pandoc is older than the pin): full upload→review→convert→download
  flow across all download kinds; permalink stability across two conversions;
  preview cache hit on refresh and bust on theme/CSS change; bundle
  export→import round trip; HTML re-import; CSRF enforcement; session/token
  hardening; bundle manifest-path rejection; review-page href filtering.
- **Auth** (`test_auth.py`): login gate redirects, public-endpoint allowlist,
  login success/failure, logout, and per-session ownership isolation (one user
  cannot reach another's session).

Test fixtures generate a small DOCX with python-docx at test time (no binary is
committed; the `*.docx` gitignore rule stays intact).

---

## 14. Deployment

- **Docker** (`Dockerfile`): `python:3.12-slim`, installs the pinned Pandoc
  `.deb` (amd64/arm64), installs from `requirements.lock.txt`, runs as a
  non-root `app` user, defines a `HEALTHCHECK` against `/healthz`, and serves via
  Gunicorn binding `0.0.0.0:${PORT}` (default 8080).
- **Lockfile** (`requirements.lock.txt`): exact pins for the full runtime
  closure, resolved for the Docker target platform (py3.12 / manylinux2014),
  used only by the Docker build for reproducibility. The ranged `requirements*.txt`
  are used for local dev and CI so incompatible upstream releases surface in CI
  first. Regeneration instructions are in the lockfile header.

### Railway / operational contract

Railway is the intended deployment target. The contract:

- Deploy **only the main app** (`word_to_wordpressV4:app`); the companion
  generator is not part of the target.
- The container must bind the injected `$PORT` (the `Dockerfile` `CMD` does).
- `FLASK_SECRET_KEY` must be set in the environment — never rely on the
  `dev-secret` default (code cannot force a secret).
- Pandoc must be present in the runtime image (the Docker build installs the
  pinned `.deb`).
- `PERSIST_DIR` is **instance-local and non-durable**: in-progress sessions,
  bundles, and exports do not survive redeploys/restarts/instance replacement.
  Session-lifecycle pruning (`SESSION_TTL_HOURS`) is therefore part of deployment
  correctness, not just cleanup.

Pre-deploy smoke check: the container boots; Pandoc is present and its logged
version matches `PANDOC_PINNED_VERSION` (no "older than pinned" warning);
`/healthz` returns 200; the app is reachable on `$PORT`.

---

## 15. Known constraints & future candidates

### Hard constraints (do not re-open casually)

- **Pandoc `--reference-doc` has produced corrupt DOCX** in this project's
  history. DOCX export therefore uses plain Pandoc output plus local
  post-processing (`fix_numbering_xml`, `sanitize_docx_styles`,
  `relocate_body_level_bookmarks`). `core/pandoc_wrapper.run_pandoc` still exposes
  an optional `reference_doc` parameter, but no app flow passes one.
- **Some WordPress theme list-marker behavior is corrected in `wordpress.js`
  after load** (`forceListStyles`), which can cause brief visible flicker.

### Future candidates (none urgent, nothing blocking)

- Extract `review()`'s POST-save block and `do_convert()`'s artifact-export block
  into service functions (currently single-call-site, no duplication).
- Consolidate the per-reference `<script>` block in `review.html` into one
  delegated handler.
- Add per-session file locking if the single-operator assumption changes (§5).
- Fold a hash of the pipeline source into the preview cache key if stale
  same-session previews after a code-only deploy become a concern (§7).
- **Free-form HTML body edits without re-importing Word** — allow small
  corrections (typos, wording, minor markup) to the converted body without a new
  DOCX upload. Non-trivial: it requires choosing a new source of truth (edited
  HTML vs original DOCX), persisting overrides in the session, and defining
  invalidation rules for heading signatures, permalink/heading-map stability,
  reference offsets, and DOCX round-trip. A minimal "edit fragment, save,
  continue export" path still needs explicit product rules and QA; a full WYSIWYG
  editor (sanitization, tables, accessibility, undo) is a larger investment.

---

## 16. Production readiness

**Verdict.** The application is **ready for its designed scope** — a small set of
trusted users, single Railway instance, with **Tier-1 authentication enabled**
(see below). It is **not yet ready as a large-scale public, multi-tenant service**
without the remaining items. The limiting factors are scope and architecture
decisions, not code quality: the codebase is well-structured, tested (131 tests),
and hardened on the paths exercised so far.

### Authentication — Tier 1 (implemented)

Env-configured accounts + Flask-Login signed-cookie sessions + per-session
ownership (§8). Enabled by setting `AUTH_OWNER_*` and/or `AUTH_USERS`; off by
default for local dev. This closes the "anyone who can reach it can use it" gap
for a trusted team and gates the expensive Pandoc operation behind login. It is
**account-list auth, not an identity provider** — there is no self-service signup,
password reset, or directory integration, and accounts live in env vars (no
database).

### Remaining blockers for large-scale / institutional deployment

1. **User management at scale / SSO.** Tier 1 handles a small fixed set of
   env-defined accounts. Genuine per-person accounts with self-service and audit
   need a database (**Tier 2**); for an institutional public app the right answer
   is likely **SSO/OIDC (Azure AD / Shibboleth)** (**Tier 3**) rather than local
   passwords.
2. **Single-instance constraint.** Sessions live on the local filesystem (§14), so
   the app must run as **one Railway instance** (optionally with a mounted volume
   for restart durability). Horizontal scaling needs shared storage first.
3. **Abuse / DoS protection.** Each conversion spawns Pandoc (CPU/memory heavy).
   Login now limits this to authenticated users, but there is still no rate
   limiting or concurrency cap for a logged-in user.
4. **Concurrency safety.** Session state is read-modify-written with no locking
   (§5). Per-user ownership prevents cross-user collisions, but the same user in
   two tabs on one session can still clobber a save.
5. **Durability & operations.** `PERSIST_DIR` is ephemeral (§14); there is no
   monitoring, alerting, or log aggregation, and the Railway release checklist
   (§14) has not been executed on a real deploy.

### Validation gap (independent of deployment model)

- **Real-document coverage is thin.** The automated suite runs against a small
  synthetic DOCX. The conversion's correctness on **real manuals** (nested
  tables, footnotes, tracked changes, irregular Word styles and numbering) is not
  yet evidenced. Before trusting output for publication, run the actual target
  manuals end-to-end and have a human verify output quality. This is the highest
  product risk regardless of where the app runs.

### Pre-production checklist

1. ✅ Tier-1 authentication + per-session ownership (set `AUTH_OWNER_*`/`AUTH_USERS`).
2. Run the real target manuals through the full flow; human-verify output.
3. Execute the Railway release checklist (§14) on a single instance; decide the
   `PERSIST_DIR` volume/persistence story.
4. Add a conversion rate limit / concurrency cap if exposed to many users.
5. Add monitoring, error alerting, and log aggregation.
6. For scale or institutional rollout: plan Tier 2 (DB users) or Tier 3 (SSO).
7. Commission a security review appropriate to the exposure (the code reviews to
   date are not a penetration test).

---

## 17. Full-repo audit findings (2026-06-11)

Baseline checks:

- `python -m pytest tests/ -q`: **125 passed in 15.26s**. No e2e/auth skips;
  local Pandoc was detected as 3.9.0.2 during later startup probes.
- `python -m pyflakes word_to_wordpressV4.py webapp.py auth.py routes/ services/ core/ utils/ docx_config_generator.py`:
  failed on unused imports/locals; see finding 10.
- Git history skimmed: latest auth/refactor/hardening commit is
  `8a1d43c`; prior Pandoc startup work is `3669dd9`; earlier broad hardening is
  `49ee9d3`.

Findings:

1. **Auth-enabled default-secret sessions are forgeable.**
   - Verdict: confirmed bug / hardening.
   - File: `config.py:9`, `webapp.py:43`, `auth.py:107`.
   - Severity: high.
   - Evidence: with auth enabled and `app.secret_key == "dev-secret"`, a Flask
     session cookie signed with the known default and payload
     `{"_user_id": "alice@wsu.edu"}` reached `/` with HTTP 200, without a
     password. Flask-Login's user loader accepts any configured email in the
     signed session.
   - Minimal fix: refuse startup when `auth_enabled()` and
     `FLASK_SECRET_KEY` is unset, `dev-secret`, or otherwise explicitly
     insecure. My recommendation is a hard fail whenever auth is enabled; at
     minimum hard fail when `PORT` is set. Add a regression test that a forged
     default-secret cookie cannot authenticate.

2. **Bundle import can plant a forged download meta file and read arbitrary
   server-readable files.**
   - Verdict: confirmed bug.
   - File: `routes/imports.py:239`, `routes/downloads.py:40`,
     `routes/downloads.py:63`, `routes/downloads.py:99`,
     `routes/downloads.py:101`.
   - Severity: high.
   - Evidence: a valid imported ZIP with normal `manual.docx`, `edits.json`,
     and `manifest.json`, plus an extra `{uuid}_meta.json` whose `docx_path`
     pointed at `PROJECT_SPEC.md`, imported successfully. A subsequent
     `GET /download/<new-session>/<that-token>/docx` returned HTTP 200 with
     body prefix `b'# Project Specification '`. The manifest docx/edits path
     policy held, but arbitrary extra archive members remain in the session
     root and the download route trusts paths from meta JSON.
   - Minimal fix: in `download()`, derive artifact paths from
     `session.root` + `token` instead of trusting meta path fields, or require
     every meta path to resolve under the current `session.root`/export
     directory before `exists()`/`send_file()`. Also reject or delete imported
     `{uuid}_*` artifact/meta members during bundle import, and test that a
     planted meta file cannot read outside the session directory.

3. **Ownerless sessions are shared by all authenticated users; the download
   fallback makes this worse.**
   - Verdict: spec-code mismatch / hardening.
   - File: `auth.py:129`, `auth.py:130`, `routes/downloads.py:43`.
   - Severity: medium.
   - Evidence: `session_owner_ok({})` returns true when auth is enabled because
     `owner is None` is accepted. The current session-creating routes do set
     owner (`routes/convert_flow.py:480`, `routes/imports.py:153`,
     `routes/imports.py:356`) and later saves preserve the same dict, but
     ownerless legacy/corrupt sessions and downloads with missing
     `session.json` are not isolated.
   - Minimal fix: when auth is enabled, require `owner == current_uid()` for
     session access. If legacy sessions must be supported, make that an
     explicit migration or temporary compatibility switch, not the default.
     In `download()`, load `session_data` first and reject when it is `None`.

4. **Theme `font_family` can break out of generated `<style>` blocks.**
   - Verdict: hardening.
   - File: `core/styling.py:154`, `core/styling.py:186`,
     `core/styling.py:316`, `core/styling.py:319`,
     `routes/convert_flow.py:1263`, `routes/convert_flow.py:1413`,
     `templates/home.html:8`.
   - Severity: medium.
   - Evidence: `coerce_theme_settings({"font_family":
     "x;}</style><script>alert(1)</script><style>{"}, "chapter")` preserves the
     raw font string, and `build_theme_css()` emits
     `--manual-font: x;}</style><script>alert(1)</script><style>{;`. The normal
     UI does not expose `font_family`, but a crafted POST or bundle manifest can.
   - Minimal fix: allowlist font family values or CSS-escape/sanitize the
     property before interpolation. Re-coerce any `theme_settings` read from
     meta/session/manifest immediately before `build_theme_css()`, and add a
     regression test for `</style>` in theme input.

5. **Imported `keep_old` bundles do not rebuild the identity crosswalk.**
   - Verdict: confirmed bug.
   - File: `routes/imports.py:321`, compared with
     `routes/convert_flow.py:444`-`routes/convert_flow.py:446` and
     `services/docx_session.py:68`.
   - Severity: medium.
   - Evidence: `/convert` uses `build_identity_crosswalk(references)` when
     `mapping_mode == "keep_old"`, but `/import_bundle` always calls
     `auto_match_old_to_new_references(...)` after scraping. A keep-old bundle
     can therefore import with different reference mapping behavior than the
     original session.
   - Minimal fix: import and use `build_identity_crosswalk` in
     `/import_bundle` when the manifest mapping mode is `keep_old`.

6. **Bundle stable-map file fallback is applied, then not persisted into
   `session.json`.**
   - Verdict: confirmed bug / spec-code mismatch.
   - File: `routes/imports.py:310`, `routes/imports.py:313`,
     `routes/imports.py:320`, `routes/imports.py:346`.
   - Severity: low-medium.
   - Evidence: if `stable_heading_map.json` exists, import code loads it into
     local `stable_heading_map` and uses it for `scrape_new_structure()`, but
     `build_session_data()` receives `manifest.get("stable_heading_map", {})`
     instead of the local fallback value. A bundle whose file and manifest map
     differ can scrape with one map and later convert/cache with another.
   - Minimal fix: pass `stable_heading_map=stable_heading_map` to
     `build_session_data()`.

7. **`_safe_next()` avoids the tested open redirects, but CRLF input causes a
   login 500.**
   - Verdict: hardening.
   - File: `routes/auth_routes.py:13`, `routes/auth_routes.py:34`.
   - Severity: low.
   - Evidence: route-level probes with CSRF disabled showed `//evil.com`,
     `%2f%2f...`, and `https:/x` redirect to `/`; `/\evil.com` becomes
     `/%5Cevil.com`. A valid login with
     `next=/%0d%0aLocation:%20https://evil.com` raises Werkzeug's
     "Header values must not contain newline characters" and returns 500.
   - Minimal fix: reject control characters and backslashes before `redirect()`;
     use `urlsplit`/same-origin validation and return `url_for("index")` for
     any parse failure.

8. **`SessionDir` says UUID4, but validation accepts non-v4 UUID-shaped
   strings.**
   - Verdict: spec-code mismatch.
   - File: `config.py:46`, `config.py:49`.
   - Severity: low.
   - Evidence: `is_valid_session_id("00000000-0000-0000-0000-000000000000")`
     and `is_valid_session_id("11111111-1111-1111-1111-111111111111")` both
     returned true. The regex checks lowercase UUID shape, not version/variant.
   - Minimal fix: parse with `uuid.UUID(value, version=4)` and compare the
     canonical string, or update the spec from "UUID4" to "canonical lowercase
     UUID-shaped string."

9. **A small amount of non-manual HTML tag assembly still lives in route code.**
   - Verdict: nit / spec-code mismatch.
   - File: `routes/pages.py:42`, `routes/pages.py:43`,
     `templates/home.html:8`, `templates/home.html:83`.
   - Severity: low.
   - Evidence: the main index route builds `<style>...</style>` and
     `<script>...</script>` strings for local WordPress assets and passes them
     through `|safe`. The generated-output/download paths are expected to do
     this, but §2/§10 currently say page/form HTML lives in templates and the
     exception is generated manual output.
   - Minimal fix: either move those two tags into `home.html` and pass raw
     css/js text, or explicitly document these local asset tags as an allowed
     route-level exception.

10. **Static lint is not clean.**
    - Verdict: nit.
    - File: representative examples include `word_to_wordpressV4.py:15`,
      `word_to_wordpressV4.py:16`, `routes/convert_flow.py:558`,
      `routes/convert_flow.py:1148`, `routes/downloads.py:20`,
      `routes/imports.py:19`, `core/docx_processor.py:5`,
      `core/html_processor.py:1`, `core/styling.py:3`,
      `docx_config_generator.py:980`.
    - Severity: low.
    - Evidence: requested `pyflakes` command exited 1 with unused imports and
      unused locals across the refactor. Some imports are intentional side
      effects/re-exports, but the chosen tool still reports them.
    - Minimal fix: remove true dead imports/locals; for intentional
      registration/re-export imports, use a linter-compatible pattern or switch
      the documented check to a tool/configuration that honors the intentional
      exceptions.

Confirmed controls / false alarms:

- Verdict: false-alarm. File: `webapp.py:61`, `webapp.py:65`-`webapp.py:72`.
  Severity: none. Evidence: enumerated `app.url_map`; with auth enabled,
  unauthenticated `GET /` and `/instructions` redirect to `/login`, public
  `/healthz` and `/login` remain reachable, malformed/unknown routes return
  404/405, and POSTs are stopped by CSRF before handler code. The
  `request.endpoint is None` early return did not expose a sensitive endpoint.
  Minimal fix: none.
- Verdict: false-alarm with caveat from finding 3. File:
  `routes/convert_flow.py:455`, `routes/convert_flow.py:480`,
  `routes/imports.py:134`, `routes/imports.py:153`,
  `routes/imports.py:324`, `routes/imports.py:356`. Severity: none. Evidence:
  `/convert`, `/import_html`, and `/import_bundle` all use
  `build_session_data()` and then set `owner=current_uid()`; later
  `save_session_data()` calls mutate/persist the existing dict and do not drop
  `owner`. Minimal fix: none beyond tightening ownerless behavior.
- Verdict: false-alarm. File: `core/html_processor.py:95`,
  `core/html_processor.py:113`-`core/html_processor.py:119`,
  `core/html_processor.py:1045`, `utils/url_policy.py:4`,
  `routes/convert_flow.py:660`, `routes/convert_flow.py:809`,
  `routes/convert_flow.py:925`. Severity: none. Evidence: sanitizer probe
  stripped `<script>`, event handlers, `javascript:` hrefs, and disallowed CSS
  while retaining allowed `text-align`; review/export links use
  `is_safe_href()` and `sanitize_external_href()`. Minimal fix: none for this
  path.
- Verdict: false-alarm. File: `core/pandoc_wrapper.py:20`-`core/pandoc_wrapper.py:35`,
  `core/pandoc_wrapper.py:46`-`core/pandoc_wrapper.py:54`,
  `core/pandoc_wrapper.py:118`-`core/pandoc_wrapper.py:130`. Severity: none.
  Evidence: Pandoc is invoked via argument lists, not shell strings, and
  `check_min_version()` returns false for missing/older/unparseable installed
  versions. Minimal fix: none.
- Verdict: false-alarm. File: `core/html_processor.py:444`-`core/html_processor.py:504`.
  Severity: none. Evidence: a probe with three-plus duplicate headings across
  interleaved levels produced unique IDs
  `['overview', 'details', 'overview-1', 'overview-2', 'details-1',
  'overview-3']` and stayed identical across three stable-map reruns. Minimal
  fix: none.
- Verdict: false-alarm / not locally verifiable. File: `Dockerfile:5`,
  `config.py:20`, `README.md:31`, `.github/workflows/ci.yml`, and
  `requirements.lock.txt:1`. Severity: none. Evidence: Pandoc pin is
  consistent at 3.9.0.2, Docker installs from `requirements.lock.txt`, and CI
  workflow exists. I did not verify the live Railway deployment or real-manual
  output quality from this local audit. Minimal fix: execute the §14 Railway
  smoke check and real-document QA separately.

Overall go/no-go for the stated scope:

- **No-go as-is for the deployed auth-on app until at least findings 1 and 2
  are fixed.** Production is reportedly using a strong `FLASK_SECRET_KEY`, which
  operationally mitigates finding 1 today, but the code should still hard-fail
  the insecure auth configuration. Finding 2 is an authenticated arbitrary file
  read through bundle import/download metadata and should block even the
  small-trusted-team Railway scope.
- After fixing findings 1 and 2, and preferably the medium hardening/correctness
  items 3-5, the app is a reasonable go for its stated narrow scope: small
  trusted team, single Railway instance, auth enabled, non-durable local
  sessions. This audit did not validate live Railway runtime behavior or
  publication quality on real manuals.

---

## 18. Audit remediation (2026-06-11)

Independent verification and fixes for the §17 findings (each was reproduced
before changing code; Codex's false-alarm classifications were spot-checked and
accepted). Suite after this pass: **131 passing** (was 125; +6 regression tests).

### §17 findings — confirmed and fixed

| # | Severity | Verdict | Fix |
|---|---|---|---|
| 1 | high | confirmed (reproduced forged cookie → 200) | `webapp.py` now hard-fails at startup when auth is enabled with an unset/`dev-secret` `FLASK_SECRET_KEY`, and the request gate aborts 500 if auth is enabled under an insecure secret. |
| 2 | high | confirmed (planted `{token}_meta.json` → read `PROJECT_SPEC.md` via download) | `download()` now requires the path from meta to resolve **inside the session root** (`_within_session`) before opening it, and requires a real `session.json`; `import_bundle` deletes any extracted member that isn't `manifest.json`/docx/edits/`stable_heading_map.json`, so a forged token artifact can't be planted. |
| 3 | medium | confirmed | `session_owner_ok` no longer accepts ownerless sessions when auth is enabled (`owner` must match the signed-in user); `download()` rejects a missing `session.json`. |
| 4 | medium | confirmed (`</style><script>` survived in generated CSS) | `font_family` is sanitized to an allowlisted character set in both `coerce_theme_settings` and at the point of use in `build_theme_css` (covers theme settings read back from meta/manifest without re-coercion). |
| 5 | medium | confirmed | `/import_bundle` now uses `build_identity_crosswalk` for `keep_old` manifests, matching `/convert`. |
| 6 | low-med | confirmed | `/import_bundle` persists the stable map it actually applied (the extracted file when present) into `session.json`, not the manifest's. |
| 7 | low | confirmed (CRLF `next` → 500) | `_safe_next` rejects backslashes, control characters, and any value with a scheme/host; falls back to `/`. |
| 8 | low | confirmed | `is_valid_session_id` now enforces the UUID **v4** version/variant nibbles, not just UUID shape. |
| 9 | low | spec clarification | §10 now documents the home/preview asset `<style>`/`<script>` tags and the download route's generated-output assembly as the allowed exception to "page HTML lives in templates." |
| 10 | low | partially addressed | Removed the dead route-level locals/imports introduced by the refactor; route modules are pyflakes-clean. Remaining pyflakes hits are (a) intentional route-registration/re-export imports in `word_to_wordpressV4.py`/`routes/__init__.py` and (b) pre-existing `core/` imports that are re-export chains or the lxml-availability probe — left as-is to avoid churn/breakage. (Lint is not a CI gate.) |

### Files changed

- `webapp.py` — startup + runtime guard against insecure auth secret.
- `auth.py` — `session_owner_ok` requires a matching owner when auth is enabled.
- `routes/downloads.py` — `_within_session` path containment; require real session; dead-local cleanup.
- `routes/imports.py` — extracted-member allowlist cleanup; `keep_old` identity crosswalk; persist applied stable map; unused-import cleanup.
- `core/styling.py` — `font_family` sanitization (`_sanitize_font_family`).
- `routes/auth_routes.py` — hardened `_safe_next`.
- `config.py` — UUID4 version/variant validation.
- `routes/convert_flow.py` — dead-local/import cleanup.
- `PROJECT_SPEC.md` — §10 asset-tag clarification; this section.

### Tests added / updated

- `tests/test_auth.py` — forged default-secret cookie is rejected; ownerless session not accessible when auth is enabled; the `with_auth` fixture now sets a real secret (required by the new guard).
- `tests/test_routes_hardening.py` — UUID v4 rejection; download rejects out-of-session meta paths; `_safe_next` rejects CRLF/backslash/scheme; `font_family` cannot break out of the `<style>` block; the `docx_ok=False` test now seeds a real session.
- `tests/test_e2e_workflow.py` — `keep_old` bundle import uses the identity crosswalk and persists the stable map (covers §17 #5 and #6).

### Remaining known risks (unchanged from §16/§17)

- **Real-document output quality** is still unvalidated by automated tests — the
  highest product risk; run the actual WSU manuals through end-to-end and
  human-verify before publishing.
- **Live Railway runtime** (boot, `$PORT`, volume/persistence) was not validated
  from this local pass — execute the §14 smoke check on the deploy.
- **No rate limiting / conversion concurrency cap** — acceptable for the small
  trusted team; revisit if exposure widens (§16).
- **Lint is not fully clean** under `pyflakes` due to intentional
  registration/re-export imports (finding 10); not a correctness or security
  issue.

### Go / no-go

**Go for the stated scope** — small trusted team, single Railway instance, auth
enabled with a strong `FLASK_SECRET_KEY`. The two §17 blockers (high-severity
findings 1 and 2) are fixed and regression-tested, and the medium correctness/
hardening items (3–6) are resolved. The standing caveats above are operational/
product validation, not code defects.
