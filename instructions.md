# WSU Manual Converter — User instructions

This page explains how to use the **web application** to turn a Word manual (`.docx`) into HTML for WordPress and how to keep permalinks stable across edits.

---

## Who this is for

- **Editors / publishers** — upload a manual, step through review, download HTML/CSS/JS, and publish to WordPress.
- **Operators** — install and run the app on a computer or server (see [Local setup](#local-setup-operators) below).

---

## Before you start (requirements)

- A **`.docx`** file (Microsoft Word format).
- **Pandoc** must be installed on the machine that runs the app. If the app fails to start, install Pandoc from [pandoc.org/installing.html](https://pandoc.org/installing.html) and confirm `pandoc --version` works in a terminal.

---

## Main workflow: first-time conversion

1. On the home page, under **Upload DOCX Manual**, choose your `.docx` file.
2. Set **Conversion options** (see [Options explained](#conversion-options) below).
3. Click **Upload and Review**.
4. Complete each review step the app presents (for example headings, references, and optionally **table review** if you enabled it).
5. When you reach the final preview, click **Proceed with Conversion** (or the equivalent control on that screen).
6. Use the download buttons to save the files you need (see [Downloads](#downloads-what-each-file-is-for)).

You do **not** need a heading map the first time. Save the **Heading Map** JSON from the download list so you can reuse it after the next Word edit.

---

## Repeat conversion (keep WordPress links stable)

When you edit the manual in Word and want published URLs (`#section-anchors`) to stay the same for unchanged headings:

1. Upload the **new** `.docx`.
2. Expand **Advanced: Permalink Continuity (Heading Map)** on the upload form.
3. Either:
   - Use **Upload heading map JSON** and pick your previous `*.heading-map.json`, **or**
   - Paste the JSON into **Or paste Signature-to-ID JSON**.
4. If both file and paste are filled in, the **pasted text wins**.
5. Leave **Keep heading numbers in text** **unchecked** unless you intentionally want numbers embedded in heading text (the site CSS usually adds numbering automatically).
6. Run through review and convert again.
7. Download a **new** heading map for the next cycle.

**Tip:** If the heading map does not seem to apply, use the file picker; relying on paste alone sometimes misses what you expect.

---

## Conversion options

| Control | What it does |
|--------|----------------|
| **Open table review before export** | If the document has tables, you get a table review step before export so you can check formatting. |
| **Keep heading numbers in text** | Keeps literals like `Chapter 1` or `I.A.` inside the heading text. **Off** is normal when your site CSS adds numbering. |
| **Table of Contents Depth** | How many heading levels appear in the generated TOC (H1 through H5, depending on selection). |
| **Heading mapping mode** | **Map to new numeric headings** (recommended) vs **Keep original headings/numbering**. |
| **Heading map (Advanced)** | Reuses stable anchor IDs from a previous export so WordPress links stay valid when text is unchanged. |

---

## Review steps (what to expect)

After upload, the app guides you through checks that depend on your document. Typical stages include:

- **Heading review** — confirm structure and levels; you may correct how headings are interpreted.
- **Reference / crosswalk review** — legacy references (Roman numerals, letters) can be aligned to the new numeric structure.
- **Table review** — only if you enabled table review and tables were found.

Follow the on-screen prompts until you reach the **preview** with export actions.

---

## Downloads: what each file is for

| Download | Use |
|----------|-----|
| **Standalone HTML** | Full page with embedded styles/scripts — best for **local preview** in a browser. |
| **Fragment** | **Body HTML only** — paste into a WordPress **Custom HTML** block (or equivalent). |
| **Fragment + CSS** | Convenient **offline preview** of the fragment with styles embedded; **not** a substitute for proper WordPress CSS deployment (see below). |
| **DOCX** | Clean Word file for the **next editing round**; re-upload after edits. |
| **CSS** / **JS** | Install on the WordPress site (theme, Customizer, or snippet plugin) so the manual matches the preview. |
| **Heading Map** | JSON to upload next time under **Advanced** for **permalink continuity**. |
| **Session Bundle (.zip)** | Saves session artifacts for **restore** via **Import & Restore → Session Bundle**. |

---

## WordPress deployment (summary)

1. Add **CSS** site-wide (e.g. **Appearance → Customize → Additional CSS** or a CSS plugin).
2. Add **JS** site-wide or via a **code snippet** plugin. If your snippet UI expects raw HTML, wrap the script in `<script> … </script>` tags.
3. Paste the **Fragment** HTML into a **Custom HTML** block.

**Important:** WordPress often strips `<input>`, `<style>`, and `<script>` from Custom HTML blocks. The shipped `wordpress.js` includes logic to recreate the TOC search box when needed. **Fragment + CSS** is still not enough by itself in WordPress if the host strips embedded `<style>` / `<script>` — use site-level CSS and JS as above.

---

## Import & restore (home page)

- **Session Bundle** — upload a previously exported `.zip` to restore that session’s state.
- **WordPress HTML** — upload an exported `.html` file; optional heading map JSON; optional **Open table review before export** (same behavior as DOCX upload when tables are present).

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| App will not start | Install Pandoc; verify `pandoc --version`. |
| **405 Method Not Allowed** on convert | Hard refresh or clear cache for this site. |
| Search / TOC wrong on WordPress | Redeploy the latest **JS** from this app’s export. |
| No table review | Enable **Open table review before export** **before** uploading. |
| Heading map ignored | Prefer **file upload** in Advanced; check JSON validity. |
| Lost in-progress work | Sessions live under the server’s temp folder; OS cleanup can remove them. Use **Export Session Bundle** when you need a backup. |

---

## Concepts (short)

### Heading map and permalinks

The heading map records a stable ID for each heading **signature** (normalized heading text). When you re-convert with the same map, unchanged headings keep the same IDs, so existing WordPress URLs with `#anchors` keep working.

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

1. Install **Python 3.10+** and **Pandoc**.
2. Install Python packages (including the Markdown library used by the in-app **Instructions** page):

   ```bash
   pip install flask~=3.0 python-docx~=1.1 beautifulsoup4~=4.12 lxml~=5.1 werkzeug~=3.0 markdown~=3.6
   ```

3. Start the app:

   ```bash
   python word_to_wordpressV4.py
   ```

4. Open the URL shown in the terminal (often `http://127.0.0.1:5000`).

**Docker:** the project `Dockerfile` installs dependencies and runs the app with Gunicorn; Pandoc is included in the image.

**Environment variables** (optional): `PERSIST_DIR`, `FLASK_SECRET_KEY`, `SESSION_TTL_HOURS`, `LOG_LEVEL` — see the project `README.md` for defaults and meanings.

---

## Related tool

The separate **config generator** (`docx_config_generator.py`) is documented in `README_config_generator.md` in the project folder. It is not part of the main upload workflow.
