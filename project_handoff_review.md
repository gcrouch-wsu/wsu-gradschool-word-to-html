> **Historical — superseded.** This note was written **2026-04-15** against an **older** `PROJECT_HANDOFF.md` and codebase (line numbers and claims will not match today). For current scope, fixes, and audits, use **`PROJECT_HANDOFF.md`** only.

---

# Phase 1 — `PROJECT_HANDOFF.md` validation

Date: 2026-04-15. Production code was not modified.

---

## One-paragraph verdict

`PROJECT_HANDOFF.md` is an unusually strong **problem statement and release checklist**: major defects it lists (XSS-class handling, `main` vs `div.manual` round-trip, missing `load_heading_map_file`, bundle/manifest vs `stable_heading_map.json`, ignored `preserve_numbers` on bundle import rebuild, duplicate-reference replacement, permissive DOCX links, Docker vs `$PORT`, unused `SESSION_TTL_HOURS`, ZIP `extractall` without caps, no tests) all match the code when spot-checked and reproduced. The document has also gained **Build Decisions**, **Build Plan**, **Acceptance Criteria**, and **Required Regression Tests**, which materially improve executability. It is **not yet** a fully reliable single build order, because four **scope decisions** are explicitly still open, **`README.md` still contradicts** deployment readiness, and the **“Priority Order”** section and **“Build Plan”** phases disagree on where **duplicate-reference work** sits relative to **bundle fidelity**—enough that a team could implement in conflicting sequences without reconciling the doc first.

---

## Confidence score: 0–100

**77 / 100** as a **reliable build spec** (accuracy + internal consistency + enough decisions locked to start coding without rework risk).

- **Diagnosis vs code:** ~**90** (claims checked match implementation).
- **Execution readiness:** ~**65** (open product/ops decisions; ordering tension; README drift; no chosen sanitizer/test stack in the doc).

**Threshold:** Proceed only if confidence **> 80**. **Not met.**

---

## Confirmed claims

Evidence is from the current repo unless noted.

- **Not deployment-ready (internet-facing):** `Dockerfile:24` (`8080` bind); `config.py:8` (`FLASK_SECRET_KEY` default); narrow HTML stripping `core/html_processor.py:286-294`; unsafed template output `word_to_wordpressV4.py:709`, `767`, `769`, `890`.
- **JSON stable heading map path works:** `word_to_wordpressV4.py:692-700`, `core/html_processor.py:853-884`; save artifact `core/html_processor.py:268-284`.
- **`load_heading_map_file` missing (runtime `NameError` if hit):** calls `word_to_wordpressV4.py:313`, `340`; no definition in repo; `hasattr(word_to_wordpressV4, "load_heading_map_file")` is false (repro run).
- **`strip_html_assets` insufficient:** `core/html_processor.py:286-294`; repro: output still contained `onerror` for crafted input.
- **`is_bad_docx_link` allows `javascript:`:** `core/docx_processor.py:888-898`; repro returned `False` for `javascript:alert(1)`.
- **`extract_manual_fragment` + exporter grid broken:** `build_manual_grid_block` uses `<main class="manual">` `core/html_processor.py:906`; import helper looks for `div.manual` inside grid `317-330`; repro returned literal `'None'`.
- **Reference replacement ignores offset (duplicate same-text bug):** `core/html_processor.py:745-769`; repro produced `See SECOND and again FIRST.` for two controlled edits.
- **Bundle: session write before `save_stable_heading_map`:** `word_to_wordpressV4.py:2606-2617`; manifest `stable_heading_map` from `session_data` `2795`; ZIP may include fresher `stable_heading_map.json` `2807-2809`; import uses manifest only for map `3032-3033`, not preferring extracted JSON file.
- **Bundle import ignores `preserve_numbers` in rebuild:** `3066` loads flag; `3030-3031` always strip numbers and `apply_css_counter_numbering(..., preserve=False)`.
- **ZIP traversal checks, no decompressed size cap:** `2945-2960`, `2961`.
- **`SESSION_TTL_HOURS` unused in app:** defined `config.py:9`; grep shows app does not reference it (only docs/config).
- **Download scans all session dirs:** `2648-2657`.
- **Companion app local-default risk:** `docx_config_generator.py:32`, `2609-2612`.
- **Flask `__main__` honors `PORT`; Docker does not:** `word_to_wordpressV4.py:3111-3121` vs `Dockerfile:24`.
- **Hard limitation list-marker workaround:** `wordpress.js` (`forceListStyles` ~`181+`).
- **Pandoc `reference_doc` optional, unused in app calls:** `core/pandoc_wrapper.py:21-23`; all `run_pandoc(` call sites are two-arg only `word_to_wordpressV4.py:983`, `2482`, `3019` — consistent with handoff note `PROJECT_HANDOFF.md:76-78`.
- **No automated tests present:** no `tests/` or `test_*.py` found in layout review; `python -m compileall word_to_wordpressV4.py docx_config_generator.py core utils` **succeeded** (syntax only).
- **Cheap static checks:** grep for `|safe`, `extractall`, `SESSION_TTL_HOURS`, `PORT`, `gunicorn`, `load_heading_map_file`, `csrf` matched the handoff’s implications (e.g. no `csrf` matches; `extractall` at `word_to_wordpressV4.py:2961`).

---

## Rejected or narrowed claims

- **“Consolidated `next_build.md` / `next_build_validation.md`” (`PROJECT_HANDOFF.md:70`):** **Narrowed** — in **this** workspace those filenames are absent from the root doc set; consolidation is plausible but **not git-proven** here (cannot distinguish deleted vs never tracked).
- **“Preview output is safe for the chosen deployment threat model” (`PROJECT_HANDOFF.md:476` acceptance):** **Narrowed** — it is a **target** criterion, not a statement of current truth; today preview still uses `|safe` with pipeline output (`word_to_wordpressV4.py:767`, `2622`).
- **Railway checklist “Confirm Dockerfile binds … `$PORT`” (`PROJECT_HANDOFF.md:559`):** **Narrowed** — reads as **post-fix** verification; **current** `Dockerfile:24` still binds `8080` (the checklist is aspirational, which is fine if readers understand that).

---

## Unverified claims

- **Handoff “Last updated” date (`PROJECT_HANDOFF.md:3`):** not validated against commit history in this pass.
- **End-to-end browser XSS / exploitability:** string-level repros and static review only; no headless browser verification.
- **Railway runtime smoke** (container boot, health, real `$PORT`): not executed in this environment.
- **Optional monolith backup path** (if still mentioned elsewhere in the full handoff): not checked on disk (path outside repo).

---

## Missing material issues

*(Gaps relative to what implementation still needs, not necessarily omissions from the handoff narrative.)*

1. **`README.md` vs handoff:** `README.md:14` still presents the app as broadly **Deployable** on Railway/Docker while the handoff correctly says not internet-ready until fixes — **stakeholder/confidence risk** until reconciled (`PROJECT_HANDOFF.md:578` already asks for this).
2. **No release-blocking *undocumented* code bug found** in this pass beyond what the handoff already lists; the notable **extra** nuance is **`numbering_mode` absent** from bundle-import `session_data` (`word_to_wordpressV4.py:3052-3077`) while `do_convert` synthesizes defaults (`2419`), which can add silent drift alongside manifest omissions (`2786-2801`).
3. **No CSRF** in codebase (grep `csrf` / `CSRF` / `WTF`: empty); handoff ties this to **Security posture** decision (`PROJECT_HANDOFF.md:382-384`) — correct, but for internet-facing scope it is **material** and easy to miss if only “enhancements” are read.

---

## Ambiguities blocking implementation

1. **Explicit open decisions (`PROJECT_HANDOFF.md:366-386`):** CSV/XLSX vs remove UI; companion deploy vs local-only; persistence strategy; internal vs internet-facing (drives CSRF/session strictness). Until recorded (even as one-line ADRs in the handoff), scope and acceptance for items 3 and 6–8 remain fluid.
2. **Ordering contradiction inside the handoff:** **Priority Order** puts **session bundle fidelity** before **duplicate reference replacement** (`PROJECT_HANDOFF.md:356-360`), while **Build Plan Phase 2** bundles duplicate-reference fixes **before** **Phase 3** heading map and bundle work (`PROJECT_HANDOFF.md:408-432`). Both orderings can be defended, but **the document disagrees with itself**, which violates the user’s “no unresolved scope ambiguity that would materially change implementation order” gate.
3. **Technology choices not fixed in the doc:** HTML sanitizer library / policy (allowlist depth), test runner, and how strictly to enforce `FLASK_SECRET_KEY` at **process start** vs documentation-only are unspecified — acceptable for a senior team, but below the bar for “>80% spec-driven confidence” without a short tech addendum.

---

## Recommendation

**Do not build yet.**

### What to correct in `PROJECT_HANDOFF.md` before implementation should begin

1. **Reconcile “Priority Order” (`352-364`) with “Build Plan” phases (`388-465`)** — especially whether **duplicate-reference correctness** is sequenced **with** HTML container fixes (Phase 2) or **after** bundle work (Priority list). Pick one canonical order and delete or cross-reference the other.
2. **Resolve or record the four “Build Decisions Needed Up Front” (`366-386`)** in the document (chosen option per item), so implementers are not guessing scope.
3. **Either update `README.md` to match the handoff** or add an explicit banner in `README.md` that **`PROJECT_HANDOFF.md` overrides** marketing language until the build is complete (the handoff’s own checklist already calls this out at `578`).
