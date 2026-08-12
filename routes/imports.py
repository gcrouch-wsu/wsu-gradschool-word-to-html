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
from auth import current_uid
from config import SessionDir, ZIP_MAX_UNCOMPRESSED_BYTES, ZIP_MAX_FILES
from services.session_state import save_session_data, load_edits_data, save_edits_data
from services.docx_session import (
    run_docx_prepipeline,
    scrape_new_structure,
    build_identity_crosswalk,
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
from core.docx_processor import compute_sha256, count_tracked_changes, deserialize_sequence_map
from core.permalinks import normalize_manual_type
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
            # A downloaded fragment has its headings shifted down (h1 -> h2) and
            # records that in data-heading-offset; undo it so the manual is back
            # at its native levels. This must be persisted, not just applied to
            # the in-memory copy used for scraping: do_convert re-reads
            # import.html, so writing only the scrape copy left the conversion
            # working from the still-shifted file and chapters stayed at h2.
            manual_html = shift_heading_levels(manual_html, -heading_offset)
            html_path.write_text(manual_html, encoding='utf-8')

        # Normalize at the trust boundary: this value came from the uploaded
        # file's own grid attributes and feeds numbering, theming, and the
        # crosswalk prefix.
        manual_type = normalize_manual_type(meta.get('manual_type') or "chapter")
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
    # Internal/test escape hatch only — not exposed in the UI (skipping review
    # drops the human validation step). Keep for automated bundle-import tests.
    skip_review = 'skip_review' in request.form
    if not f or not f.filename.lower().endswith(".zip"):
        flash("Please upload a .zip session bundle.")
        return redirect(url_for("index"))

    # Optional: a newer Word file to use instead of the one inside the bundle.
    # This is the return leg of the editing cycle — the bundle holds the
    # reference review, the upload holds the editor's changes.
    revised_docx = request.files.get("revised_docx")
    revised_name = secure_filename(revised_docx.filename) if revised_docx and revised_docx.filename else ""
    if revised_docx and revised_docx.filename and not revised_name.lower().endswith(".docx"):
        flash("The revised document must be a .docx file.")
        return redirect(url_for("index"))
    if not revised_name:
        revised_docx = None

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
            zf_members = [info.filename for info in zf.infolist()]
            member_basenames = {
                name.replace('\\', '/').rstrip('/').split('/')[-1]
                for name in zf_members
                if not name.endswith('/')
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

        # Defense in depth: a legitimate bundle contains only the manifest, the
        # docx, the edits, and (optionally) the stable-map. Delete any other
        # extracted member so a malicious bundle can't plant a token artifact
        # (e.g. a forged {uuid}_meta.json the download route would later trust).
        allowed_members = {doc_name, edits_name, "manifest.json", "stable_heading_map.json"}
        for name in zf_members:
            if name.endswith('/'):
                continue
            relative = name.replace('\\', '/').strip('/')
            base = relative.split('/')[-1]
            if base in allowed_members and '/' not in relative:
                continue
            # Delete at the path the member was actually extracted to, not just
            # its basename: a member inside a subdirectory ("sub/evil.json")
            # landed at session.root/sub/evil.json while this swept
            # session.root/evil.json, so it survived. Extraction has already
            # been confined to session.root (checked above), so the join is safe.
            try:
                target = (session.root / relative).resolve()
                if target.is_file() and session.root.resolve() in target.parents:
                    target.unlink()
            except (OSError, ValueError):
                pass

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
        # (Suppressed when a revised DOCX was supplied below — there the
        # mismatch is the whole point, and warning about it is just noise.)
        expected_hash = manifest.get("doc_hash", "")
        actual_hash = compute_sha256(doc_path)
        if expected_hash and expected_hash != actual_hash and not revised_docx:
            flash("Warning: DOCX hash does not match manifest. Proceeding to import anyway.")

        # Standardize filenames in the isolated session
        dest_doc = session.source_docx
        dest_edits = session.edits_json

        # If the filenames in zip weren't already standardized, move them
        if doc_path != dest_doc:
            shutil.move(str(doc_path), str(dest_doc))
        if edits_path != dest_edits:
            shutil.move(str(edits_path), str(dest_edits))

        pending = count_tracked_changes(dest_doc)
        if pending and not revised_docx:
            flash(
                f"This bundle's document has {pending} unresolved tracked change(s). "
                "Accept or reject them in Word and save, then import again — the "
                "converter cannot read text inside a pending change."
            )
            return redirect(url_for("index"))

        if revised_docx:
            # Closes the editing round trip: the bundle carries the reference
            # review, the newly uploaded file carries the edits made in Word.
            # Without this the operator had to repackage the zip by hand, where
            # zipping the folder instead of its contents, or renaming the
            # document, produced errors ("manifest.json missing", "Malicious
            # bundle detected") that say nothing about what actually went wrong.
            revised_docx.save(str(dest_doc))
            pending = count_tracked_changes(dest_doc)
            if pending:
                flash(
                    f"“{revised_name}” has {pending} unresolved tracked change(s). Accept "
                    "or reject them in Word and save before uploading — the converter "
                    "cannot read text inside a pending change, so anything left "
                    "unresolved is silently dropped."
                )
                return redirect(url_for("index"))
            flash(
                f"Using the revised document “{revised_name}” in place of the one "
                f"in the bundle. Your reference review is kept — anything that could "
                "not be matched to a citation is reported below."
            )
            logger.info("Bundle import: replaced %s with uploaded %s", doc_name, revised_name)
        else:
            flash(f"Session imported for {doc_name}.")

        current_doc_hash = compute_sha256(dest_doc)
        edits_data = load_edits_data(session)
        if not revised_docx and expected_hash and expected_hash == current_doc_hash:
            edits_data["doc_hash"] = current_doc_hash
            save_edits_data(session, edits_data)

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

            # Phases 3-4: heading IDs, scrape, then build the crosswalk the same
            # way /convert does — identity for keep_old, auto-match otherwise.
            normalized_html, new_headings = scrape_new_structure(normalized_html, stable_heading_map)
            if manifest.get("mapping_mode", "map_new") == "keep_old":
                auto_crosswalk = build_identity_crosswalk(references)
            else:
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
                # Use the map actually applied above (the extracted
                # stable_heading_map.json when present, else the manifest's), so
                # the persisted session matches what was scraped/cached.
                stable_heading_map=stable_heading_map,
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
            session_data['doc_hash'] = current_doc_hash
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
