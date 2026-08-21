# DOCX Configuration Generator

A standalone Flask application for analyzing DOCX files and generating JSON
configuration manifests. It is a **local style-preview / heading-map exploration
tool**, not part of the main converter upload workflow.

**Deployment:** The main converter’s deployment scope is a maintainer concern outside this README; this companion app remains **local-only** unless your team explicitly expands it.

## Purpose

This tool allows you to:
- Upload a DOCX file and analyze its styles, fonts, colors, and heading structure
- Configure document settings (manual type, mapping mode, TOC depth)
- Customize styles for body text and headings (fonts, sizes, colors)
- Review resolved (inherited) styles with real document samples
- Edit ordered and unordered list formats
- Run a basic heading-order accessibility preflight
- Edit heading structure (levels and titles)
- Export inferred heading token maps for inspection in this tool
- Export a JSON configuration file you can re-import into this generator later
- Download an example DOCX that illustrates the resolved styles
- Import a JSON configuration file to continue editing later

## Installation

For parity with the main app (and fewer version surprises), install from the repo root:

```bash
pip install -r requirements.txt
```

Minimal run (if you only need this tool in isolation):

```bash
pip install flask python-docx
```

## Usage

### Starting the App

```bash
python docx_config_generator.py
```

The app will start on `http://127.0.0.1:5000`. The main converter also defaults
to port 5000 — stop it first, or this bind will fail.

### Workflow

1. **Upload DOCX**: Upload your Word document on the home page
1. **Or Import JSON**: Upload a saved configuration to resume work
2. **Analysis**: The app automatically extracts:
   - All paragraph styles (fonts, sizes, colors)
   - Heading structure (levels, text, styles)
   - Document structure
3. **Edit Configuration**: 
   - Adjust conversion settings (manual type, mapping mode, TOC depth)
   - Customize body text styles (font, size, color, line height)
   - Configure heading styles (H1-H6 fonts, sizes, colors)
   - Edit ordered list numbering and unordered bullet styles
   - Set list levels to **Not used** to omit them from the preview and example DOCX
   - Review resolved style samples and heading-order warnings
   - Edit heading structure (change levels, update titles)
4. **Save & Export**: Click "Save Configuration" then "Download JSON"
5. **Example DOCX**: Download a visual sample doc to confirm styles
6. **Re-import later**: Download JSON from this tool and import it here to resume. The main converter does **not** load this file.

**Save vs Download JSON**:
- **Preview updates automatically** when you change a setting (unsaved).
- **Save Configuration** writes changes to the session config file.
- **Reset Form** reloads the last saved configuration.
- **Download JSON** exports the saved configuration file you can import later.

## JSON Configuration Structure

The exported JSON contains:

```json
{
  "version": "1.0",
  "document_info": {
    "filename": "manual.docx",
    "analyzed_at": "2026-01-XX..."
  },
  "conversion": {
    "mapping_mode": "map_new",
    "preserve_numbers": false,
    "toc_depth": 3,
    "manual_type": "chapter"
  },
  "infer_style_map": {
    "alpha_upper": 2,
    "decimal": 3
  },
  "infer_sequence_map": [
    { "sequence": ["alpha_upper", "decimal"], "level": 3 }
  ],
  "styles": {
    "body": {
      "font": "Calibri",
      "size": 11,
      "color": "#000000",
      "line_height": 1.15,
      "paragraph_format": { "space_before_pt": 0, "space_after_pt": 6 }
    },
    "headings": {
      "h1": { "font_name": "Calibri", "font_size": 16, "color": "#981E32" },
      "h2": { ... },
      ...
    }
  },
  "theme": {
    "theme_id": "manual",
    "body_font": "\"Calibri\", sans-serif",
    "heading_color": "#981E32",
    ...
  },
  "headings_structure": [
    { "index": 0, "level": 1, "text": "Chapter 1", "style_name": "Heading 1" },
    ...
  ],
  "lists": {
    "multilevel_formats": {
      "0": { "format": "lowerLetter", "lvl_text": "%1.", "start": 1 }
    },
    "unordered_formats": {
      "0": "disc",
      "1": "circle",
      "2": "square"
    },
    "examples": []
  }
}
```

## Features

- **Style Extraction**: Automatically detects fonts, sizes, and colors from Word styles
- **Resolved Styles**: Shows inherited values with real document examples
- **Heading Analysis**: Identifies all headings with their levels and styles
- **List Formats**: Captures ordered and unordered list patterns
- **Accessibility Preflight**: Flags heading order skips
- **Visual Editor**: User-friendly interface for editing configuration
- **Preview Panel**: Live preview to compare keep-original vs new-numeric heading styles
- **JSON Export**: Structured JSON you can re-import into this generator
- **Example DOCX Export**: Generates a sample Word file for style verification
- **Session Management**: Files stored temporarily (can be cleared between sessions)

## File Locations

- Uploaded files: Stored in system temp directory under `docx_config_generator/`
- Session files: `{session_id}_upload.docx`, `{session_id}_analysis.json`, `{session_id}_config.json`
- Exported JSON: Downloads as `{filename}_config.json`

## Integration with Main App

The converter (`word_to_wordpressV4.py`) does **not** load this JSON today.
The generator shares canonical helpers with `core/` and `utils/` (see
`PROJECT_SPEC.md` §11) so heading-prefix and numbering helpers cannot drift.
Do not deploy it: `debug=True`, no authentication, no CSRF. §21 tracks whether
it stays local-only or gets the same gate as the main app.

## Notes

- Separate standalone app; not part of the Railway/Docker deploy target
- Runs on port 5000 by default (conflicts with the main app if both are up)
- Session files are temporary and may be cleared on system restart
- Font sizes in the config are stored in points to match Word.

