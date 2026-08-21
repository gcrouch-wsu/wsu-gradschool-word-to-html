# WSU Manual Converter — User instructions

This page explains how to use the **web application** to turn a Word manual (`.docx`) into HTML for WordPress and how to keep permalinks stable across edits.

**Release engineering and security posture** for production are outside the scope of this file; follow your team’s internal runbooks. **`README.md`** covers local install, env vars, and tests. This file is **operator / editor** guidance.

---

## Who this is for

- **Editors / publishers** — upload a manual, step through review, download HTML/CSS/JS, and publish to WordPress.
- **Operators** — install and run the app on a computer or server (see [Local setup](#local-setup-operators) below).

---

## Before you start (requirements)

- A **`.docx`** file (Microsoft Word format).
- **All tracked changes must be resolved** in Word (**Review → Accept/Reject**) before upload. The app refuses documents with pending revisions.
- **Pandoc** must be installed on the machine that runs the app. If the app fails to start, install Pandoc from [pandoc.org/installing.html](https://pandoc.org/installing.html) and confirm `pandoc --version` works in a terminal.

If the production app asks you to sign in, enter the account email and password supplied by your team. Use the eye button in the password field to show or hide what you typed before submitting.

---

## Main workflow: first-time conversion

1. On the home page, under **1. Start from Word**, choose your `.docx` file.
2. Set **Conversion options** (see [Options explained](#conversion-options) below). Skip the heading-map box on a first run.
3. Click **Continue with Word file**.
4. Complete each review step the app presents (heading numbers when remapping, references, and optionally **table review** if you enabled it).
5. When you reach the final preview, use the download buttons (see [Downloads](#downloads-what-each-file-is-for)).
6. Save the **Heading Map** JSON from the download list so you can reuse it after the next Word edit. Export a **Session Bundle** if you need a backup or handoff.

Sessions are temporary (typically kept for a couple of days on the server unless cleaned up earlier). Export a bundle when you need the work to survive beyond that.

---

## Repeat conversion (keep WordPress links stable)

When you edit the manual in Word and want published URLs (`#section-anchors`) to stay the same for unchanged headings:

1. Upload the **new** `.docx` on the home page (**1. Start from Word**).
2. In the **same form**, use the shaded **Optional: heading map** box: pick your previous heading map file (often named like `*.heading-map.json`). You do **not** need a separate step; it goes with the Word file.
3. Or paste the map text under **Prefer to paste the map instead of using a file?** If both a file and pasted text are filled in, the **pasted text wins**.
4. Choose mapping mode to match the document (see options below). Leave **Show numbers in the heading text** **unchecked** unless you intentionally want numbers embedded in heading HTML (the site CSS usually adds numbering). **When that option is on, numbers are part of the visible heading**, so they are part of the **permalink signature**—changing only a number in Word can change the anchor unless the heading map is updated.
5. Run through review and convert again.
6. Download a **new** heading map for the next cycle.

**Tip:** If the heading map does not seem to apply, use the file picker; relying on paste alone sometimes misses what you expect.

---

## Conversion options

| Control | What it does |
|--------|----------------|
| **Top-level label (Chapter or Section)** | **Auto** detects from Chapter/Section headings in the Word file (not cover-page keywords). Override to Chapter or Section only if Auto is wrong. |
| **How should body references match headings?** | **Map body cites to new heading numbers** — use when renumbering (letter/Roman → decimals); runs a heading-number review. **Keep the Word file’s heading numbers** — use when the DOCX is already decimal; skips that review. |
| **Show numbers in the heading text** | Only applies in **Map…** mode. Off (default) strips typed numbers **and** spelled-out labels like `Chapter One` / `Section One` so site CSS can add `Chapter 1.` In **Keep…** mode this checkbox is ignored — Word numbers stay either way. |
| **Open table review before export** | If the document has tables, you get a table review step before export. You can also open **Table settings…** from the preview later. |
| **Table of Contents Depth** | How many heading levels appear in the generated TOC (H1 through H5). |
| **Advanced** | Infer heading levels from Word numbering styles (map-to-new only); strip direct Word formatting. Leave off unless a conversion mis-levels headings or you need a cleaner slate for CSS. |
| **Heading map (optional box)** | Reuses stable anchor IDs from a previous export so WordPress links stay valid when heading text is unchanged. |

**Quick pick:** Already-decimal manuals (e.g. Chapter 4.2 in Word) → **Keep the Word file’s heading numbers**. Being renumbered → **Map body cites to new heading numbers**.

---

## Review steps (what to expect)

After upload, the app guides you through checks that depend on your options and document:

- **Heading-number review** — when mapping to new numbers; confirm or fix how old numbers map to new ones. Skipped in **Keep…** mode.
- **Reference / crosswalk review** — body cites can be linked to internal headings or external URLs; mark non-cites as **Do not link**. Common degree acronyms (`D.V.M.`, `Ph.D.`, and similar dotted letter tokens) are filtered out automatically and usually never appear here.
- **Table review** — if you enabled it (or later via **Table settings…** on preview): per-table header row, column alignment, and placement.

Follow the on-screen prompts until you reach the **preview** with export actions. Optional **Document colors & fonts** on the preview updates theme CSS for this session.

---

## Reference review workflow

The reference review page is designed so you can work from the top down, approve obvious matches quickly, and save an incomplete session.

- Use the filter bar to focus the list:
  - **Needs action** — no usable link decision yet; choose a heading, enter an external URL, or mark **Do not link**.
  - **Needs review** — link-ready items that still need your approval.
  - **Ready to link** — citations that will become links.
  - **Skipped** — citations marked as plain text.
  - **Auto-matched** — citations the app matched to a heading.
  - **All** — every detected citation.
- For each citation, choose exactly one decision:
  - **Internal heading** — link to a heading in this manual.
  - **External URL** — link to another page or site.
  - **Do not link** — keep the citation as plain text in the final HTML.
- Auto-matched citations are preselected as internal links, but remain in **Needs review** until you approve them.
- Use **Approve** on one citation after you verify it. Use **Approve visible** after filtering to a set you have checked. Use **Approve exact auto-matches** when exact matches are clearly safe to accept in bulk.
- Use **Change** to open the full controls for a citation. Use **Edit link text** only when the linked words should differ from the citation text imported from Word.
- Use **Save progress** as often as needed. You can stop mid-review and continue later from the same session or from an exported **Session Bundle**.

---

## Downloads: what each file is for

Grouped on the preview page:

**Recommended for WordPress**

| Download | Use |
|----------|-----|
| **Fragment** | **Body HTML only** — paste into a WordPress **Custom HTML** block. |
| **CSS + theme** | Site stylesheet plus this session’s colors/fonts/table theme. |
| **JS** | Install on the WordPress site for TOC, search, the TOC print button, and navigation. |

**Also available**

| Download | Use |
|----------|-----|
| **Fragment + CSS** | Convenient **offline preview** of the fragment with styles embedded; **not** a substitute for proper WordPress CSS/JS deployment. |
| **Standalone HTML** | Full page with embedded styles/scripts — best for **local preview** in a browser. |
| **DOCX** | Clean Word file for the **next editing round**; re-upload after edits. |
| **CSS (base only)** | Stylesheet alone — for sites that already have theme colors installed. |
| **Heading Map** | JSON to attach next time in the optional heading-map box for **permalink continuity**. |
| **Session Bundle (.zip)** | Saves session artifacts for **restore** via **3. Restore a session bundle**. |
| **Table settings…** | Re-open table review when the document has tables. |

---

## WordPress deployment (summary)

1. Add **CSS** site-wide (e.g. **Appearance → Customize → Additional CSS** or a CSS plugin). Prefer **CSS + theme** or **CSS (base only)** as appropriate; **append** below any existing site CSS — do not replace the whole box.
2. Add **JS** site-wide or via a **code snippet** plugin. If your snippet UI expects raw HTML, wrap the script in `<script> … </script>` tags. After a converter CSS/JS update, re-paste **both** files (the 2026-08-20 print change updated both).
3. Paste the **Fragment** HTML into a **Custom HTML** block.

The TOC panel is controlled by the site-level JS. With the current `wordpress.js`, the TOC includes search and a **Print / Save PDF** button. That button opens the browser print dialog and uses the app's print CSS so the printed/PDF version drops TOC/search/print chrome, uses a single full-width ~11pt column, repeats table headers, and underlines external links without printing the URL after them.

**Important:** WordPress often strips `<input>`, `<style>`, and `<script>` from Custom HTML blocks. The shipped `wordpress.js` includes logic to recreate the TOC search box and print button when needed. **Fragment + CSS** is still not enough by itself in WordPress if the host strips embedded `<style>` / `<script>` — use site-level CSS and JS as above.

---

## Other paths on the home page

- **2. Start from a saved web page (HTML)** — when you only have an exported `.html` file (not the Word document). You can attach an optional heading map there too. Skips the heading-number remap step and goes to reference review.
- **3. Restore a session bundle (.zip)** — restores a full saved **session** you exported earlier (not the same as starting from Word or HTML). You can also supply a **revised Word document** so reference edits re-attach after an editor round-trip.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| App will not start | Install Pandoc; verify `pandoc --version`. |
| Upload refused for tracked changes | In Word: **Review → Accept → Accept All Changes** (or reject them), save, re-upload. |
| **405 Method Not Allowed** on convert | Hard refresh or clear cache for this site. |
| Search, TOC, or Print / Save PDF missing on WordPress | Redeploy the latest **JS** from this app’s export. |
| Need a PDF copy | Use **Print / Save PDF** above the TOC on the published/manual preview page, then choose Save as PDF in the browser print dialog. |
| No table review mid-flow | Enable **Open table review before export** **before** uploading, or use **Table settings…** on the preview. |
| Heading map ignored | Prefer **file upload** in the heading-map box; check JSON validity. |
| Degree / acronym wrongly offered as a cite | Mark it **Do not link**. Common dotted degrees are filtered automatically. |
| Reference review opens with only a few items visible | Check the active filter. **Needs review** is the default; use **All** to see every detected citation. |
| Auto-matched references still say Needs review | That is expected. The link is ready, but you still need to approve it or use **Approve exact auto-matches**. |
| Lost in-progress work | Sessions live under the server’s temp folder; OS cleanup can remove them. Use **Export Session Bundle** when you need a backup. |

---

## Concepts (short)

### Heading map and permalinks

The heading map records a stable ID for each heading **signature** (normalized heading text—exact match after normalization, not “fuzzy” similarity). When you re-convert with the same map, headings whose normalized text still matches keep the same IDs, so existing WordPress URLs with `#anchors` keep working.

### Hybrid rule for IDs

1. If the heading matches the uploaded map → use the **stored ID**.
2. Otherwise → generate a **new slug** from the heading text.

### Reference numbering

The tool can map old-style references to numeric form, for example:

- `Chapter 1.D.4` → `Chapter 1.4.4`
- `Section I.A.2.b` → `Section 1.1.2.2`
- `Chapter One` → `Chapter 1`

---

## Local setup (operators)

To run the Flask app on your machine:

1. Install **Python 3.12+** (recommended; matches Docker and typical `lxml` wheels) and **Pandoc**.
2. Install Python packages from the repo root:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   python word_to_wordpressV4.py
   ```

4. Open the URL shown in the terminal (often `http://127.0.0.1:5000`).

**Docker:** the project `Dockerfile` installs dependencies and runs the app with Gunicorn; Pandoc is included in the image.

**Environment variables** (optional): `PERSIST_DIR`, `FLASK_SECRET_KEY`, `SESSION_TTL_HOURS`, `AUTH_OWNER_*` / `AUTH_USERS`, `LOG_LEVEL` — see the project `README.md` for defaults and meanings.

---

## Related tool

The separate **config generator** (`docx_config_generator.py`) is documented in `README_config_generator.md` in the project folder. It is not part of the main upload workflow.
