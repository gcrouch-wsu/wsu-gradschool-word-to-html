"""DOCX conversion workflow: upload, heading/reference/table review, convert."""

import hashlib
import json
import html
import logging
import math
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    request,
    render_template,
    redirect,
    url_for,
    flash,
    jsonify,
)
from markupsafe import Markup, escape as markup_escape
from werkzeug.utils import secure_filename
from bs4 import BeautifulSoup

from webapp import app
from auth import current_uid, session_owner_ok
from config import SessionDir, is_valid_session_id
from services.session_state import (
    load_session_data,
    save_session_data,
    load_edits_data,
    save_edits_data,
)
from services.reference_keys import remap_reference_edits
from services.docx_session import (
    run_docx_prepipeline,
    scrape_new_structure,
    build_identity_crosswalk,
    build_heading_order,
    build_session_data,
)
from core.permalinks import normalize_heading_ref, ensure_prefixed
from core.html_processor import (
    save_stable_heading_map,
    process_html_pipeline,
    apply_css_counter_numbering,
    strip_inline_formatting,
    sanitize_docx_ids_for_export,
    has_tables_in_html,
    infer_heading_levels_from_prefix,
    strip_heading_numbers_dom,
    format_manual_tables,
    max_columns_in_first_table,
    describe_tables,
    extract_manual_fragment,
    build_manual_grid_block,
)
from core.pandoc_wrapper import (
    run_pandoc,
    run_pandoc_html_to_docx,
)
from core.docx_processor import (
    compute_sha256,
    serialize_sequence_map,
    generate_stable_ref_id,
    has_tables_in_docx,
    count_tracked_changes,
    sanitize_docx_styles,
    fix_numbering_xml,
    relocate_body_level_bookmarks,
    extract_style_map_from_reference,
)
from core.manual_structure import (
    auto_match_old_to_new_references,
    heading_sort_key,
    heading_dropdown_sort,
    find_heading_by_full,
    lookup_heading_title,
    build_heading_crosswalk_from_map,
)
from core.reference_linking import extract_external_links_from_html, extract_external_links_from_reference_text
from utils.url_policy import is_safe_href, normalize_external_href
from core.styling import (
    coerce_theme_settings,
    build_theme_css,
    build_table_theme_css,
    wsu_swatch_buttons_html,
    get_wp_css_text,
    get_wp_js_text,
)

logger = logging.getLogger(__name__)

from routes.common import (
    load_heading_id_map_from_request,
    first_manual_table_html,
    session_retention_context,
)

@app.route("/heading_review/<uuid:session_id>", methods=["GET", "POST"])
def heading_review(session_id):
    """Review and edit heading crosswalk before detailed reference editing."""
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session expired or invalid.")
        return redirect(url_for("index"))

    auto_crosswalk = session_data.get('approved_crosswalk') or session_data.get('auto_crosswalk', {})
    approved_crosswalk = session_data.get('approved_crosswalk', {})
    old_crosswalk = session_data.get('old_crosswalk', {})
    heading_map = session_data.get('heading_map', {})
    heading_order = session_data.get('heading_order', {})
    new_headings = session_data.get('new_headings', {})
    normalized_new_headings = False
    for heading_key, heading_data in new_headings.items():
        if heading_key.startswith(('H1:', 'H2:', 'H3:', 'H4:', 'H5:', 'H6:')):
            continue
        text = heading_data.get('text', '').strip()
        full = heading_data.get('full', '').strip()
        if text and full and not full.lower().startswith(heading_key.lower()):
            heading_data['full'] = f"{heading_key} - {text}"
            normalized_new_headings = True
        elif text and not full:
            heading_data['full'] = f"{heading_key} - {text}"
            normalized_new_headings = True
    if normalized_new_headings:
        session_data['new_headings'] = new_headings
        save_session_data(session, session_data)
    filename = session_data.get('filename', '')
    manual_type = session_data.get('manual_type', 'chapter')

    logger.debug(f"[heading_review]: Session loaded with heading_map={len(heading_map)} entries")
    if heading_map:
        sample_keys = list(heading_map.keys())[:5]
        logger.debug(f"[heading_review]: Sample heading_map keys: {sample_keys}")
    logger.debug(f"[heading_review]: approved_crosswalk={len(approved_crosswalk)} entries")
    logger.debug(f"[heading_review]: auto_crosswalk={len(auto_crosswalk)} entries")
    logger.debug(f"[heading_review]: old_crosswalk={len(old_crosswalk)} entries")

    # If user chose to keep old headings, skip this step
    if session_data.get('mapping_mode', 'map_new') == 'keep_old':
        return redirect(url_for('review', session_id=session_id))

    if request.method == 'POST':
        updated = {}
        heading_ids = set()
        for key in request.form.keys():
            if key.startswith("valid_"):
                heading_ids.add(key.replace("valid_", ""))

        updated_titles = {}

        for heading_id in heading_ids:
            is_valid = f'valid_{heading_id}' in request.form

            if is_valid:
                old_ref_raw = request.form.get(f'old_ref_{heading_id}', '').strip()
                new_ref_raw = request.form.get(f'new_ref_{heading_id}', '').strip()
                new_title_raw = request.form.get(f'new_title_{heading_id}', '').strip()

                if old_ref_raw and new_ref_raw:
                    old_ref = ensure_prefixed(normalize_heading_ref(old_ref_raw), manual_type)
                    new_ref = ensure_prefixed(normalize_heading_ref(new_ref_raw), manual_type)
                    if old_ref and new_ref:
                        updated[old_ref] = new_ref

                        if new_title_raw:
                            updated_titles[new_ref] = new_title_raw

                        logger.debug(
                            f"[heading_review POST]: Including valid entry: '{old_ref}' -> '{new_ref}'"
                            f"{(' with edited title' if new_title_raw else '')}"
                        )
        if not updated:
            fallback = {}
            if heading_map:
                fallback, heading_order = build_heading_crosswalk_from_map(heading_map, manual_type)
            elif old_crosswalk:
                for idx, (old_ref, new_ref) in enumerate(old_crosswalk.items()):
                    norm_old = ensure_prefixed(normalize_heading_ref(old_ref), manual_type)
                    norm_new = ensure_prefixed(normalize_heading_ref(new_ref), manual_type)
                    if norm_old and norm_new:
                        fallback[norm_old] = norm_new
                        heading_order[norm_old] = heading_order.get(norm_old, idx)
            else:
                fallback = auto_crosswalk
            updated = fallback

        session_data['approved_crosswalk'] = updated
        session_data['heading_order'] = heading_order

        # Update new_headings with edited titles
        if updated_titles:
            new_headings = session_data.get('new_headings', {})
            for new_ref, edited_title in updated_titles.items():
                # Update or create heading entry with edited title
                if new_ref in new_headings:
                    new_headings[new_ref]['text'] = edited_title
                    new_headings[new_ref]['full'] = f"{new_ref} - {edited_title}"
                else:
                    # Create new entry if doesn't exist
                    new_headings[new_ref] = {
                        'text': edited_title,
                        'full': f"{new_ref} - {edited_title}",
                        'level': 'unknown',
                        'id': ''
                    }
            session_data['new_headings'] = new_headings
            logger.debug(f"[heading_review POST]: Updated {len(updated_titles)} NEW heading titles")

        save_session_data(session, session_data)

        edit_data = load_edits_data(session)
        if not edit_data:
            edit_data = {
                'document': filename,
                'doc_hash': session_data.get('doc_hash') or "",
                'auto_crosswalk': auto_crosswalk,
                'approved_crosswalk': {},
                'reference_edits': {},
                'reference_validations': {},
                'reference_link_targets': {},
                'reference_ignored': {},
                'last_updated': str(datetime.now())
            }
        edit_data['document'] = filename
        edit_data['doc_hash'] = session_data.get('doc_hash') or ""
        edit_data['auto_crosswalk'] = auto_crosswalk
        edit_data['approved_crosswalk'] = updated
        edit_data['last_updated'] = str(datetime.now())
        save_edits_data(session, edit_data)

        flash(f"Heading map saved. {len(updated)} entries" + (f", {len(updated_titles)} titles edited." if updated_titles else "."))
        return redirect(url_for('review', session_id=session_id))

    # Build display list - PRIORITIZE approved_crosswalk so saved edits stay visible
    display_crosswalk = {}

    # Priority 1: Use approved_crosswalk if manually uploaded or saved
    if approved_crosswalk:
        logger.debug(f"[heading_review]: Using approved_crosswalk ({len(approved_crosswalk)} entries)")
        display_crosswalk = approved_crosswalk.copy()
    # Priority 2: Use heading_map if available (extracted from DOCX)
    elif heading_map:
        logger.debug(f"[heading_review]: Building display_crosswalk from heading_map ({len(heading_map)} entries)")
        display_crosswalk, heading_order = build_heading_crosswalk_from_map(heading_map, manual_type)
        logger.debug(f"[heading_review]: Built display_crosswalk with {len(display_crosswalk)} entries from heading_map")
    # Priority 3: Fall back to old_crosswalk
    elif old_crosswalk:
        logger.debug(f"[heading_review]: Falling back to old_crosswalk ({len(old_crosswalk)} entries)")
        tmp_order = {}
        for idx, (old_ref, new_ref) in enumerate(old_crosswalk.items()):
            norm_old = ensure_prefixed(normalize_heading_ref(old_ref), manual_type)
            norm_new = ensure_prefixed(normalize_heading_ref(new_ref), manual_type)
            if norm_old and norm_new:
                display_crosswalk[norm_old] = norm_new
                tmp_order[norm_old] = idx
        if tmp_order:
            heading_order = tmp_order
    # Priority 4: Use auto_crosswalk as last resort
    else:
        logger.debug(f"[heading_review]: Falling back to auto_crosswalk ({len(auto_crosswalk)} entries)")
        display_crosswalk = auto_crosswalk

    # Persist heading_order for later sorting if we synthesized it
    if heading_order and session_data.get('heading_order', {}) != heading_order:
        session_data['heading_order'] = heading_order
        save_session_data(session, session_data)

    logger.debug(f"[heading_review]: display_crosswalk before filtering: {len(display_crosswalk)} entries")
    if display_crosswalk:
        sample_items = list(display_crosswalk.items())[:5]
        logger.debug(f"[heading_review]: Sample display_crosswalk items: {sample_items}")

    # Filter out blank/None keys and sort by parsed numeric key
    filtered_items = []
    for old_ref, new_ref in display_crosswalk.items():
        if not old_ref or str(old_ref).lower() == "none":
            continue
        if not new_ref or str(new_ref).lower() == "none":
            continue
        norm_old = ensure_prefixed(normalize_heading_ref(old_ref), manual_type)
        norm_new = ensure_prefixed(normalize_heading_ref(new_ref), manual_type)
        if not norm_old or not norm_new:
            continue
        filtered_items.append((norm_old, norm_new))

    logger.debug(f"[heading_review]: After filtering: {len(filtered_items)} items remain")

    rows = sorted(
        filtered_items,
        key=lambda x: (
            heading_sort_key(x[0]),
            heading_order.get(x[0], heading_order.get(normalize_heading_ref(x[0]), 10**6))
        )
    )

    render_rows = []
    if heading_map:
        for old_ref, title in heading_map.items():
            is_synthetic = old_ref.startswith("_h")
            suggested_new_ref = ""
            if is_synthetic:
                match_key, _ = find_heading_by_full(title, new_headings)
                if match_key:
                    suggested_new_ref = match_key
            else:
                norm_old = ensure_prefixed(normalize_heading_ref(old_ref), manual_type)
                if not norm_old:
                    continue
                suggested_new_ref = display_crosswalk.get(norm_old) or display_crosswalk.get(old_ref) or old_ref
            render_rows.append({
                "old_ref": old_ref,
                "new_ref": suggested_new_ref or "",
                "old_title_override": title if is_synthetic else "",
                "is_synthetic": is_synthetic
            })
    else:
        for old_ref, new_ref in rows:
            render_rows.append({
                "old_ref": old_ref,
                "new_ref": new_ref,
                "old_title_override": "",
                "is_synthetic": False
            })

    logger.debug(f"[heading_review]: After sorting: {len(rows)} rows to display")
    if rows:
        logger.debug(f"[heading_review]: First 3 rows: {rows[:3]}")
        logger.debug(f"[heading_review]: Last 3 rows: {rows[-3:]}")

    logger.debug(f"[heading_review]: new_headings contains {len(new_headings)} entries")
    if new_headings:
        sample_new_keys = list(new_headings.keys())[:5]
        logger.debug(f"[heading_review]: Sample new_headings keys: {sample_new_keys}")

    template_rows = []
    title_lookup_failures = 0
    old_title_failures = 0
    for idx, row in enumerate(render_rows):
        old_ref = row["old_ref"]
        new_ref = row["new_ref"]
        is_synthetic = row["is_synthetic"]
        # OLD title: lookup from heading_map using the old reference
        old_title = row["old_title_override"] or lookup_heading_title(old_ref, heading_map, debug=(idx < 3))
        if not old_title:
            old_title_failures += 1

        # NEW title: the heading text doesn't change, only the numbering does,
        # so start from the OLD title and prefer the scraped HTML heading text.
        new_title = old_title
        alt_key = ""
        if new_headings:
            scraped_title = new_headings.get(new_ref, {}).get("text", "")
            if not scraped_title:
                alt_key = ensure_prefixed(normalize_heading_ref(new_ref), manual_type)
                scraped_title = new_headings.get(alt_key, {}).get("text", "")
            if scraped_title:
                new_title = scraped_title
            elif not new_title and idx < 3:
                logger.debug(f"[heading_review]: NEW title lookup failed for '{new_ref}', tried alt_key '{alt_key}', using old_title as fallback")
                title_lookup_failures += 1
        if not old_title and new_title:
            old_title = new_title

        template_rows.append({
            "heading_id": f"head_{idx}",
            "old_ref": old_ref or "",
            "display_old_ref": "" if is_synthetic else (old_ref or ""),
            "old_title": old_title or "",
            "new_ref": new_ref or "",
            "new_title": new_title or "",
            "checked": not is_synthetic,
        })

    if old_title_failures > 0:
        logger.debug(f"[heading_review]: Total OLD title lookup failures: {old_title_failures}")
    if title_lookup_failures > 0:
        logger.debug(f"[heading_review]: Total NEW title lookup failures: {title_lookup_failures} (but used old_title as fallback)")

    return render_template(
        "heading_review.html",
        rows=template_rows,
        session_id=session_id,
        **session_retention_context(session),
    )

@app.route("/convert", methods=["POST"])
def convert():
    f = request.files.get("docx")
    if not f or f.filename == "":
        flash("Please choose a .docx file.")
        return redirect(url_for("index"))

    # Phase 1: Initialize Session
    session_id = str(uuid.uuid4())
    session = SessionDir(session_id, create=True)

    preserve = bool(request.form.get("preserve_numbers"))
    mapping_mode = request.form.get("mapping_mode", "map_new")
    manual_type_override = (request.form.get("manual_type") or "auto").strip().lower()
    if manual_type_override not in ("auto", "chapter", "section", "policy"):
        manual_type_override = "auto"
    infer_heading_depth = request.form.get("infer_heading_depth") in ("1", "on", "true", "yes")
    strip_docx_formatting = "strip_docx_formatting" in request.form
    toc_depth = request.form.get("toc_depth", "2")  # Default to 2 if not provided
    edit_tables = "edit_tables" in request.form
    stable_heading_map, stable_heading_map_raw = load_heading_id_map_from_request()
    try:
        toc_depth = int(toc_depth)
        if toc_depth < 1 or toc_depth > 5:
            toc_depth = 2  # Validate range
    except (ValueError, TypeError):
        toc_depth = 2  # Default if invalid
    
    filename = secure_filename(f.filename)
    if not filename.lower().endswith(".docx"):
        flash("Only .docx files are supported.")
        return redirect(url_for("index"))

    src = session.source_docx
    f.save(str(src))

    pending = count_tracked_changes(src)
    if pending:
        # Refuse rather than convert quietly: the extractor cannot read text
        # inside a revision mark, so a pending change becomes a missing heading
        # or a dropped reference with nothing to show for it.
        flash(
            f"“{filename}” has {pending} unresolved tracked change(s). Accept or reject "
            "them in Word and save before converting — the converter cannot read text "
            "inside a pending change, so anything left unresolved is silently dropped."
        )
        return redirect(url_for("index"))
    try:
        style_map = {}
        sequence_map = {}
        if mapping_mode == "map_new" and infer_heading_depth:
            style_map, sequence_map = extract_style_map_from_reference(src)

        logger.info(f"SESSION: {session_id}")

        # Phases 1-2: preprocess DOCX, run Pandoc, normalize HTML (shared
        # with /import_bundle via services.docx_session)
        override = None if manual_type_override == "auto" else manual_type_override
        (heading_map, old_crosswalk, references, manual_type,
         docx_links_by_para, normalized_html) = run_docx_prepipeline(
            session, style_map, sequence_map, manual_type_override=override
        )

        # Align preserve flag with mapping choice: keeping old headings implies keeping numbers
        if mapping_mode == "keep_old":
            preserve = True

        if mapping_mode == "map_new" and infer_heading_depth:
            if not style_map:
                flash("No style map found in the source DOCX; falling back to prefix-based inference.")
            normalized_html = infer_heading_levels_from_prefix(normalized_html, style_map if style_map else None)

        # Strip old heading numbers (so CSS counters apply correctly)
        if not preserve:
            normalized_html, _ = strip_heading_numbers_dom(normalized_html)

        # Apply numeric numbering to headings (mimics CSS counters)
        normalized_html = apply_css_counter_numbering(normalized_html, manual_type, preserve=preserve)

        # Phase 3: heading IDs + scrape NEW structure
        normalized_html, new_headings = scrape_new_structure(normalized_html, stable_heading_map)

        # Phase 4: auto-match OLD references to NEW headings.
        # If keeping old numbering, build an identity crosswalk (OLD->OLD) instead.
        if mapping_mode == "keep_old":
            logger.info("Mode: keep_old - Building identity crosswalk (OLD->OLD)")
            auto_crosswalk = build_identity_crosswalk(references)
            logger.info(f"Built identity crosswalk with {len(auto_crosswalk)} OLD->OLD mappings")
        else:
            logger.info("Mode: map_new - Auto-matching OLD->NEW")
            auto_crosswalk = auto_match_old_to_new_references(references, new_headings, manual_type=manual_type)
            logger.info(f"Auto-matched {len(auto_crosswalk)} OLD->NEW mappings")

        # Store data in session for crosswalk editor
        theme_settings, _ = coerce_theme_settings(None, manual_type)
        session_data = build_session_data(
            manual_type=manual_type,
            filename=filename,
            src_path=src,
            references=references,
            new_headings=new_headings,
            auto_crosswalk=auto_crosswalk,
            heading_map=heading_map,
            old_crosswalk=old_crosswalk,
            heading_order=build_heading_order(heading_map, manual_type),
            pre_path=session.pre_docx,
            temp_html_path=session.temp_html,
            toc_depth=toc_depth,
            preserve_numbers=preserve,
            mapping_mode=mapping_mode,
            strip_docx_formatting=strip_docx_formatting,
            theme_settings=theme_settings,
            infer_heading_depth=infer_heading_depth,
            infer_style_map=style_map,
            infer_sequence_map=serialize_sequence_map(sequence_map),
            stable_heading_map=stable_heading_map,
            stable_heading_map_raw=stable_heading_map_raw,
            docx_links_by_para=docx_links_by_para,
            edit_tables=edit_tables,
        )
        session_data['owner'] = current_uid()
        session_data['doc_hash'] = compute_sha256(src)
        save_session_data(session, session_data)
        logger.info(f"Session saved: {session_id}")

        # Redirect to heading crosswalk if mapping to new numbers; otherwise go to reference review
        if session_data['mapping_mode'] == "keep_old":
            return redirect(url_for('review', session_id=session_id))
        return redirect(url_for('heading_review', session_id=session_id))

    except subprocess.CalledProcessError as e:
        logger.exception("Pandoc conversion failed")
        flash(f"Pandoc conversion failed. Is Pandoc installed and on PATH? ({e})")
        return redirect(url_for("index"))
    except Exception as e:
        logger.exception("Conversion failed")
        flash(f"Conversion failed: {e}")
        return redirect(url_for("index"))

@app.route("/review/<uuid:session_id>", methods=["GET", "POST"])
def review(session_id):
    """Review crosswalk and references before conversion"""
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session expired or invalid.")
        return redirect(url_for("index"))


    # NEW WORKFLOW: Load auto_crosswalk and new_headings from pre-conversion
    auto_crosswalk = session_data.get('approved_crosswalk') or session_data.get('auto_crosswalk', {})
    approved_crosswalk = session_data.get('approved_crosswalk', {})
    new_headings = session_data.get('new_headings', {})
    references = session_data.get('references', [])
    html_import = session_data.get('html_import', False)
    rebuild_links = session_data.get('rebuild_links', False)
    edit_tables = session_data.get('edit_tables', False)
    mapping_mode = session_data.get('mapping_mode', 'map_new')
    linked_ref_count = 0
    if html_import and references:
        for ref in references:
            if len(ref) > 5 and ref[5]:
                linked_ref_count += 1
    has_tables = False
    src_path = Path(session_data.get('src_path', ''))
    html_path = Path(session_data.get('html_path', ''))
    if html_import and html_path.exists():
        has_tables = has_tables_in_html(html_path)
    elif src_path.exists():
        has_tables = has_tables_in_docx(src_path)

    page_size = 50
    try:
        page = int(request.values.get('page', '1'))
    except Exception:
        page = 1
    # Group references by paragraph for display
    # Use stable IDs based on content, not sequential order
    ref_by_para = {}
    for ref in references:
        para_idx = ref[0]
        full_text = ref[1]
        old_ref = ref[2]
        start_pos = ref[3]
        # Generate stable ID based on location and content
        stable_id = generate_stable_ref_id(para_idx, start_pos, old_ref)
        if para_idx not in ref_by_para:
            ref_by_para[para_idx] = []
        ref_by_para[para_idx].append((ref, stable_id))
    para_keys = sorted(ref_by_para.keys())
    total_paras = len(para_keys)
    total_pages = max(1, math.ceil(total_paras / page_size))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_para_keys = para_keys[start_idx:end_idx]
    showing_start = start_idx + 1 if total_paras else 0
    showing_end = min(end_idx, total_paras)
    manual_type = session_data.get('manual_type', 'chapter')
    filename = session_data.get('filename', '')
    session_doc_hash = session_data.get('doc_hash') or ""

    logger.debug(f"Session loaded - new_headings has {len(new_headings)} entries, references has {len(references)} entries")
    logger.debug(f"Auto-matched {len(auto_crosswalk)} OLD->NEW references")
    if len(new_headings) == 0:
        logger.warning("new_headings is empty; pre-conversion may have failed.")
    else:
        logger.debug(f"Sample new headings: {list(new_headings.keys())[:3]}")
    
    if request.method == 'POST':
        # Log the shape of the submission, not its contents: the form carries the
        # manual's reference text and operator-entered URLs, which do not belong
        # in a log file even at DEBUG.
        logger.debug(
            "review POST: %d form keys, buttons=%s",
            len(request.form),
            [k for k in ("save_edits", "proceed", "next_page", "prev_page") if k in request.form],
        )

        # Save on any POST so Enter submits don't drop changes.

        # Save reference edits, validations, and link targets to persistent file
        edits = {}
        validations = {}
        link_targets = {}
        ignored = {}
        external_urls = {}
        if html_import:
            rebuild_links = 'rebuild_links' in request.form
            session_data['rebuild_links'] = rebuild_links
        # edit_tables was set during initial upload; preserve it from session
        edit_tables = session_data.get('edit_tables', False)
        edit_file = session.edits_json
        existing_data = load_edits_data(session)
        edits = existing_data.get('reference_edits', {}) or {}
        validations = existing_data.get('reference_validations', {}) or {}
        link_targets = existing_data.get('reference_link_targets', {}) or {}
        ignored = existing_data.get('reference_ignored', {}) or {}
        external_urls = existing_data.get('reference_external_urls', {}) or {}

        # Collect all reference IDs from the form
        all_ref_ids = set()
        for key in request.form.keys():
            if key.startswith('ref_edit_'):
                ref_id = key.replace('ref_edit_', '')
                all_ref_ids.add(ref_id)
            elif key.startswith('ref_valid_'):
                ref_id = key.replace('ref_valid_', '')
                all_ref_ids.add(ref_id)
            elif key.startswith('ref_target_'):
                ref_id = key.replace('ref_target_', '')
                all_ref_ids.add(ref_id)
            elif key.startswith('ref_ignore_'):
                ref_id = key.replace('ref_ignore_', '')
                all_ref_ids.add(ref_id)
            elif key.startswith('ref_external_'):
                ref_id = key.replace('ref_external_', '')
                all_ref_ids.add(ref_id)

        logger.debug(f"Collected {len(all_ref_ids)} reference IDs from form: {sorted(list(all_ref_ids))[:10]}")

        # External URL values that could not be made into a safe link. Kept
        # so the operator is told which ones were not saved.
        rejected_external: list[str] = []
        # External URLs dropped because their reference is also marked Ignore.
        ignored_with_url: list[str] = []

        # Process edits, validations, and targets
        for ref_id in all_ref_ids:
            # ref_id is already a stable ID (e.g., "ref_42_123_a1b2c3d4"), use it directly
            edit_key = ref_id

            # Save edit text
            edit_value = request.form.get(f'ref_edit_{ref_id}', '').strip()
            if edit_value:
                edits[edit_key] = edit_value
            elif edit_key in edits:
                edits.pop(edit_key, None)

            # Save validation status (checkbox checked = valid)
            is_valid = f'ref_valid_{ref_id}' in request.form
            is_ignored = f'ref_ignore_{ref_id}' in request.form
            if is_ignored:
                is_valid = False
            validations[edit_key] = is_valid
            if is_ignored:
                ignored[edit_key] = True
            elif edit_key in ignored:
                ignored.pop(edit_key, None)

            # Save link target (heading to link to)
            target_value = request.form.get(f'ref_target_{ref_id}', '').strip()
            if target_value:
                link_targets[edit_key] = target_value
            elif edit_key in link_targets:
                link_targets.pop(edit_key, None)

            # Save external URL (link to other manuals). Only persist
            # safe-scheme URLs: the export re-sanitizes, but unsafe values
            # should not linger in session.json to be reused elsewhere.
            # A scheme-less host ("policies.wsu.edu/x") is promoted to
            # https rather than discarded; anything still refused is
            # reported below instead of vanishing from the form silently.
            external_raw = request.form.get(f'ref_external_{ref_id}', '').strip()
            external_value = normalize_external_href(external_raw)
            if is_ignored and external_value:
                # The two settings contradict and the pipeline resolves it in
                # favour of Ignore. Keep the URL anyway — an ignored reference is
                # never applied, so it is inert, and preserving it means unticking
                # Ignore recovers the operator's work instead of asking them to
                # retype it. Just say clearly that it is not in effect.
                ignored_with_url.append(external_value)
            if external_value:
                external_urls[edit_key] = external_value
            else:
                if external_raw and not is_ignored:
                    rejected_external.append(external_raw)
                external_urls.pop(edit_key, None)

            # Log the shape of the decision, never the content. These fields
            # carry policy text the operator curated and the URLs they chose;
            # neither belongs in a log file, even at DEBUG.
            logger.debug(
                "Saving %s: valid=%s ignored=%s edit=%s target=%s external=%s",
                ref_id, is_valid, is_ignored,
                bool(edit_value), bool(target_value), bool(external_value),
            )

        # Save to persistent edit file
        edit_data = {
            'document': filename,
            'doc_hash': session_doc_hash,
            'auto_crosswalk': auto_crosswalk,
            'approved_crosswalk': approved_crosswalk,
            'reference_edits': edits,
            'reference_validations': validations,
            'reference_link_targets': link_targets,
            'reference_ignored': ignored,
            'reference_external_urls': external_urls,
            'last_updated': str(datetime.now())
        }
        save_edits_data(session, edit_data)
        session_data['approved_crosswalk'] = approved_crosswalk
        session_data['reference_edits'] = edits
        session_data['reference_validations'] = validations
        session_data['reference_link_targets'] = link_targets
        session_data['reference_ignored'] = ignored
        session_data['reference_external_urls'] = external_urls
        save_session_data(session, session_data)

        # Count valid vs invalid references
        valid_count = sum(1 for v in validations.values() if v)
        invalid_count = sum(1 for v in validations.values() if not v)

        # Debug: print save location
        logger.debug(f"Saved edits to: {edit_file}")
        logger.debug(f"Saved data - edits: {len(edits)} entries, validations: {len(validations)} entries ({valid_count} valid, {invalid_count} invalid), link_targets: {len(link_targets)} entries, external_urls: {len(external_urls)} entries")
        logger.debug(f"Sample validations: {dict(list(validations.items())[:5])}")

        flash(
            f"Edits saved. {valid_count} reference(s) set to link, "
            f"{invalid_count} skipped. Export a session bundle to share or "
            "continue on another machine."
        )
        if rejected_external:
            unique_rejected = sorted(set(rejected_external))
            shown = ", ".join(f"“{value[:60]}”" for value in unique_rejected[:3])
            if len(unique_rejected) > 3:
                shown += f", and {len(unique_rejected) - 3} more"
            flash(
                f"⚠ {len(unique_rejected)} External URL value(s) were NOT saved — "
                f"only http(s), mailto:, and #anchor links are allowed: {shown}. "
                "Re-enter them as a full web address."
            )
            logger.warning("Rejected %d External URL value(s): %s",
                           len(unique_rejected), unique_rejected[:10])
        if ignored_with_url:
            unique_conflicts = sorted(set(ignored_with_url))
            shown = ", ".join(f"“{value[:60]}”" for value in unique_conflicts[:3])
            if len(unique_conflicts) > 3:
                shown += f", and {len(unique_conflicts) - 3} more"
            flash(
                f"⚠ {len(unique_conflicts)} External URL(s) are saved but NOT in effect, "
                f"because their reference is marked “Ignore”, which wins: {shown}. "
                "Untick Ignore on those references to apply them."
            )
            logger.info("%d External URL(s) held inactive behind Ignore: %s",
                           len(unique_conflicts), unique_conflicts[:10])
        if 'proceed' in request.form:
            if edit_tables and has_tables:
                return redirect(url_for('table_review', session_id=session_id))
            return redirect(url_for('do_convert', session_id=session_id))
        if 'next_page' in request.form:
            target_page = min(page + 1, total_pages)
            return redirect(url_for('review', session_id=session_id, page=target_page))
        if 'prev_page' in request.form:
            target_page = max(page - 1, 1)
            return redirect(url_for('review', session_id=session_id, page=target_page))
        return redirect(url_for('review', session_id=session_id, page=page))
    
    # Use approved_crosswalk if provided, else auto_crosswalk for displaying OLD->NEW mappings
    display_crosswalk = approved_crosswalk if approved_crosswalk else auto_crosswalk

    logger.debug(f"[review]: Using {'approved_crosswalk' if approved_crosswalk else 'auto_crosswalk'} with {len(display_crosswalk)} entries")
    if display_crosswalk:
        sample_items = list(display_crosswalk.items())[:5]
        logger.debug(f"[review]: Sample display_crosswalk: {sample_items}")
    
    # ---- Build review page data (rendered by templates/review.html) ----

    # Load existing edits, validations, and link targets first
    edit_file = session.edits_json
    edit_data = load_edits_data(session)
    # Same re-attachment the conversion does, so the review page shows the
    # operator their saved work against the edited document rather than a page
    # of blank fields. Persist it, so the next save writes the current ids.
    edit_data, remapped, discarded = remap_reference_edits(
        references,
        edit_data,
        trust_exact_ids=bool(session_doc_hash and edit_data.get('doc_hash') == session_doc_hash),
    )
    if remapped or discarded:
        save_edits_data(session, edit_data)
    if remapped:
        flash(
            f"The document changed since these edits were saved — {remapped} "
            "reference edit(s) were re-matched to their citations. Check them before converting."
        )
    if discarded:
        flash(
            f"⚠ {discarded} saved reference edit(s) could not be matched: a citation was added "
            "or removed, so there is no reliable way to tell which copy each edit belonged to. "
            "They are kept in the session but not applied — re-enter them below."
        )
    existing_edits = edit_data.get('reference_edits', {})
    existing_validations = edit_data.get('reference_validations', {})
    existing_link_targets = edit_data.get('reference_link_targets', {})
    existing_ignored = edit_data.get('reference_ignored', {})
    existing_external_urls = edit_data.get('reference_external_urls', {})

    # Build list of all NEW headings for dropdown (document order when available)
    numbered_headings = []
    unnumbered_headings = []

    def looks_numbered_heading(text: str) -> bool:
        if not text:
            return False
        if re.match(r'^(Chapter|Section)\s+[\w\dIVXLCDM]+', text, re.IGNORECASE):
            return True
        if re.match(r'^\d+(?:\.\d+)+\s+', text):
            return True
        if re.match(r'^[IVXLCDM]+\.[A-Z0-9]+', text, re.IGNORECASE):
            return True
        if re.match(r'^[A-Z]\.\s+', text):
            return True
        return False

    # Prefer document order if available; fallback to numeric sort.
    for heading_key, heading_data in sorted(new_headings.items(), key=heading_dropdown_sort):
        full_text = heading_data.get('full', '')
        synthetic_key = heading_key.startswith(('H1:', 'H2:', 'H3:', 'H4:', 'H5:', 'H6:'))
        is_numbered = looks_numbered_heading(full_text)
        # Include numbered headings even if they came from H1/H2 synthetic keys.
        if not synthetic_key or is_numbered:
            if is_numbered:
                numbered_headings.append(heading_data)
            else:
                if len(heading_data['text'].split()) <= 15:
                    unnumbered_headings.append(heading_data)
        else:
            # For un-numbered headings, only include if they are reasonably short.
            # This filters out full paragraphs that Pandoc might have marked as headings.
            if len(heading_data['text'].split()) <= 15:
                unnumbered_headings.append(heading_data)

    unnumbered_headings.sort(key=lambda h: (h.get('text') or h.get('full') or '').lower())
    dropdown_headings = numbered_headings + unnumbered_headings
    all_headings = [h['full'] for h in dropdown_headings]
    logger.debug(f"Building dropdown with {len(dropdown_headings)} headings")

    external_links_by_para = {}
    # docx_links_by_para is keyed by int paragraph index in-process, but a
    # session.json round-trip turns those keys into strings; coerce digit keys
    # back to int so the lookups below (which use the int para_idx from the
    # references) actually find the links instead of silently rendering none.
    docx_links_by_para = {
        (int(k) if isinstance(k, str) and k.isdigit() else k): v
        for k, v in (session_data.get('docx_links_by_para', {}) or {}).items()
    }
    if html_import:
        html_path = session_data.get('html_path', '')
        if html_path and Path(html_path).exists():
            try:
                raw_html = Path(html_path).read_text(encoding='utf-8', errors='ignore')
                manual_html, _ = extract_manual_fragment(raw_html)
                external_links_by_para = extract_external_links_from_html(manual_html)
            except Exception as e:
                logger.warning(f"Failed to extract external links from HTML import: {e}")
    if not external_links_by_para and references:
        external_links_by_para = extract_external_links_from_reference_text(references)

    paragraphs = []
    for para_idx in page_para_keys:
        refs_with_ids = ref_by_para[para_idx]
        full_text = refs_with_ids[0][0][1] if refs_with_ids else ""
        # Escape the paragraph text, then wrap each reference in a highlight span.
        highlighted = str(markup_escape(full_text))
        for ref, ref_id in refs_with_ids:
            esc_ref = str(markup_escape(ref[2]))
            highlighted = highlighted.replace(esc_ref, f'<span class="highlight">{esc_ref}</span>')

        docx_links = []
        for item in docx_links_by_para.get(para_idx, []):
            href = item.get("href") or ""
            text = item.get("text") or ""
            # Only emit a clickable href for safe schemes (http/https/mailto/
            # internal anchor); unsafe ones (javascript:, data:, …) render as
            # plain text via the template's empty-href branch.
            safe_href = href if is_safe_href(href) else ""
            docx_links.append({
                "href": safe_href,
                "label": text if text else href,
                "bad": bool(item.get("bad")),
            })

        ref_rows = []
        for ref, ref_id in refs_with_ids:
            old_ref = ref[2]

            # Auto-matched NEW reference, resolved to its full heading text
            auto_matched_new = auto_crosswalk.get(old_ref, "")
            auto_target_full = ""
            auto_match_found = bool(auto_matched_new and auto_matched_new in new_headings)
            if auto_match_found:
                full_new_heading = new_headings[auto_matched_new]['full']
                auto_target_full = full_new_heading
            else:
                full_new_heading = "Not auto-matched"

            # Existing manual edit overrides the auto-match
            edit_key = ref_id
            selected_target = existing_link_targets.get(edit_key, "")
            current_value = existing_edits.get(edit_key, "")
            if mapping_mode == "keep_old" and current_value and old_ref:
                target_label = (selected_target.split(' - ')[0] or '').strip() if selected_target else ''
                if not target_label and auto_target_full:
                    target_label = (auto_target_full.split(' - ')[0] or '').strip()
                if target_label:
                    current_norm = normalize_heading_ref(current_value)
                    target_norm = normalize_heading_ref(target_label)
                    old_norm = normalize_heading_ref(old_ref)
                    if current_norm and target_norm and old_norm and current_norm == target_norm and current_norm != old_norm:
                        current_value = old_ref
            if not current_value:
                if mapping_mode == "keep_old" and old_ref:
                    current_value = old_ref
                else:
                    if selected_target:
                        current_value = (selected_target.split(' - ')[0] or '').strip()
                    elif auto_target_full:
                        selected_target = auto_target_full
                        current_value = (auto_target_full.split(' - ')[0] or '').strip()
            external_value = existing_external_urls.get(edit_key, "")
            # Only prefill the editable External URL field with safe-scheme
            # candidates (the export sanitizes again, but a javascript:/data:
            # default would be a useless prefill to surface to the operator).
            if not external_value:
                external_candidates = [h for h in external_links_by_para.get(para_idx, []) if is_safe_href(h)]
                if external_candidates:
                    external_value = external_candidates[0]
            if not external_value:
                for item in docx_links_by_para.get(para_idx, []):
                    href = item.get("href") or ""
                    if href and not item.get("bad") and is_safe_href(href):
                        external_value = href
                        break

            # Validation status (default false - user must explicitly validate)
            has_saved_validation = edit_key in existing_validations
            is_valid = existing_validations.get(edit_key, False)
            is_ignored = bool(existing_ignored.get(edit_key, False))
            if is_ignored:
                is_valid = False
            is_linked = bool(html_import and len(ref) > 5 and ref[5])
            is_read_only = bool(is_linked and not rebuild_links)
            if not has_saved_validation and auto_matched_new and auto_match_found:
                norm_old = normalize_heading_ref(old_ref)
                if norm_old:
                    norm_old = re.sub(r'^[\(\[]\s*', '', norm_old)
                    norm_old = re.sub(r'\s*[\)\]]$', '', norm_old)
                if mapping_mode == "keep_old":
                    norm_new = normalize_heading_ref(auto_matched_new)
                    if norm_new:
                        norm_new = re.sub(r'^[\(\[]\s*', '', norm_new)
                        norm_new = re.sub(r'\s*[\)\]]$', '', norm_new)
                    norm_old_no_prefix = re.sub(r'^(Chapter|Section)\s+', '', norm_old or '', flags=re.IGNORECASE)
                    norm_new_no_prefix = re.sub(r'^(Chapter|Section)\s+', '', norm_new or '', flags=re.IGNORECASE)
                    if norm_old and (norm_old == norm_new or norm_old_no_prefix == norm_new_no_prefix):
                        is_valid = True
                else:
                    is_valid = True

            has_been_reviewed = (
                edit_key in existing_validations
                or edit_key in existing_edits
                or edit_key in existing_link_targets
                or edit_key in existing_ignored
                or edit_key in existing_external_urls
            )
            if is_read_only:
                has_been_reviewed = True

            ref_rows.append({
                "ref_id": ref_id,
                "old_ref": old_ref,
                "full_new_heading": full_new_heading,
                "auto_target_full": auto_target_full,
                "auto_match_found": auto_match_found,
                "is_ignored": is_ignored,
                "is_read_only": is_read_only,
                "is_valid": is_valid,
                "checked": bool(is_valid and not is_read_only),
                "validation_class": "invalid" if is_read_only else ("" if is_valid else "invalid"),
                "review_status": "reviewed" if has_been_reviewed else "unreviewed",
                "review_indicator": "✓ Reviewed" if has_been_reviewed else "○ Not reviewed yet",
                "review_badge_color": "#10b981" if has_been_reviewed else "#9ca3af",
                "selected_target": selected_target,
                "current_value": current_value,
                "external_value": external_value,
            })

        paragraphs.append({
            "para_number": para_idx + 1,
            "highlighted_text": Markup(highlighted),
            "external_links": [h for h in external_links_by_para.get(para_idx, []) if is_safe_href(h)],
            "docx_links": docx_links,
            "refs": ref_rows,
        })

    valid_loaded = sum(1 for v in existing_validations.values() if v)
    invalid_loaded = sum(1 for v in existing_validations.values() if not v)

    return render_template(
        "review.html",
        session_id=session_id,
        filename=session_data.get('filename', 'Unknown'),
        manual_type=manual_type,
        references_count=len(references),
        page=page,
        total_pages=total_pages,
        showing_start=showing_start,
        showing_end=showing_end,
        total_paras=total_paras,
        auto_crosswalk_count=len(auto_crosswalk),
        headings_count=len(all_headings),
        existing_validations_count=len(existing_validations),
        valid_loaded=valid_loaded,
        invalid_loaded=invalid_loaded,
        html_import=html_import,
        linked_ref_count=linked_ref_count,
        rebuild_links=rebuild_links,
        edit_file_name=edit_file.name,
        dropdown_headings=all_headings,
        paragraphs=paragraphs,
        **session_retention_context(session),
    )

# Sample HTML for table review live preview when the session has no real table yet.
_TABLE_REVIEW_PREVIEW_SAMPLE = (
    '<div class="manual"><table>'
    '<thead><tr><th>Policy area</th><th>Code</th><th>Description</th></tr></thead>'
    "<tbody>"
    "<tr><td>Section I</td><td>101</td><td>First column is a normal body cell (not a header row).</td></tr>"
    "<tr><td>Sub-item</td><td>1,250</td><td>Numeric column for alignment preview.</td></tr>"
    "<tr><td>Another row</td><td>42</td><td>Shorter cell.</td></tr>"
    "<tr><td>Final example</td><td>900</td><td>More body content to show striping.</td></tr>"
    "</tbody></table></div>"
)


@app.route("/table_review/<uuid:session_id>/preview", methods=["POST"])
def table_review_preview(session_id):
    """Return theme table CSS + table HTML for live preview (JSON).

    Prefers the first table from this session's converted HTML; falls back to a
    labeled sample only when none is available.
    """
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        return jsonify({"ok": False, "error": "invalid_session"}), 404
    manual_type = session_data.get("manual_type", "chapter")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    settings, _ = coerce_theme_settings(body, manual_type)
    css = build_table_theme_css(settings)

    html_import = session_data.get("html_import", False)
    html_path = Path(session_data.get("html_path", ""))
    source = html_path if (html_import and html_path.exists()) else session.temp_html
    real_table = first_manual_table_html(source)
    using_sample = real_table is None
    preview_src = real_table or _TABLE_REVIEW_PREVIEW_SAMPLE

    aligned = format_manual_tables(
        preview_src,
        settings.get("table_align_mode", "auto"),
        settings.get("table_col1_align"),
        settings.get("table_coln_align"),
        settings.get("table_header_align"),
        col2_align=settings.get("table_col2_align"),
        col3_align=settings.get("table_col3_align"),
    )
    soup = BeautifulSoup(aligned, "html.parser")
    tbl = soup.find("table")
    table_html = str(tbl) if tbl else "<table></table>"
    return jsonify({
        "ok": True,
        "css": css,
        "table_html": table_html,
        "using_sample": using_sample,
    })


@app.route("/table_review/<uuid:session_id>", methods=["GET", "POST"])
def table_review(session_id):
    """Review table formatting options before conversion."""
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session expired or invalid.")
        return redirect(url_for("index"))

    html_import = session_data.get('html_import', False)
    src_path = Path(session_data.get('src_path', ''))
    html_path = Path(session_data.get('html_path', ''))
    has_tables = False
    if html_import and html_path.exists():
        has_tables = has_tables_in_html(html_path)
    elif src_path.exists():
        has_tables = has_tables_in_docx(src_path)
    if not has_tables:
        return redirect(url_for("do_convert", session_id=session_id))

    manual_type = session_data.get('manual_type', 'chapter')
    theme_settings, warnings = coerce_theme_settings(session_data.get('theme_settings'), manual_type)

    detected_cols = 0
    table_source = html_path if (html_import and html_path.exists()) else session.temp_html
    if table_source.exists():
        detected_cols = max_columns_in_first_table(table_source)
    tables = describe_tables(
        table_source,
        theme_settings.get("table_headers"),
        theme_settings.get("table_aligns"),
        theme_settings.get("table_blocks"),
    )
    sw_bg = wsu_swatch_buttons_html("table_header_bg")
    sw_hc = wsu_swatch_buttons_html("table_header_color")
    sw_bc = wsu_swatch_buttons_html("table_border_color")
    sw_sc = wsu_swatch_buttons_html("table_row_stripe_color")

    if request.method == "POST":
        fd = request.form.to_dict()
        for bkey in ("table_header_bold", "table_row_stripe"):
            if bkey not in request.form:
                fd[bkey] = ""
        updates = session_data.get("theme_settings", {}).copy()
        updates.update(fd)
        theme_settings, warnings = coerce_theme_settings(updates, manual_type)
        session_data['theme_settings'] = theme_settings
        save_session_data(session, session_data)
        if 'back' in request.form:
            return redirect(url_for('review', session_id=session_id))
        return redirect(url_for("do_convert", session_id=session_id))

    return render_template(
        "table_review.html",
        session_id=session_id,
        manual_type=manual_type,
        detected_cols=detected_cols,
        tables=tables,
        theme_settings=theme_settings,
        sw_bg=sw_bg,
        sw_hc=sw_hc,
        sw_bc=sw_bc,
        sw_sc=sw_sc,
        wp_css_text=get_wp_css_text(),
        **session_retention_context(session),
    )

def _preview_cache_key(session, pipeline_config, *, html_import, pre_path, manual_type,
                       theme_settings, theme_id, strip_docx_formatting, filename,
                       numbering_mode_hint, stable_heading_map=None):
    """Fingerprint of every input that affects do_convert's output.

    When the fingerprint matches the one stored at the last conversion, the
    preview is re-rendered from the saved artifacts instead of re-running
    Pandoc and the full pipeline on every GET. pipeline_config already carries
    the crosswalk, reference edits, heading edits, and stable map, so any
    review-step change invalidates the key; theme/table settings and the
    source file hash cover the rest.
    """
    source = (session.root / "import.html") if html_import else pre_path
    try:
        source_hash = compute_sha256(Path(source)) if source and Path(source).exists() else ""
    except OSError:
        source_hash = ""
    config = dict(pipeline_config)
    if stable_heading_map is not None:
        config['stable_heading_map'] = stable_heading_map
    # The static site assets are baked into the cached preview CSS and the
    # combined CSS artifact, so a deploy/edit to wordpress.css|js must bust the
    # cache (otherwise a refreshed session keeps serving the old stylesheet).
    assets_hash = hashlib.sha256(
        (get_wp_css_text() + "\x00" + get_wp_js_text()).encode("utf-8")
    ).hexdigest()
    fingerprint = {
        "pipeline_config": config,
        "manual_type": manual_type,
        "theme_settings": theme_settings,
        "theme_id": theme_id,
        "strip_docx_formatting": strip_docx_formatting,
        "filename": filename,
        "numbering_mode_hint": numbering_mode_hint,
        "source_hash": source_hash,
        "assets_hash": assets_hash,
    }
    return hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _load_cached_preview_parts(session, token):
    """Return the saved artifacts needed to re-render the preview, or None."""
    manual_path = session.root / f"{token}_manual.html"
    toc_path = session.root / f"{token}_toc.html"
    css_path = session.root / f"{token}_wordpress.css"
    meta_path = session.root / f"{token}_meta.json"
    if not (manual_path.exists() and toc_path.exists() and css_path.exists() and meta_path.exists()):
        return None
    try:
        return {
            "final_html": manual_path.read_text(encoding="utf-8"),
            "toc_html": toc_path.read_text(encoding="utf-8"),
            "combined_css": css_path.read_text(encoding="utf-8"),
            "meta": json.loads(meta_path.read_text(encoding="utf-8")),
        }
    except (OSError, json.JSONDecodeError):
        return None


@app.route("/convert/<uuid:session_id>", methods=["GET"])
def do_convert(session_id):
    """Perform the actual conversion after review"""
    session_id = str(session_id)
    session = SessionDir(session_id)
    session_data = load_session_data(session)
    if session_data is None or not session_owner_ok(session_data):
        flash("Session expired or invalid.")
        return redirect(url_for("index"))
    
    html_import = session_data.get('html_import', False)
    src_path = Path(session_data.get('src_path', '')) if session_data.get('src_path') else session.source_docx
    pre_path = Path(session_data.get('pre_path', '')) if session_data.get('pre_path') else session.pre_docx
    filename = session_data.get('filename', src_path.name)
    toc_depth = session_data.get('toc_depth', 2)
    preserve = session_data.get('preserve_numbers', False)
    manual_type = session_data.get('manual_type', 'chapter')
    mapping_mode = session_data.get('mapping_mode', 'map_new')
    numbering_mode = session_data.get('numbering_mode', "preserve" if preserve else "css-counters")
    rebuild_links = session_data.get('rebuild_links', False)
    strip_docx_formatting = session_data.get('strip_docx_formatting', False)
    infer_heading_depth = session_data.get('infer_heading_depth', False)
    infer_style_map = session_data.get('infer_style_map') or {}
    stable_heading_map = session_data.get('stable_heading_map') or {}
    heading_edits = session_data.get('heading_edits', {})
    theme_settings, theme_warnings = coerce_theme_settings(session_data.get('theme_settings'), manual_type)
    theme_id = theme_settings.get("theme_id", "manual")

    # Align preserve flag with mapping choice: keeping old headings implies keeping numbers
    # BUT: Respect the user's checkbox - only force preserve=True for keep_old, don't override checkbox for map_new
    if mapping_mode == "keep_old":
        preserve = True

    logger.debug(f"[do_convert]: mapping_mode={mapping_mode}, preserve={preserve} (from checkbox: {session_data.get('preserve_numbers', False)})")

    # NEW WORKFLOW: Load auto_crosswalk and new_headings
    auto_crosswalk = session_data.get('approved_crosswalk') or session_data.get('auto_crosswalk', {})
    new_headings = session_data.get('new_headings', {})
    original_references = session_data.get('references', [])

    # Load saved reference edits, validations, and link targets if they exist
    edit_file = session.edits_json
    session_doc_hash = session_data.get('doc_hash') or ""
    reference_edits = {}
    reference_validations = {}
    reference_link_targets = {}
    reference_ignored = {}
    reference_external_urls = {}
    if edit_file.exists():
        try:
            edit_data = json.loads(edit_file.read_text(encoding='utf-8'))
            # Re-attach edits whose citation moved because the DOCX was edited.
            # Reference ids encode paragraph position, so an inserted paragraph
            # shifts every id below it and the operator's curated link targets
            # and external URLs silently stop applying.
            edit_data, moved, dropped = remap_reference_edits(
                original_references,
                edit_data,
                trust_exact_ids=bool(session_doc_hash and edit_data.get('doc_hash') == session_doc_hash),
            )
            if moved:
                flash(
                    f"The document changed since these edits were saved — "
                    f"{moved} reference edit(s) were re-matched to their citations."
                )
            if dropped:
                flash(
                    f"⚠ {dropped} saved reference edit(s) could not be matched: a citation "
                    "was added or removed, so there is no reliable way to tell which copy "
                    "each edit belonged to. They are kept in the session but not applied — "
                    "re-enter them on the affected references."
                )
            reference_edits = edit_data.get('reference_edits', {})
            reference_validations = edit_data.get('reference_validations', {})
            reference_link_targets = edit_data.get('reference_link_targets', {})
            reference_ignored = edit_data.get('reference_ignored', {})
            reference_external_urls = edit_data.get('reference_external_urls', {})
            approved_from_edits = edit_data.get('approved_crosswalk')
            if approved_from_edits:
                auto_crosswalk = approved_from_edits
            logger.debug("="*80)
            logger.debug("Loaded reference edits from file")
            logger.debug(f"Edit file: {edit_file}")
            logger.debug(f"Loaded {len(reference_edits)} edits, {len(reference_validations)} validations, {len(reference_link_targets)} link targets")
            logger.debug(f"Ignored references: {len(reference_ignored)}")
            logger.debug(f"External URL references: {len(reference_external_urls)}")
            valid_count = sum(1 for v in reference_validations.values() if v)
            logger.debug(f"Valid references: {valid_count}, Invalid/False positives: {len(reference_validations) - valid_count}")
            if reference_validations:
                logger.debug(f"Sample validations (first 5): {dict(list(reference_validations.items())[:5])}")
        except Exception:
            logger.exception("Could not load edit file")
    else:
        logger.debug(f"No edit file found at: {edit_file}")
    
    # Now do the conversion
    try:
        # Pipeline configuration. Built before any work because it doubles as
        # the preview-cache fingerprint (see _preview_cache_key).
        pipeline_config = {
            'toc_depth': toc_depth,
            'mapping_mode': mapping_mode,
            'preserve_numbers': preserve,
            'infer_heading_depth': infer_heading_depth,
            'infer_style_map': infer_style_map,
            'stable_heading_map': stable_heading_map,
            'heading_edits': heading_edits,
            'table_align_mode': theme_settings.get('table_align_mode', 'auto'),
            'table_col1_align': theme_settings.get('table_col1_align'),
            'table_col2_align': theme_settings.get('table_col2_align'),
            'table_col3_align': theme_settings.get('table_col3_align'),
            'table_coln_align': theme_settings.get('table_coln_align'),
            'table_header_align': theme_settings.get('table_header_align'),
            'table_headers': theme_settings.get('table_headers', {}),
            'table_aligns': theme_settings.get('table_aligns', {}),
            'table_blocks': theme_settings.get('table_blocks', {}),
            'references': original_references,
            'reference_edits': reference_edits,
            'reference_validations': reference_validations,
            'reference_link_targets': reference_link_targets,
            'reference_ignored': reference_ignored,
            'reference_external_urls': reference_external_urls,
            'auto_crosswalk': auto_crosswalk,
            'new_headings': new_headings,
            'skip_linked_text': (html_import and not rebuild_links),
            'rebuild_links': bool(html_import and rebuild_links)
        }

        cache_key = _preview_cache_key(
            session, pipeline_config,
            html_import=html_import, pre_path=pre_path, manual_type=manual_type,
            theme_settings=theme_settings, theme_id=theme_id,
            strip_docx_formatting=strip_docx_formatting, filename=filename,
            numbering_mode_hint=session_data.get('numbering_mode'),
        )
        cached_token = session_data.get('token')
        if (session_data.get('convert_cache_key') == cache_key
                and cached_token and is_valid_session_id(cached_token)):
            parts = _load_cached_preview_parts(session, cached_token)
            if parts is not None:
                logger.info(f"[do_convert]: preview cache hit for session {session_id}; skipping reconversion")
                meta = parts["meta"]
                cached_numbering_mode = meta.get("numbering_mode") or numbering_mode
                manual_grid_block = build_manual_grid_block(
                    parts["final_html"],
                    toc_depth,
                    manual_type,
                    cached_numbering_mode,
                    theme_id=theme_id,
                    toc_html=parts["toc_html"],
                )
                wp_js = get_wp_js_text()
                return render_template("home.html",
                                       show_preview=True,
                                       hide_upload=True,
                                       body_html=manual_grid_block,
                                       token=cached_token,
                                       session_id=session_id,
                                       page_title=filename.replace('.docx', '').replace('_', ' ').title(),
                                       manual_type=manual_type,
                                       toc_depth=toc_depth,
                                       numbering_mode=cached_numbering_mode,
                                       wordpress_css_tag=f"<style>{parts['combined_css']}</style>",
                                       wordpress_js_tag=f"<script>{wp_js}</script>",
                                       theme_settings=theme_settings,
                                       has_tables=bool(meta.get("has_tables")),
                                       theme_id=theme_id,
                                       **session_retention_context(session))

        # 1. Source Acquisition
        if not html_import:
            out = session.export_html
            run_pandoc(pre_path, out)
            html_content = out.read_text(encoding="utf-8", errors="ignore")
        else:
            html_content = (session.root / "import.html").read_text(encoding="utf-8", errors="ignore")

        # 2. Unified Processing Pipeline (Single-Pass BeautifulSoup)
        final_html, toc_html = process_html_pipeline(html_content, session_id, pipeline_config)
        
        # Save processed body
        out = session.export_html
        out.write_text(final_html, encoding='utf-8')
        
        # 3. Build Preview Wrappers
        # Set numbering mode: "preserve" keeps original numbers, "css-counters" applies CSS auto-numbering
        numbering_mode = session_data.get('numbering_mode') if html_import else ("preserve" if preserve else "css-counters")
        
        # Single implementation for grid shell + a11y (see build_manual_grid_block)
        manual_grid_block = build_manual_grid_block(
            final_html,
            toc_depth,
            manual_type,
            numbering_mode,
            theme_id=theme_id,
            toc_html=toc_html,
        )

        has_tables_in_output = "<table" in final_html

        # 4. Export Artifacts
        # Each (re)conversion issues a fresh token; drop the previous token's
        # artifacts so repeated previews/theme tweaks don't accumulate files.
        old_token = session_data.get('token')
        if old_token and is_valid_session_id(old_token):
            for stale in session.root.glob(f"{old_token}_*"):
                try:
                    stale.unlink()
                except OSError:
                    pass

        token = str(uuid.uuid4())
        standalone_path = session.root / f"{token}_standalone.html"
        docx_html_path = session.root / f"{token}_docx_source.html"
        docx_path = session.root / f"{token}_{src_path.stem}_numbered.docx"
        css_path = session.root / f"{token}_wordpress.css"
        manual_content_path = session.root / f"{token}_manual.html"
        manual_content_raw_path = session.root / f"{token}_manual_raw.html"
        
        # Save manual content (+ TOC so a cache hit can rebuild the preview)
        manual_content_path.write_text(final_html, encoding='utf-8')
        manual_content_raw_path.write_text(final_html, encoding='utf-8')
        (session.root / f"{token}_toc.html").write_text(toc_html or "", encoding='utf-8')

        # Build combined CSS
        wp_css = get_wp_css_text()
        wp_js = get_wp_js_text()
        theme_css = build_theme_css(theme_settings)
        combined_css = f"{wp_css}\n{theme_css}"
        css_path.write_text(combined_css, encoding='utf-8')

        # Standalone HTML
        standalone_html = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(filename)}</title><style>{combined_css}</style></head><body>{manual_grid_block}<script>{wp_js}</script></body></html>'
        standalone_path.write_text(standalone_html, encoding='utf-8')

        # DOCX Generation
        docx_ok = True
        try:
            # Re-generate numbered HTML for DOCX specifically (bakes in numbers)
            docx_source_html = final_html
            if strip_docx_formatting:
                docx_source_html = strip_inline_formatting(docx_source_html)

            # Note: apply_css_counter_numbering is still in the file for now
            numbered_html = apply_css_counter_numbering(docx_source_html, manual_type, preserve=preserve)
            numbered_html = sanitize_docx_ids_for_export(numbered_html)
            docx_html_path.write_text(f'<!doctype html><html><body>{numbered_html}</body></html>', encoding='utf-8')

            run_pandoc_html_to_docx(docx_html_path, docx_path)
            fix_numbering_xml(docx_path)
            sanitize_docx_styles(docx_path)
            relocate_body_level_bookmarks(docx_path)
        except Exception:
            docx_ok = False
            logger.exception("DOCX generation failed")
            flash("DOCX export failed — the HTML outputs above are unaffected. Check the server log for details.")

        # Metadata for download
        meta = {
            "session_id": session_id,
            "filename": filename,
            "manual_type": manual_type,
            "toc_depth": toc_depth,
            "numbering_mode": numbering_mode,
            "theme_settings": theme_settings,
            "theme_id": theme_id,
            "docx_path": str(docx_path),
            "docx_ok": docx_ok,
            "has_tables": has_tables_in_output,
            "docx_html_path": str(docx_html_path),
            "manual_content_path": str(manual_content_path),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        (session.root / f"{token}_meta.json").write_text(json.dumps(meta, indent=2), encoding='utf-8')

        session_data.update({
            'token': token,
            'manual_content_path': str(manual_content_path),
            'manual_content_raw_path': str(manual_content_raw_path),
            'css_path': str(css_path),
            'numbering_mode': numbering_mode,
            'theme_settings': theme_settings
        })
        save_stable_heading_map(session_id, final_html)
        try:
            if session.stable_map_json.exists():
                session_data["stable_heading_map"] = json.loads(
                    session.stable_map_json.read_text(encoding="utf-8")
                )
        except Exception as e:
            logger.warning("Could not reload stable_heading_map into session: %s", e)
        # Store the fingerprint the NEXT GET will compute: the stable heading
        # map was just regenerated from this output, so re-running with it
        # yields identical HTML — recompute the key with the updated map so an
        # immediate refresh is a cache hit rather than a wasted reconversion.
        session_data['convert_cache_key'] = _preview_cache_key(
            session, pipeline_config,
            html_import=html_import, pre_path=pre_path, manual_type=manual_type,
            theme_settings=theme_settings, theme_id=theme_id,
            strip_docx_formatting=strip_docx_formatting, filename=filename,
            numbering_mode_hint=session_data.get('numbering_mode'),
            stable_heading_map=session_data.get("stable_heading_map") or {},
        )
        save_session_data(session, session_data)

        return render_template("home.html", 
                                    show_preview=True, 
                                    hide_upload=True, 
                                    # Full grid shell so inlined wordpress.js finds .manual-grid / .manual-toc
                                    body_html=manual_grid_block,
                                    token=token, 
                                    session_id=session_id,
                                    page_title=filename.replace('.docx', '').replace('_', ' ').title(),
                                    manual_type=manual_type,
                                    toc_depth=toc_depth,
                                    numbering_mode=numbering_mode,
                                    wordpress_css_tag=f"<style>{combined_css}</style>",
                                    wordpress_js_tag=f"<script>{wp_js}</script>",
                                    theme_settings=theme_settings,
                                    has_tables=has_tables_in_output,
                                    theme_id=theme_id,
                                    **session_retention_context(session))

    except Exception as e:
        logger.exception("Conversion failed")
        flash(f"Conversion failed: {e}")
        return redirect(url_for("index"))
