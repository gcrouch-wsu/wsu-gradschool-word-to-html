> **Historical — superseded.** This re-check reflects a **snapshot** of `PROJECT_HANDOFF.md` / `README.md` from **2026-04** before later hardening and doc sync. **Do not use line-number references here against current files.** Authoritative state: **`PROJECT_HANDOFF.md`**.

---

## Remaining mismatches between docs and code

This pass only validates whether the **three prior blockers** and the **re-check questions** are addressed in the **updated** `PROJECT_HANDOFF.md` and `README.md`, against the **current** code. No production code was reviewed for changes (none expected).

### 1. Doc-vs-doc: stale warning inside `PROJECT_HANDOFF.md` about `README.md`

**Issue:** `PROJECT_HANDOFF.md:637-638` still states that `README.md` “still overstates current deployability and round-trip reliability” and that readers should prefer the handoff if README conflicts.

**Counter-evidence (updated README):** `README.md:5-6` explicitly defers release-readiness to `PROJECT_HANDOFF.md`; `README.md:13-14` frames round-trip as **intended** with gaps in the handoff; `README.md:16` describes Railway/Docker as under hardening with blockers in the handoff; `README.md:121-122` tells deployed environments not to rely on default secrets and to follow the handoff.

**Verdict:** The **handoff’s “What To Trust”** subsection is **internally stale** relative to the README it describes. This is a **small but real** documentation contradiction to fix in a future doc edit (no code change required).

### 2. Doc-vs-doc: minor redundancy after locked “Build Decisions”

**Issue:** `PROJECT_HANDOFF.md:386-404` locks the companion app as **local-only** for this build, but `PROJECT_HANDOFF.md:369-370` (“Important Enhancements”) still asks to “Clarify whether `docx_config_generator.py` is local-only or a supported deployed app.”

**Verdict:** **Low severity**—Enhancements are “after required fixes,” but item 7 is now **mostly redundant** with the locked decision. Not blocking execution.

### 3. Code unchanged vs handoff (expected pre-build, not a doc error)

These are **intentional** until implementation lands; the handoff still describes them accurately as current gaps:

| Topic | Code evidence | Handoff alignment |
| --- | --- | --- |
| `load_heading_map_file` | Calls `word_to_wordpressV4.py:313`, `340`; no definition in `.py` | Required Fix 3 (`194-210`) says remove/disable path—**matches** |
| CSRF | No `csrf` / `CSRF` in `.py` (grep) | Required Fix 10 (`341-358`), Phase 4 work (`469`), Acceptance §9 (`540-543`), regression item 8 (`574-575`), checklist item 7 (`605`)—**consistent** |
| `\|safe` / XSS surface | `word_to_wordpressV4.py:709`, `767`, `769`, `890` | Required Fix 1—**matches** |
| ZIP `extractall` | `word_to_wordpressV4.py:2961` | Required Fix 8—**matches** |
| `SESSION_TTL_HOURS` unused in app | `config.py:9`; not referenced from main app in grep | Handoff + README table—**matches** |
| Docker bind | `Dockerfile:24` still `8080` | “Current Railway-specific blockers” (`102-107`) + checklist item 1 (`586`) as **post-fix** confirmation—**matches** |

### 4. Re-check answers (prior findings → now)

1. **Priority Order vs Build Plan:** **Resolved.** `PROJECT_HANDOFF.md:372-384` now orders duplicate-reference work **before** bundle work and **before** Railway/CSRF/ZIP, matching **Phase 2** (duplicate + HTML) then **Phase 3** (CSV removal + bundle) then **Phase 4** (Railway + CSRF + archive/session) (`406-471`). This removes the previous **duplicate-ref vs bundle** sequencing conflict.

2. **Build decisions explicit:** **Resolved.** `PROJECT_HANDOFF.md:386-404` locks CSV/XLSX out for this build, companion **local-only**, persistence **stay instance-local + cleanup/limits/docs**, and **internet-facing** posture with CSRF/secrets/hardening in scope.

3. **Decisions consistent with the rest of the handoff:** **Mostly yes.** Required Fix 3 (`194-210`) matches decision (1); companion local-only matches layout (`34-35`), Railway section (`93-94`), README (`60`); persistence matches Phase 4 / Fix 8; security posture matches new Required Fix 10 and Phase 4 CSRF line (`469`). **Minor** redundancy: Enhancements item 7 (`369-370`) vs locked decision (above).

4. **CSRF in required scope across sections:** **Yes.** Present in Required Fixes **#10** (`341-358`), minimum coverage in Fix 9 (`338`), Phase **4** (`469`), Acceptance **§9** (`540-543`), Required Regression Tests **#8** (`574-575`), Railway checklist **#7** (`605`). **Important Enhancements** no longer treats CSRF as optional-only—consistent with the locked posture.

5. **README defers release-readiness to handoff:** **Yes.** `README.md:5-6` and cross-references at `13-14`, `16`, `60`, `121-122`.

6. **README still materially overstates?** **No longer** on the dimensions previously flagged: deployability (`16`), round-trip (`13-14`), secret/env posture (`121-122`), companion scope (`60`). Remaining feature bullets are framed as product intent, with gaps pointed at the handoff where relevant.

7. **Other contradictions / ambiguities:** Aside from **`What To Trust` vs current README** (`637-638`) and **Enhancements #7 redundancy** (`369-370`), no additional **material** scope contradictions were found in this pass.

8. **Code-vs-doc large enough to stay well below 90?** **No.** The remaining gap is **not** “handoff disagrees with code on what is broken”—it agrees. What keeps the **spec** from a **92+** score is normal **pre-implementation** state: the **code has not yet changed**, CSRF/tests/Docker `$PORT`/heading-map removal are still **work to do**, and the handoff has **one stale paragraph** plus **light editorial cleanup** in Enhancements.

### 5. Cheap validations rerun

| Check | Result |
| --- | --- |
| `python -m compileall word_to_wordpressV4.py docx_config_generator.py core utils` | **Success** |
| `load_heading_map_file` | Still only calls in `word_to_wordpressV4.py:313`, `340` (expected until build) |
| `PORT` / `gunicorn` | `word_to_wordpressV4.py:3111-3112` reads `PORT` for Flask dev; `Dockerfile:11-18`, `24` installs gunicorn but **CMD** still binds `0.0.0.0:8080` (aligns with handoff “current blockers” `102-107`) |
| `SESSION_TTL_HOURS` | `config.py:9`; README table `127` |
| `csrf` in `*.py` | **No matches** (expected until build) |
| `\|safe` / `extractall` | `word_to_wordpressV4.py:709`, `767`, `769`, `890`; `2961` |

**Targeted repros:** Not re-run; prior conclusions still follow directly from the unchanged snippets above. Re-run if any stakeholder disputes the unchanged security posture.

---

## Recommendation

**Proceed to build**

**Confidence in `PROJECT_HANDOFF.md` as a build spec: 88 / 100** (up from **77** on the prior pass).

The three issues that previously capped confidence at 77 are **actually resolved** in the updated `PROJECT_HANDOFF.md` / `README.md`: **Priority Order** aligns with **Build Plan** phases; **Build Decisions** are **locked** and consistent with Required Fixes and Railway/CSRF scope; **README** now **defers** release truth to the handoff and tones down deploy/round-trip claims. Remaining issues are **minor doc hygiene** (`PROJECT_HANDOFF.md:637-638` stale claim about README; redundant **Important Enhancements** item 7 at `369-370`), not reasons to hold implementation.

**Why not 92+:** (1) the stale **What To Trust** paragraph contradicts the updated README; (2) Enhancement #7 should be trimmed to match locked companion scope; (3) confidence here is in the **written spec**, while the **codebase is still pre-fix** until the build executes—by design, not a new discovery.

**Above 85:** Prior doc-level blockers are cleared; CSRF is consistently in **required** scope across fixes, plan, acceptance, tests, and checklist; sequencing is internally consistent.

**Below 90:** One handoff paragraph is still wrong about README; the repo has not yet implemented the spec (expected before coding starts).
