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

All five pages render from `templates/` with Jinja autoescaping; the route
handlers build plain data structures (row dicts, per-paragraph reference dicts)
and hand them to templates. No HTML string-building lives in Python.
CSRF tokens come from Flask-WTF's `csrf_token()` Jinja global.

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

`python -m pytest tests/ -q` — **125 tests.** Runtime deps in
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
decisions, not code quality: the codebase is well-structured, tested (125 tests),
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
