"""Import paths: saved HTML pages and exported session bundles."""

import json
import logging
import os
import shutil
import uuid
import zipfile

from flask import (
    request,
    redirect,
    url_for,
    flash,
)
from werkzeug.utils import secure_filename

from webapp import app
from auth import current_uid, session_owner_ok
from config import SessionDir, ZIP_MAX_UNCOMPRESSED_BYTES, ZIP_MAX_FILES
from services.session_state import save_session_data, load_edits_data
from services.docx_session import (
    run_docx_prepipeline,
    scrape_new_structure,
    build_heading_order,
    build_session_data,
)
from core.html_processor import (
    add_heading_ids,
    apply_css_counter_numbering,
    infer_heading_levels_from_prefix,
    strip_heading_numbers_dom,
    strip_html_assets,
    shift_heading_levels,
    extract_manual_fragment,
)
from core.docx_processor import compute_sha256, deserialize_sequence_map
from core.manual_structure import scrape_heading_structure_from_html, auto_match_old_to_new_references
from core.reference_linking import extract_references_from_html
from core.styling import coerce_theme_settings

logger = logging.getLogger(__name__)

from routes.common import load_heading_id_map_from_request

def _zip_archive_within_limits(zf: zipfile.ZipFile) -> tuple[bool, str]:
    """Reject archives that exceed configured uncompressed size or file count."""
    total = 0
    count = 0
    for info in zf.infolist():
        if info.filename.endswith("/"):
            continue
        count += 1
        if count > ZIP_MAX_FILES:
            return False, f"ZIP contains too many files (limit {ZIP_MAX_FILES})."
        total += int(info.file_size or 0)
        if total > ZIP_MAX_UNCOMPRESSED_BYTES:
            return False, "ZIP uncompressed size exceeds the configured limit."
    return True, ""

@app.route("/import_html", methods=["POST"])
def import_html():
    """Import HTML (standalone/fragment/WordPress) and start a review session"""
    f = request.files.get("html_file")
    if not f or f.filename == "":
        flash("Please upload an HTML file.")
        return redirect(url_for("index"))

    # Phase 1: Initialize Session
    session_id = str(uuid.uuid4())
    session = SessionDir(session_id, create=True)

    filename = secure_filename(f.filename)
    if not filename.lower().endswith((".html", ".htm")):
        flash("Only .html or .htm files are supported.")
        return redirect(url_for("index"))

    # Save to session-isolated root
    html_path = session.root / "import.html"
    f.save(str(html_path))

    strip_docx_formatting = "strip_docx_formatting" in request.form
    edit_tables = "edit_tables" in request.form
    stable_heading_map, stable_heading_map_raw = load_heading_id_map_from_request()

    try:
        raw_html = html_path.read_text(encoding='utf-8', errors='ignore')
        cleaned_html = strip_html_assets(raw_html)
        html_path.write_text(cleaned_html, encoding='utf-8')
        manual_html, meta = extract_manual_fragment(cleaned_html)
        if not (manual_html or "").strip():
            flash("Could not find manual content (expected .manual-grid / main.manual / div.manual).")
            return redirect(url_for("index"))
        heading_offset = 0
        try:
            heading_offset = int(meta.get('heading_offset') or 0)
        except (ValueError, TypeError):
            heading_offset = 0
        if heading_offset:
            manual_html = shift_heading_levels(manual_html, -heading_offset)

        manual_type = meta.get('manual_type') or "chapter"
        toc_depth = meta.get('toc_depth') or "2"
        numbering_mode = meta.get('numbering_mode') or "css-counters"
        theme_id = meta.get('theme_id') or ""

        try:
            toc_depth = int(toc_depth)
            if toc_depth < 1 or toc_depth > 5:
                toc_depth = 2
        except (ValueError, TypeError):
            toc_depth = 2
        mapping_mode = "keep_old" if numbering_mode == "preserve" else "map_new"
        preserve_numbers = (numbering_mode == "preserve")

        manual_with_ids = add_heading_ids(
            manual_html,
            overwrite_existing=False,
            stable_map=stable_heading_map
        )
        scrape_html = manual_with_ids
        if numbering_mode == "css-counters":
            scrape_html = apply_css_counter_numbering(scrape_html, manual_type, preserve=False)
        new_headings = scrape_heading_structure_from_html(scrape_html)

        references = extract_references_from_html(manual_with_ids)

        if mapping_mode == "keep_old":
            auto_crosswalk = {ref[2]: ref[2] for ref in references}
        else:
            auto_crosswalk = auto_match_old_to_new_references(references, new_headings, manual_type=manual_type)

        theme_settings, _ = coerce_theme_settings({"theme_id": theme_id} if theme_id else None, manual_type)
        session_data = build_session_data(
            manual_type=manual_type,
            filename=filename,
            src_path=html_path,
            references=references,
            new_headings=new_headings,
            auto_crosswalk=auto_crosswalk,
            toc_depth=toc_depth,
            preserve_numbers=preserve_numbers,
            numbering_mode=numbering_mode,
            mapping_mode=mapping_mode,
            html_import=True,
            html_path=html_path,
            strip_docx_formatting=strip_docx_formatting,
            edit_tables=edit_tables,
            theme_settings=theme_settings,
            stable_heading_map=stable_heading_map,
            stable_heading_map_raw=stable_heading_map_raw,
        )
        session_data['owner'] = current_uid()
        save_session_data(session, session_data)

        return redirect(url_for('review', session_id=session_id))
    except Exception as e:
        logger.exception("HTML import failed")
        flash(f"HTML import failed: {e}")
        return redirect(url_for("index"))


def _bundle_import_post_pandoc_pipeline(normalized_html: str, manifest: dict, manual_type: str) -> str:
    """
    Post-process Pandoc body HTML when rebuilding from an imported session bundle.
    Must stay aligned with convert() / do_convert(): infer depth, then optionally strip
    heading numbers, then apply CSS-counter numbering with the correct preserve flag.
    """
    if manifest.get("mapping_mode", "map_new") == "map_new" and manifest.get("infer_heading_depth", False):
        style_map = manifest.get("infer_style_map", {}) or {}
        normalized_html = infer_heading_levels_from_prefix(
            normalized_html, style_map if style_map else None
        )
    preserve_numbers = bool(manifest.get("preserve_numbers", False))
    if manifest.get("mapping_mode", "map_new") == "keep_old":
        preserve_numbers = True
    if not preserve_numbers:
        normalized_html, _ = strip_heading_numbers_dom(normalized_html)
    return apply_css_counter_numbering(
        normalized_html, manual_type, preserve=preserve_numbers
    )


@app.route("/import_bundle", methods=["POST"])
def import_bundle():
    """Import a session bundle zip and copy contents into isolated session workspace"""
    f = request.files.get("bundle")
    skip_review = 'skip_review' in request.form
    if not f or not f.filename.lower().endswith(".zip"):
        flash("Please upload a .zip session bundle.")
        return redirect(url_for("index"))

    # Phase 1: Initialize Session
    session_id = str(uuid.uuid4())
    session = SessionDir(session_id, create=True)

    # Save ZIP to session root
    bundle_path = session.root / "import_bundle.zip"
    f.save(str(bundle_path))

    try:
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            # Safety check: Prevent path traversal.
            # Normalize separators and resolve each entry's final path so that
            # backslash variants ("..\\foo") and URL-encoded tricks are caught.
            safe_root = session.root.resolve()
            safe_root_str = str(safe_root)
            if not safe_root_str.endswith(os.sep):
                safe_root_str += os.sep

            for name in zf.namelist():
                # Reject obvious absolute paths and dot-dot segments
                normalized_name = name.replace('\\', '/')
                if normalized_name.startswith('/') or '..' in normalized_name.split('/'):
                    flash("Security error: Malicious bundle detected.")
                    return redirect(url_for("index"))
                # Resolve-and-confirm: ensure the entry stays inside the session root
                target = (safe_root / name).resolve()
                if not str(target).startswith(safe_root_str):
                    flash("Security error: Malicious bundle detected.")
                    return redirect(url_for("index"))
            ok_zip, zip_msg = _zip_archive_within_limits(zf)
            if not ok_zip:
                flash(zip_msg)
                return redirect(url_for("index"))
            # Capture the FILE member basenames BEFORE extraction: the
            # manifest's file names are a second trust boundary (their contents
            # are arbitrary attacker JSON) and must reference real, in-archive
            # basenames — not absolute paths or "../" that would escape
            # session.root once joined (pathlib replaces the base on an absolute
            # right operand). Directory entries are excluded so a manifest can't
            # point docx/edits at a directory (which would later blow up in
            # compute_sha256/shutil.move).
            member_basenames = {
                info.filename.replace('\\', '/').rstrip('/').split('/')[-1]
                for info in zf.infolist()
                if not info.filename.endswith('/')
            }
            zf.extractall(session.root)

        manifest_path = session.manifest_json
        if not manifest_path.exists():
            flash("Invalid bundle: manifest.json missing.")
            return redirect(url_for("index"))

        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        doc_name = manifest["files"].get("docx")
        edits_name = manifest["files"].get("edits")

        # Manifest file names must be plain basenames that were actually present
        # in the (already-validated) archive. Rejects absolute paths, separators,
        # and "../" before they reach session.root / shutil.move / compute_sha256.
        for nm in (doc_name, edits_name):
            if (not isinstance(nm, str) or not nm
                    or nm != os.path.basename(nm)
                    or nm in ("", ".", "..")
                    or nm not in member_basenames):
                flash("Security error: Malicious bundle detected.")
                return redirect(url_for("index"))

        doc_path = session.root / doc_name
        edits_path = session.root / edits_name

        # is_file (not exists): a directory entry whose basename slipped through
        # must not reach compute_sha256/shutil.move.
        if not doc_path.is_file() or not edits_path.is_file():
            flash("Invalid bundle: missing DOCX or edits file.")
            return redirect(url_for("index"))

        # Verify hash. A mismatch is deliberately non-fatal: operators sometimes
        # swap an edited DOCX into an exported bundle, and the review steps that
        # follow give them a chance to catch real problems. Warn, don't block.
        expected_hash = manifest.get("doc_hash", "")
        actual_hash = compute_sha256(doc_path)
        if expected_hash and expected_hash != actual_hash:
            flash("Warning: DOCX hash does not match manifest. Proceeding to import anyway.")

        # Standardize filenames in the isolated session
        dest_doc = session.source_docx
        dest_edits = session.edits_json
        
        # If the filenames in zip weren't already standardized, move them
        if doc_path != dest_doc:
            shutil.move(str(doc_path), str(dest_doc))
        if edits_path != dest_edits:
            shutil.move(str(edits_path), str(dest_edits))

        flash(f"Session imported for {doc_name}.")

        # Immediately start a review session from the imported doc/edits
        try:
            style_map = {}
            sequence_map = {}
            if manifest.get("mapping_mode", "map_new") == "map_new" and manifest.get("infer_heading_depth", False):
                style_map = manifest.get("infer_style_map", {}) or {}
                sequence_map = deserialize_sequence_map(manifest.get("infer_sequence_map", {}) or {})

            # Phases 1-2: shared with /convert via services.docx_session
            (heading_map, old_crosswalk, references, manual_type,
             docx_links_by_para, normalized_html) = run_docx_prepipeline(session, style_map, sequence_map)

            # Bundle-specific middle: heading-number handling is driven by the
            # manifest rather than form fields.
            normalized_html = _bundle_import_post_pandoc_pipeline(
                normalized_html, manifest, manual_type
            )
            preserve_numbers = bool(manifest.get("preserve_numbers", False))
            if manifest.get("mapping_mode", "map_new") == "keep_old":
                preserve_numbers = True
            stable_heading_map = manifest.get("stable_heading_map", {}) or {}
            if session.stable_map_json.exists():
                try:
                    stable_heading_map = json.loads(
                        session.stable_map_json.read_text(encoding="utf-8")
                    )
                except Exception as e:
                    logger.warning("Bundle stable_heading_map.json unreadable, using manifest: %s", e)

            # Phases 3-4: heading IDs, scrape, auto-match
            normalized_html, new_headings = scrape_new_structure(normalized_html, stable_heading_map)
            auto_crosswalk = auto_match_old_to_new_references(references, new_headings, manual_type=manual_type)

            theme_settings, _ = coerce_theme_settings(manifest.get("theme_settings"), manual_type)
            session_data = build_session_data(
                manual_type=manual_type,
                filename=session.source_docx.name,
                src_path=session.source_docx,
                references=references,
                new_headings=new_headings,
                auto_crosswalk=auto_crosswalk,
                heading_map=heading_map,
                old_crosswalk=old_crosswalk,
                heading_order=build_heading_order(heading_map, manual_type),
                pre_path=session.pre_docx,
                temp_html_path=session.temp_html,
                toc_depth=manifest.get("toc_depth", 2),
                preserve_numbers=preserve_numbers,
                numbering_mode=manifest.get("numbering_mode"),
                mapping_mode=manifest.get("mapping_mode", 'map_new'),
                strip_docx_formatting=manifest.get("strip_docx_formatting", False),
                theme_settings=theme_settings,
                heading_edits=manifest.get("heading_edits", {}),
                infer_heading_depth=manifest.get("infer_heading_depth", False),
                infer_style_map=manifest.get("infer_style_map", {}),
                infer_sequence_map=manifest.get("infer_sequence_map", {}),
                stable_heading_map=manifest.get("stable_heading_map", {}) or {},
                stable_heading_map_raw=manifest.get("stable_heading_map_raw", "") or "",
                docx_links_by_para=docx_links_by_para,
                edit_tables=manifest.get("edit_tables", False),
            )
            # If edits file exists in bundle, seed approved_crosswalk from it
            edits_data = load_edits_data(session)
            appr = edits_data.get('approved_crosswalk', {})
            if appr:
                session_data['approved_crosswalk'] = appr
            session_data['owner'] = current_uid()
            save_session_data(session, session_data)

            if skip_review:
                return redirect(url_for('do_convert', session_id=session_id))
            return redirect(url_for('heading_review', session_id=session_id))
        except Exception as e:
            logger.exception("Bundle import: could not start review session")
            flash(f"Import succeeded but could not start review automatically: {e}")
            return redirect(url_for("index"))
    except Exception as e:
        logger.exception("Bundle import failed")
        flash(f"Import failed: {e}")
        return redirect(url_for("index"))
