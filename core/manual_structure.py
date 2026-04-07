import logging
import re
from bs4 import BeautifulSoup
from .permalinks import normalize_heading_ref, ensure_prefixed, SPELLED_NUMS
from utils.helpers import roman_to_int

logger = logging.getLogger(__name__)

def parse_heading_key(key: str) -> tuple:
    """
    Parse a heading key like 'Chapter 1.4.2' or 'Section I.A.2' into a sortable tuple.
    """
    if not key:
        return ()
    key = key.strip()
    m = re.match(r'^(Chapter|Section)\s+(.+)$', key, re.IGNORECASE)
    rest = m.group(2) if m else key
    parts = [p for p in rest.replace('-', '.').split('.') if p]
    parsed = []
    for p in parts:
        rv = roman_to_int(p)
        if rv and rv > 0:
            parsed.append(rv)
        elif p.isdigit():
            parsed.append(int(p))
        elif len(p) == 1 and p.isalpha():
            parsed.append(ord(p.upper()) - ord('A') + 1)
        else:
            parsed.append(p.lower())
    return tuple(parsed)

def heading_sort_key(ref: str):
    """
    Safe sort key for headings that avoids int/str comparison by tagging parts.
    Returns tuple of (tag, value) where tag=0 for numbers, 1 for strings.
    """
    parts = parse_heading_key(ref)
    if not parts:
        return (2, ref.lower())
    tagged = []
    for p in parts:
        if isinstance(p, int):
            tagged.append((0, p))
        else:
            tagged.append((1, str(p)))
    return tuple(tagged)

def heading_dropdown_sort(item: tuple[str, dict]):
    key, data = item
    order = data.get('order')
    if isinstance(order, int):
        return (0, order)
    return (1, heading_sort_key(key))

def build_display_text_from_heading(heading_key: str, heading_full: str) -> str:
    """Build a user-friendly display string for a heading."""
    return f"{heading_key}: {heading_full}"

def find_heading_by_full(target_full: str, headings: dict):
    """Find a heading by full text. Returns (ref_key, heading_data) or (None, None)."""
    if not target_full or not headings:
        return None, None

    def normalize_full(value: str) -> str:
        value = (value or "").replace('\u00a0', ' ')
        value = re.sub(r'\s+', ' ', value).strip().lower()
        value = re.sub(r'[^a-z0-9\s]', '', value)
        return value

    target_norm = normalize_full(target_full)
    for heading_key, heading_data in headings.items():
        full_value = heading_data.get('full') or ''
        if full_value == target_full:
            return heading_key, heading_data
        if target_norm and normalize_full(full_value) == target_norm:
            return heading_key, heading_data
        text_value = heading_data.get('text') or heading_data.get('title') or ''
        if target_norm and normalize_full(text_value) == target_norm:
            return heading_key, heading_data
    return None, None

def build_heading_crosswalk_from_map(heading_map: dict, manual_type: str = "chapter") -> tuple[dict, dict]:
    """
    Build a proposed OLD->NEW heading crosswalk from the extracted heading_map.
    Returns (crosswalk, order_map) where order_map preserves document order.
    """
    crosswalk = {}
    order_map = {}

    print(f"DEBUG [build_crosswalk]: Building from heading_map with {len(heading_map)} entries")
    if heading_map:
        sample_keys = list(heading_map.keys())[:10]
        print(f"DEBUG [build_crosswalk]: Sample heading_map keys: {sample_keys}")

    for idx, (old_ref, title) in enumerate(heading_map.items()):
        # Skip synthetic keys (un-numbered headings) - they'll get CSS counters automatically
        if old_ref.startswith("_h"):
            if idx < 10:
                print(f"DEBUG [build_crosswalk]: Skipping un-numbered heading: '{title[:50]}'")
            continue

        # Ensure prefix FIRST so normalization can handle spelled numbers like "Chapter One"
        # This deduplicates "One" and "Chapter One" -> "Chapter 1"
        prefixed_old = ensure_prefixed(old_ref, manual_type)
        norm_old = normalize_heading_ref(prefixed_old)

        if not norm_old:
            continue

        old_with_prefix = norm_old

        # Enable debug for first 5 conversions
        debug_this = idx < 5
        predicted = convert_old_numbering_to_new(old_with_prefix, debug=debug_this) or old_with_prefix
        predicted = ensure_prefixed(normalize_heading_ref(predicted), manual_type)

        if old_with_prefix not in crosswalk:
            crosswalk[old_with_prefix] = predicted
            order_map[old_with_prefix] = idx

        # Debug first few entries to see the transformation
        if debug_this:
            same = "WARNING SAME!" if old_with_prefix == predicted else "OK Different"
            print(f"DEBUG [build_crosswalk #{idx}]: '{old_ref}' (title: '{title[:30]}...')")
            print(f"  -> normalized: '{norm_old}'")
            print(f"  -> with_prefix: '{old_with_prefix}'")
            print(f"  -> predicted: '{predicted}' {same}")

    print(f"DEBUG [build_crosswalk]: Built {len(crosswalk)} crosswalk entries")
    return crosswalk, order_map

def lookup_heading_title(ref: str, heading_map: dict, debug: bool = False) -> str:
    """
    Resolve a title for a given ref using common normalized variants.
    """
    if not ref:
        return ""
    candidates = []
    norm = normalize_heading_ref(ref)
    candidates.append(ref)
    if norm:
        candidates.append(norm)
    no_prefix = re.sub(r'^(Chapter|Section)\s+', '', norm, flags=re.IGNORECASE) if norm else ""
    if no_prefix:
        candidates.append(no_prefix)

    for cand in candidates:
        if cand in heading_map and heading_map[cand]:
            if debug:
                print(f"DEBUG [lookup_title]: Found title for '{ref}' using candidate '{cand}': '{heading_map[cand][:50]}...'")
            return heading_map[cand]

    norm = normalize_heading_ref(ref)
    norm_no_prefix = re.sub(r'^(Chapter|Section)\s+', '', norm, flags=re.IGNORECASE) if norm else ""
    for key, title in heading_map.items():
        if not key or not title:
            continue
        key_norm = normalize_heading_ref(key)
        if key_norm and (key_norm == norm or key_norm == norm_no_prefix):
            if debug:
                print(f"DEBUG [lookup_title]: Found title for '{ref}' using normalized key '{key_norm}': '{title[:50]}...'")
            return title
        key_no_prefix = re.sub(r'^(Chapter|Section)\s+', '', key_norm, flags=re.IGNORECASE)
        if key_no_prefix and (key_no_prefix == norm or key_no_prefix == norm_no_prefix):
            if debug:
                print(f"DEBUG [lookup_title]: Found title for '{ref}' using normalized key no-prefix '{key_no_prefix}': '{title[:50]}...'")
            return title

    if debug:
        print(f"DEBUG [lookup_title]: No title found for '{ref}', tried: {candidates}")
        print(f"DEBUG [lookup_title]: Sample heading_map keys: {list(heading_map.keys())[:5]}")
    return ""

def find_heading_order_violations(html: str) -> list[dict]:
    """Identify headings that skip levels (e.g., H1 followed by H3)."""
    soup = BeautifulSoup(html, 'html.parser')
    headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    violations = []
    prev_level = 0
    for h in headings:
        curr_level = int(h.name[1])
        if curr_level > prev_level + 1 and prev_level != 0:
            violations.append({
                "id": h.get('id', ''),
                "text": h.get_text().strip(),
                "prev_level": prev_level,
                "curr_level": curr_level
            })
        prev_level = curr_level
    return violations

def extract_heading_editor_rows(html: str) -> list[dict]:
    """Extract heading data for the review table."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        rows.append({
            "id": h.get('id', ''),
            "level": int(h.name[1]),
            "text": h.get_text().strip()
        })
    return rows

def extract_heading_edits_from_form(form) -> dict:
    """Parse heading edits from the review form."""
    edits = {}
    for key, value in form.items():
        if key.startswith("heading_text_"):
            hid = key.replace("heading_text_", "")
            lvl_key = f"heading_level_{hid}"
            lvl = int(form.get(lvl_key, 0))
            edits[hid] = {"text": value, "level": lvl}
    return edits

def scrape_heading_structure_from_html(html: str) -> dict:
    """
    Scrape the NEW heading structure from converted HTML (after CSS numbering applied).
    Returns: {
        "Chapter 1.4": {
            "text": "Graduate Faculty",
            "full": "Chapter 1.4 - Graduate Faculty",
            "level": "h2",
            "id": "graduate-faculty",
            "order": 0
        },
        ...
    }

    Also handles headings without Chapter/Section prefixes (for preserve mode).
    Builds hierarchical numbering by tracking context (e.g., Section I.B.3).
    """
    soup = BeautifulSoup(html, 'html.parser')
    headings = {}

    # Track current numbering context at each level for hierarchical building
    current_context = {"prefix": None, "h1": None, "h2": None, "h3": None, "h4": None, "h5": None, "h6": None}
    level_names = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

    order_idx = 0
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = heading.get_text().strip()
        level = heading.name

        # Skip empty headings
        if not text:
            continue

        # Try to parse full chapter/section number from heading
        full_match = re.match(r'^(Chapter|Section)\s+([\d\w.]+)\s*[-:\u2013\u2014.]\s*(.+)', text, re.IGNORECASE)

        if full_match:
            prefix = full_match.group(1)
            number = full_match.group(2)
            title = full_match.group(3).strip()

            key = f"{prefix} {number}"

            current_context["prefix"] = prefix
            parts = number.replace('.', ' ').split()
            for i, part in enumerate(parts):
                if i < len(level_names):
                    current_context[level_names[i]] = part
            for i in range(len(parts), len(level_names)):
                current_context[level_names[i]] = None

            existing_id = heading.get('id', '')
            if existing_id:
                slug = existing_id
            else:
                slug = re.sub(r'^[\d\.\s]+', '', title)
                slug = re.sub(r'[^\w\s-]', '', slug)
                slug = re.sub(r'[\s_]+', '-', slug)
                slug = slug.strip('-').lower()[:50]

            headings[key] = {
                'text': title,
                'full': text,
                'level': level,
                'id': slug,
                'order': order_idx
            }
            order_idx += 1
        else:
            # Heading without full Chapter/Section prefix
            partial_match = re.match(r'^((?:[0-9]+|[IVXLCDM]{1,10}|[A-Z])(?:\.[A-Z0-9]+)*\.?)[\s\t]+(.+)', text)

            if partial_match and current_context["prefix"]:
                full_num_str = partial_match.group(1).upper().rstrip('.')
                title = partial_match.group(2).strip()

                if full_num_str in ['IN', 'TO', 'OR', 'AS', 'AT', 'BY', 'OF', 'ON', 'THE', 'FOR', 'AND']:
                    partial_match = None

            if partial_match and current_context["prefix"]:
                parts = full_num_str.split('.')
                level_idx = level_names.index(level)
                effective_parts = list(parts)

                if len(parts) > 1:
                    for i, part in enumerate(parts):
                        if i < len(level_names):
                            current_context[level_names[i]] = part

                    if len(parts) <= level_idx:
                        sub_match = re.match(r'^([A-Z\d]+)[\.\s]+(.+)', title, re.IGNORECASE)
                        if sub_match:
                            sub_num = sub_match.group(1).upper()
                            title = sub_match.group(2).strip()
                            next_slot_idx = len(parts)
                            if next_slot_idx < len(level_names):
                                current_context[level_names[next_slot_idx]] = sub_num
                                effective_parts.append(sub_num)
                else:
                    partial_num = parts[0]
                    current_context[level] = partial_num

                depth = min(len(effective_parts), len(level_names)) if len(parts) > 1 else (level_idx + 1)

                for i in range(depth, len(level_names)):
                    current_context[level_names[i]] = None

                parts_out = []
                for i in range(depth):
                    val = current_context[level_names[i]]
                    if val:
                        parts_out.append(str(val))
                    else:
                        parts_out.append('?')

                if parts_out:
                    full_number = '.'.join(parts_out)
                    key = f"{current_context['prefix']} {full_number}"
                    full_text = f"{key} - {title}"

                    existing_id = heading.get('id', '')
                    if existing_id:
                        slug = existing_id
                    else:
                        slug = re.sub(r'[^\w\s-]', '', title)
                        slug = re.sub(r'[\s_]+', '-', slug)
                        slug = slug.strip('-').lower()[:50]

                    headings[key] = {
                        'text': title,
                        'full': full_text,
                        'level': level,
                        'id': slug,
                        'order': order_idx
                    }
                    order_idx += 1
                else:
                    key = f"{level.upper()}: {text[:50]}"
                    existing_id = heading.get('id', '')
                    slug = existing_id if existing_id else re.sub(r'[^\w\s-]', '', text).replace(' ', '-').strip('-').lower()[:50]

                    headings[key] = {
                        'text': text,
                        'full': text,
                        'level': level,
                        'id': slug,
                        'order': order_idx
                    }
                    order_idx += 1
            else:
                existing_id = heading.get('id', '')
                if existing_id:
                    slug = existing_id
                else:
                    slug = re.sub(r'[^\w\s-]', '', text)
                    slug = re.sub(r'[\s_]+', '-', slug)
                    slug = slug.strip('-').lower()[:50]

                key = f"{level.upper()}: {text[:50]}"

                headings[key] = {
                    'text': text,
                    'full': text,
                    'level': level,
                    'id': slug,
                    'order': order_idx
                }
                order_idx += 1

    print(f"DEBUG: Scraped {len(headings)} NEW headings from HTML")
    return headings

def auto_match_old_to_new_references(old_references: list, new_structure: dict, manual_type: str = "chapter") -> dict:
    """
    Auto-match OLD references to NEW headings.
    Uses numbering conversion, Chapter/Section swaps, and Roman→Arabic variants
    to generate candidate matches.
    Returns: {"Chapter 1.D.4": "Chapter 1.4.4", ...}
    """
    crosswalk = {}

    print(f"DEBUG [auto_match]: Matching {len(old_references)} references to {len(new_structure)} new headings")
    if new_structure:
        print(f"DEBUG [auto_match]: Sample new_headings keys: {list(new_structure.keys())[:5]}")

    for idx, ref in enumerate(old_references):
        old_ref_text = ref[2]  # Extract the reference string

        # Skip if it doesn't look like a chapter/section reference
        if not re.match(r'^(Chapter|Section)\s+[\dIVXLCDM]+', old_ref_text, re.IGNORECASE):
            continue

        # Skip obviously spurious huge numbers (likely artifacts)
        num_match = re.match(r'^(Chapter|Section)\s+([^\s]+)', old_ref_text, re.IGNORECASE)
        if num_match:
            first_part = num_match.group(2).split('.')[0]
            try:
                num_val = int(first_part)
            except ValueError:
                num_val = roman_to_int(first_part)
            if num_val and num_val > 50:
                print(f"DEBUG: Skipping auto-match for '{old_ref_text}' (unreasonably high leading number)")
                continue

        # Convert OLD to predicted NEW
        predicted_new = convert_old_numbering_to_new(old_ref_text, debug=(idx < 10))

        # Build candidate variants
        candidates = [predicted_new]
        if predicted_new.lower().startswith("chapter "):
            candidates.append(predicted_new.replace("Chapter ", "Section ", 1))
        elif predicted_new.lower().startswith("section "):
            candidates.append(predicted_new.replace("Section ", "Chapter ", 1))

        # Roman -> Arabic variant for FM-style numbering
        m = re.match(r'^(Chapter|Section)\s+(.+)$', old_ref_text, re.IGNORECASE)
        if m:
            prefix = m.group(1).title()
            numbering = m.group(2).strip()
            parts = numbering.split(".")
            converted_parts = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                rv = roman_to_int(part)
                if rv > 0:
                    converted_parts.append(str(rv))
                elif len(part) == 1 and part.isalpha():
                    converted_parts.append(str(ord(part.upper()) - ord('A') + 1))
                else:
                    converted_parts.append(part)
            if converted_parts:
                numeric = ".".join(converted_parts)
                candidates.append(f"{prefix} {numeric}")

        if manual_type == "chapter":
            norm = []
            for c in candidates:
                if c.lower().startswith("section "):
                    norm.append(c.replace("Section ", "Chapter ", 1))
                norm.append(c)
            candidates = norm

        # Dedupe preserving order
        seen = set()
        deduped = []
        for c in candidates:
            if c not in seen:
                deduped.append(c)
                seen.add(c)
        candidates = deduped

        matched = None
        for cand in candidates:
            if cand in new_structure:
                matched = cand
                break

        if matched:
            crosswalk[old_ref_text] = matched
            print(f"DEBUG: Auto-matched: '{old_ref_text}' -> '{matched}' (candidates: {candidates})")
        else:
            # Validate the predicted reference before using it
            predicted_valid = True
            pred_match = re.match(r'^(Chapter|Section)\s+(.+)$', predicted_new, re.IGNORECASE)
            if pred_match:
                numbering_parts = pred_match.group(2).split('.')
                for part in numbering_parts:
                    try:
                        if int(part) > 50:
                            predicted_valid = False
                            if idx < 10:
                                print(f"DEBUG: Rejecting predicted '{predicted_new}' - contains unreasonably high number: {part}")
                            break
                    except ValueError:
                        pass  # Not a number, keep it

            if predicted_valid:
                crosswalk[old_ref_text] = predicted_new
                if idx < 10:
                    print(f"DEBUG: Predicted (no heading match): '{old_ref_text}' -> '{predicted_new}' (candidates tried: {candidates})")
            else:
                if idx < 10:
                    print(f"DEBUG: Skipping '{old_ref_text}' - predicted value '{predicted_new}' is invalid")

    print(f"DEBUG [auto_match]: Built crosswalk with {len(crosswalk)} entries")
    if crosswalk:
        sample_items = list(crosswalk.items())[:3]
        print(f"DEBUG [auto_match]: Sample crosswalk: {sample_items}")

    return crosswalk

def convert_old_numbering_to_new(old_ref: str, debug: bool = False) -> str:
    """
    Convert old-style numbering (with letters) to new-style (numeric).
    Examples:
        "Chapter 1.D.4" -> "Chapter 1.4.4"
        "Chapter 1D" -> "Chapter 1.4"
        "Section I.A.2.b" -> "Section 1.1.2.2"
    """
    # Extract prefix and numbering - handle both "1.D" and "1D" formats
    # Use greedy match to capture ALL numbering parts
    match = re.match(r'^(Chapter|Section)\s+(.+?)(?:\s+[-\u2013\u2014:]|$)', old_ref, re.IGNORECASE)
    if not match:
        if debug:
            print(f"DEBUG [convert]: No match for '{old_ref}'")
        return old_ref

    prefix = match.group(1)
    numbering = match.group(2).strip()

    if debug:
        print(f"DEBUG [convert]: Input: '{old_ref}'")
        print(f"DEBUG [convert]: Extracted prefix: '{prefix}', numbering: '{numbering}'")
    # Handle spelled-out leading number (Chapter One)
    parts_spell = numbering.split('.')
    if parts_spell:
        first = parts_spell[0].strip()
        if first.lower() in SPELLED_NUMS:
            parts_spell[0] = str(SPELLED_NUMS[first.lower()])
            numbering = '.'.join(parts_spell)

    # Split by dots AND extract mixed alphanumeric parts like "1D" -> ["1", "D"]
    # First, insert dots before letters that follow numbers (e.g., "1D" -> "1.D")
    numbering = re.sub(r'(\d)([A-Za-z])', r'\1.\2', numbering)
    # Also insert dots before numbers that follow letters (e.g., "D4" -> "D.4")
    numbering = re.sub(r'([A-Za-z])(\d)', r'\1.\2', numbering)

    # Now split by dots
    parts = numbering.split('.')
    new_parts = []

    for idx, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        # Strategy: First level can be Roman numerals (I, II, III, IV, V, VI, VII, VIII, IX, X, XI, XII)
        # Sub-levels should treat single letters as letters (A=1, B=2, C=3), not Roman numerals

        is_first_level = (idx == 0)

        # Check if it's all Roman numeral characters
        if re.match(r'^[IVXLCDM]+$', part, re.IGNORECASE):
            roman_val = roman_to_int(part)

            # For FIRST level: Always try Roman conversion first (I, II, III, IV, etc.)
            if is_first_level and roman_val > 0 and roman_val <= 20:
                # Valid Roman numeral at top level (I through XX)
                new_parts.append(str(roman_val))
            # For SUB-levels: Only convert multi-character Romans (II, III, IV)
            # Single letters like C, D, M at sub-levels are LETTERS, not Roman 100, 500, 1000
            elif not is_first_level and len(part) > 1 and roman_val > 0:
                # Multi-character Roman at sub-level (rare but possible)
                new_parts.append(str(roman_val))
            elif len(part) == 1 and part.isalpha():
                # Single letter - convert as letter (A=1, B=2, C=3, etc.)
                letter_num = ord(part.upper()) - ord('A') + 1
                new_parts.append(str(letter_num))
            else:
                # Unknown format, keep as-is
                new_parts.append(part)
        # Check if it's a pure number (keep as-is)
        elif part.isdigit():
            new_parts.append(part)
        # Check if it's a single letter (convert to number: A=1, B=2, etc.)
        elif len(part) == 1 and part.isalpha():
            letter_num = ord(part.upper()) - ord('A') + 1
            new_parts.append(str(letter_num))
        else:
            # Unknown format, keep as-is
            new_parts.append(part)

    new_numbering = '.'.join(new_parts)
    result = f"{prefix} {new_numbering}"

    if debug:
        print(f"DEBUG [convert]: Parts after split: {parts}")
        print(f"DEBUG [convert]: Converted parts: {new_parts}")
        print(f"DEBUG [convert]: Result: '{result}'")

    return result

