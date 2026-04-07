import os
import re
import json
import logging
import uuid
import hashlib
from pathlib import Path
from bs4 import BeautifulSoup, Tag, NavigableString
from .permalinks import normalize_heading_signature
from utils.helpers import sanitize_theme_id, roman_to_int
from config import SessionDir

logger = logging.getLogger(__name__)

# Detect lxml once at import time; fall back to built-in parser if unavailable.
try:
    import lxml as _lxml_check  # noqa: F401
    _HTML_PARSER = 'lxml'
except ImportError:
    _HTML_PARSER = 'html.parser'

# --- Constants & Helpers from word_to_wordpressV4.py ---

_WHITESPACE_EQUIV = {
    '\u00a0': ' ',  # NBSP -> space
    '\u2009': ' ', '\u2002': ' ', '\u2003': ' ', '\u200a': ' ',
    '\u202f': ' ', '\u205f': ' ', '\u3000': ' '
}
_ZERO_WIDTH = {'\u200b', '\u200c', '\u200d'}

def _norm_char(c: str) -> str:
    if c in _ZERO_WIDTH:
        return ''  # contributes nothing
    return _WHITESPACE_EQUIV.get(c, c)

def _normalized(s: str) -> str:
    return ''.join(_norm_char(c) for c in s)

_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?i:(?:Chapter|Section))\s+[IVXLCDM\d]+(?:\.[A-Z\d]+)*(?:\s*[:.\\-])?\s+|"
    r"(?:\d+|[IVXLCDM]{1,6}|[A-Z]{1,3}|[a-z]{1,3})(?:[.\s]+(?:\d+|[IVXLCDM]{1,6}|[A-Z]{1,3}|[a-z]{1,3})){1,5}\.?\s+(?:[:.\\-]\s*)?|"
    r"(?i:[IVXLCDM]+)\.(?:[A-Z]{1,3}|[a-z]{1,3})(?:\.\d+){0,3}\.?\s+(?:[:.\\-]\s*)?|"
    r"(?i:[IVXLCDM]+)(?:\.\d+){0,3}\.?\s+(?:[:.\\-]\s*)?|"
    r"(?:[A-Z]{1,3}|[a-z]{1,3})\.\s+(?:[:.\\-]\s*)?|"
    r"\d+(?:\.\d+){0,3}(?:[.)])?\s+(?:[:.\\-]\s*)?"
    r")"
)

_HEADING_INFER_TOKEN = r'(?:\d+|[IVXLCDMivxlcdm]{1,6}|[A-Z]{1,3}|[a-z]{1,3})'
_HEADING_INFER_RE = re.compile(
    r'^\s*(?:(?i:Chapter|Section)\s+)?'
    r'(' + _HEADING_INFER_TOKEN + r'(?:\.\s*' + _HEADING_INFER_TOKEN + r'){1,5})\b'
)

def _is_numeric_or_roman(token: str) -> bool:
    if not token:
        return False
    if token.isdigit():
        return True
    return bool(re.fullmatch(r'[IVXLCDM]+', token, re.IGNORECASE))

def _extract_heading_prefix_tokens(text: str) -> list[str]:
    if not text:
        return []
    normalized = _normalized(text).strip()
    m = _HEADING_INFER_RE.match(normalized)
    if not m:
        return []
    seq = m.group(1)
    parts = [p.strip() for p in seq.split('.') if p.strip()]
    return parts

def _extract_style_map_tokens(text: str) -> list[str]:
    if not text:
        return []
    normalized = _normalized(text)
    m = _HEADING_PREFIX_RE.match(normalized)
    if not m:
        return []
    prefix = m.group(0)
    prefix = re.sub(r'^(?:Chapter|Section)\s+', '', prefix, flags=re.IGNORECASE).strip()
    prefix = re.sub(r'[:.\-\s]+$', '', prefix).strip()
    parts = [p for p in re.split(r'[.\s]+', prefix) if p]
    return parts

def _classify_token_for_style_map(token: str, parts_len: int, style_map: dict, prefer_roman_single: bool = False) -> str:
    if not token:
        return ""
    if token.isdigit():
        return "decimal"
    if re.fullmatch(r'[a-z]+', token, re.IGNORECASE):
        has_alpha = "alpha_lower" in style_map or "alpha_upper" in style_map
        has_roman = "roman_lower" in style_map or "roman_upper" in style_map
        if has_roman and not has_alpha:
            return "roman_lower" if token.islower() else "roman_upper"
        if has_alpha and not has_roman:
            return "alpha_lower" if token.islower() else "alpha_upper"
        if has_alpha and has_roman:
            # Ambiguity: C, D, I, V, X, L, M could be either
            if prefer_roman_single or parts_len >= 5:
                # Long sequences or explicit Roman context
                if re.fullmatch(r'[ivxlcdm]+', token, re.IGNORECASE):
                    return "roman_lower" if token.islower() else "roman_upper"
            # Default to alpha for single letters unless it's obviously roman
            if len(token) == 1:
                return "alpha_lower" if token.islower() else "alpha_upper"
            return "roman_lower" if token.islower() else "roman_upper"
    return ""


_alpha = re.compile(r'^\s*([a-zA-Z])[.)]\s+')
_decimal = re.compile(r'^\s*(\d+)[.)]\s+')
_roman  = re.compile(r'^\s*((?i:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx))[.)]\s+')

def _list_kind(m):
    if not m: return None
    if m.re is _alpha: return 'alpha'
    if m.re is _roman: return 'roman'
    if m.re is _decimal: return 'decimal'
    return None

def _list_rank(kind):
    return {'decimal': 0, 'alpha': 1, 'roman': 2}.get(kind, 0)

def _list_value(m):
    kind = _list_kind(m)
    if kind == 'decimal':
        try: return int(m.group(1))
        except: return None
    if kind == 'alpha':
        ch = m.group(1)
        return ord(ch.lower()) - ord('a') + 1 if ch else None
    if kind == 'roman':
        try: return roman_to_int(m.group(1))
        except: return None
    return None

def _kind_for_type_attr(type_attr: str) -> str:
    if type_attr in ('a', 'A'): return 'alpha'
    if type_attr in ('i', 'I'): return 'roman'
    return 'decimal'

def _infer_list_rank_order(soup: BeautifulSoup) -> dict[str, int]:
    default = {'decimal': 0, 'alpha': 1, 'roman': 2}
    edges = set()
    for ol in soup.find_all('ol'):
        parent = ol.find_parent('ol')
        if not parent: continue
        parent_kind = _kind_for_type_attr(parent.get('type', ''))
        child_kind = _kind_for_type_attr(ol.get('type', ''))
        if parent_kind and child_kind and parent_kind != child_kind:
            edges.add((parent_kind, child_kind))
    if not edges: return default
    kinds = ['decimal', 'alpha', 'roman']
    graph = {k: set() for k in kinds}; indeg = {k: 0 for k in kinds}
    for src, dst in edges:
        if dst not in graph[src]:
            graph[src].add(dst); indeg[dst] += 1
    order = []
    queue = sorted([k for k in kinds if indeg[k] == 0], key=kinds.index)
    while queue:
        node = queue.pop(0); order.append(node)
        for nxt in sorted(graph[node], key=kinds.index):
            indeg[nxt] -= 1
            if indeg[nxt] == 0: queue.append(nxt); queue.sort(key=kinds.index)
    return {k: idx for idx, k in enumerate(order)} if len(order) == len(kinds) else default

def _list_type_for(m):
    if not m: return ('ol', '')
    if m.re is _alpha:
        ch = m.group(1)
        return ('ol', 'a' if ch.islower() else 'A')
    if m.re is _roman:
        raw = m.group(1)
        return ('ol', 'i' if raw.islower() else 'I')
    return ('ol', '')

def _list_class_for_type(type_attr: str) -> str:
    mapping = {'a': 'list-alpha-lower', 'A': 'list-alpha-upper', 'i': 'list-roman-lower', 'I': 'list-roman-upper'}
    return mapping.get(type_attr, 'list-decimal')

def _apply_list_class(ol: Tag, type_attr: str) -> None:
    class_name = _list_class_for_type(type_attr)
    existing = ol.get('class', [])
    if isinstance(existing, str): existing = [existing]
    if class_name not in existing: existing.append(class_name)
    ol['class'] = existing

def _list_style_from_type_attr(type_attr: str) -> str | None:
    mapping = {'a': 'lower-alpha', 'A': 'upper-alpha', 'i': 'lower-roman', 'I': 'upper-roman', '1': 'decimal'}
    return mapping.get(type_attr)

def _list_style_from_class_list(class_list: list[str]) -> str | None:
    if 'list-alpha-lower' in class_list: return 'lower-alpha'
    if 'list-alpha-upper' in class_list: return 'upper-alpha'
    if 'list-roman-lower' in class_list: return 'lower-roman'
    if 'list-roman-upper' in class_list: return 'upper-roman'
    if 'list-decimal' in class_list: return 'decimal'
    return None

def _list_style_from_inline(style: str) -> str | None:
    m = re.search(r'list-style-type\s*:\s*([^;]+)', style, re.IGNORECASE)
    return m.group(1).strip().lower() if m else None

def _list_info_from_style(style_type: str | None) -> tuple[str, str | None] | None:
    if not style_type: return None
    if 'alpha' in style_type: return ('alpha', 'lower' if 'lower' in style_type else 'upper')
    if 'roman' in style_type: return ('roman', 'lower' if 'lower' in style_type else 'upper')
    if 'decimal' in style_type: return ('decimal', None)
    return None

def _style_from_list_info(kind: str, case: str | None) -> str:
    if kind == 'alpha': return 'lower-alpha' if case == 'lower' else 'upper-alpha'
    if kind == 'roman': return 'lower-roman' if case == 'lower' else 'upper-roman'
    return 'decimal'

def _type_from_list_info(kind: str, case: str | None) -> str:
    if kind == 'alpha': return 'a' if case == 'lower' else 'A'
    if kind == 'roman': return 'i' if case == 'lower' else 'I'
    return '1'

def _apply_list_style(ol: Tag, style_type: str) -> None:
    if not style_type: return
    ol['data-list-style'] = style_type
    style = ol.get('style', '')
    style = re.sub(r'(?i)list-style-type\s*:\s*[^;]+\s*(!important)?\s*;?', '', style).strip()
    if style and not style.endswith(';'): style += ';'
    ol['style'] = f"{style}list-style-type: {style_type} !important;"

def _after_prefix(tag: Tag, prefix_len: int, soup: BeautifulSoup):
    result = []
    remaining = prefix_len
    for child in list(tag.children):
        if remaining <= 0:
            result.append(child)
            continue
        if isinstance(child, NavigableString):
            s = str(child)
            if len(s) <= remaining:
                remaining -= len(s)
            else:
                result.append(NavigableString(s[remaining:]))
                remaining = 0
        elif isinstance(child, Tag):
            child_text_len = len(child.get_text())
            if child_text_len <= remaining:
                remaining -= child_text_len
            else:
                result.append(child)
                remaining = 0
    return result

def normalize_spaces(s: str) -> str:
    return (s.replace('\u00a0',' ').replace('\u200b','').replace('\u200c','').replace('\u200d',''))

def generate_stable_ref_id(para_idx: int, start_pos: int, ref_text: str) -> str:
    ref_hash = hashlib.md5(ref_text.encode('utf-8')).hexdigest()[:8]
    return f"ref_{para_idx}_{start_pos}_{ref_hash}"

def extract_body(html: str) -> str:
    soup = BeautifulSoup(html, _HTML_PARSER)
    body = soup.find('body')
    if body:
        return body.decode_contents()
    return html

def save_stable_heading_map(session_id: str, final_html: str) -> None:
    soup = BeautifulSoup(final_html, _HTML_PARSER)
    heading_map: dict[str, str] = {}
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        hid = (heading.get('id') or '').strip()
        if not hid:
            continue
        text = heading.get_text().strip()
        sig = normalize_heading_signature(text)
        if sig and hid:
            heading_map[sig] = hid
    session = SessionDir(session_id)
    session.stable_map_json.write_text(
        json.dumps(heading_map, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    logger.info("Saved stable heading map: %d entries", len(heading_map))

def strip_html_assets(html: str) -> str:
    soup = BeautifulSoup(html, _HTML_PARSER)
    for tag in soup.find_all(['script', 'style']):
        tag.decompose()
    for link in soup.find_all('link'):
        rel = link.get('rel') or []
        if not isinstance(rel, list): rel = [str(rel)]
        if 'stylesheet' in [r.lower() for r in rel]: link.decompose()
    return str(soup)

def shift_heading_levels(html: str, offset: int) -> str:
    if not offset: return html
    soup = BeautifulSoup(html, _HTML_PARSER)
    for tag in soup.find_all(re.compile(r'^h[1-6]$', re.IGNORECASE)):
        try: level = int(tag.name[1])
        except: continue
        new_level = max(1, min(6, level + offset))
        if new_level != level: tag.name = f"h{new_level}"
    return str(soup)

def _infer_manual_type_from_html(soup: BeautifulSoup) -> str:
    h1 = soup.find('h1')
    if h1 and re.match(r'^Section\s+', (h1.get_text() or "").strip(), re.IGNORECASE):
        return "section"
    return "chapter"

def extract_manual_fragment(html: str) -> tuple[str, dict]:
    soup = BeautifulSoup(html, _HTML_PARSER)
    grid = soup.find('div', class_='manual-grid')
    meta = {}
    if grid:
        manual = grid.find('div', class_='manual')
        meta = {
            'manual_type': grid.get('data-manual-type'),
            'toc_depth': grid.get('data-toc-depth'),
            'numbering_mode': grid.get('data-numbering-mode'),
            'heading_offset': grid.get('data-heading-offset'),
            'theme_id': grid.get('data-theme')
        }
    else:
        manual = soup.find('div', class_='manual') or soup.find('body') or soup
    
    if not meta.get('manual_type'):
        meta['manual_type'] = _infer_manual_type_from_html(BeautifulSoup(str(manual), _HTML_PARSER))
    return str(manual), meta

def add_heading_ids(soup_or_html, overwrite_existing: bool = True, stable_map: dict | None = None):
    """
    Add unique id attributes to all headings (h1-h6) for anchor linking.
    Hybrid Rule (default overwrite_existing=True):
        1. If overwrite_existing is False AND the heading already has an id, keep it.
        2. Otherwise, if stable_map has a matching signature, use that id.
        3. Otherwise, generate a slug from the heading text.
    """
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _add_heading_ids_impl(soup, overwrite_existing, stable_map)
        return str(soup)
    _add_heading_ids_impl(soup_or_html, overwrite_existing, stable_map)

def _add_heading_ids_impl(soup: BeautifulSoup, overwrite_existing: bool = True, stable_map: dict | None = None) -> None:
    used_ids = set()
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = heading.get_text().strip()
        existing_id = (heading.get('id') or '').strip()

        # Branch 1: keep existing id (only when caller explicitly opts out of overwrite)
        if existing_id and not overwrite_existing:
            slug = existing_id
            if slug in used_ids:
                base_slug = slug
                counter = 1
                while slug in used_ids:
                    slug = f"{base_slug}-{counter}"
                    counter += 1
            heading['id'] = slug
            used_ids.add(slug)
            continue

        # Branch 2: stable map lookup by content signature
        if stable_map:
            sig = normalize_heading_signature(text)
            if sig and sig in stable_map:
                slug = stable_map[sig]
                if slug in used_ids:
                    base_slug = slug
                    counter = 1
                    while slug in used_ids:
                        slug = f"{base_slug}-{counter}"
                        counter += 1
                heading['id'] = slug
                used_ids.add(slug)
                continue

        # Branch 3: generate slug from heading text
        slug = re.sub(r'^(?:Chapter|Section)\s+[\dIVXLCDM]+(?:\.[A-Za-z\d]+)*\s*(?:--|[-:.])\s*', '', text, flags=re.IGNORECASE)
        slug = re.sub(r'^([A-Z0-9]+(?:\.[A-Z0-9]+)+|[A-Z0-9]+\.)\s+', '', slug, flags=re.IGNORECASE)
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = slug.strip('-').lower()[:50]

        base_slug = slug or "heading"
        slug = base_slug
        counter = 1
        while slug in used_ids:
            slug = f"{base_slug}-{counter}"
            counter += 1
        heading['id'] = slug
        used_ids.add(slug)

def generate_server_side_toc(soup: BeautifulSoup, toc_depth: int) -> str:
    import html as _html
    headings = []
    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        try:
            level = int(h.name[1])
            if level <= toc_depth: headings.append((level, h.get('id', ''), h.get_text().strip()))
        except: continue
    out = ['<ul class="toc-list" aria-labelledby="toc-heading">']
    chapter_open = False
    for level, hid, text in headings:
        safe_text, safe_id = _html.escape(text), _html.escape(hid)
        if level == 1:
            if chapter_open: out.append('</ul></li>')
            out.append(f'<li class="toc-chapter toc-item toc-level-1"><a href="#{safe_id}">{safe_text}</a><ul class="toc-subsections toc-collapsed">')
            chapter_open = True
        else:
            out.append(f'<li class="toc-section toc-item toc-level-{level}"><a href="#{safe_id}">{safe_text}</a></li>')
    if chapter_open: out.append('</ul></li>')
    out.append('</ul>')
    return ''.join(out)

def strip_pandoc_styles(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        for tag in soup.find_all(['style', 'header']): tag.decompose()
        return str(soup)
    for tag in soup_or_html.find_all(['style', 'header']): tag.decompose()

def strip_images_and_figures(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        for tag in soup.find_all(['img', 'figure', 'figcaption']): tag.decompose()
        return str(soup)
    for tag in soup_or_html.find_all(['img', 'figure', 'figcaption']): tag.decompose()

def format_manual_tables(soup_or_html, align_mode: str = "auto", col1_align: str | None = None, coln_align: str | None = None, header_align: str | None = None):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _format_manual_tables_impl(soup, align_mode, col1_align, coln_align, header_align)
        return str(soup)
    _format_manual_tables_impl(soup_or_html, align_mode, col1_align, coln_align, header_align)

def _format_manual_tables_impl(soup: BeautifulSoup, align_mode: str = "auto", col1_align: str | None = None, coln_align: str | None = None, header_align: str | None = None) -> None:
    mode = (align_mode or "auto").strip().lower()
    def norm_align(v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("", "auto", "none"):
            return None
        return s if s in ("left", "center", "right") else None
    c1 = norm_align(col1_align)
    cn = norm_align(coln_align)
    ha = norm_align(header_align)
    def is_num(t):
        if not t: return True
        t = t.strip(); normalized = re.sub(r'[\s$,%\u00a0\u2013\u2014]', '', t)
        return bool(re.match(r'^-?[\d,.]+$', normalized))
    def apply_align(tag, a):
        s = tag.get('style', ''); s = re.sub(r'(?i)text-align\s*:\s*[^;]+\s*(!important)?\s*;?', '', s).strip()
        tag['style'] = f"{s}{';' if s and not s.endswith(';') else ''} text-align: {a} !important;"
    for table in soup.find_all('table'):
        # WCAG 1.3.1: add scope to th elements for screen reader table navigation
        for th in table.find_all('th'):
            if not th.get('scope'):
                # th in thead or first row → column header; th as first cell in body row → row header
                if th.parent and (th.parent.parent and th.parent.parent.name == 'thead'):
                    th['scope'] = 'col'
                elif th.parent and th == th.parent.find('th') and th.parent.find('td'):
                    th['scope'] = 'row'
                else:
                    th['scope'] = 'col'
        for row in table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            for idx, td in enumerate(cells):
                num = is_num(td.get_text().strip())
                if td.name == "th" and ha:
                    a = ha
                elif c1 and cn:
                    a = c1 if idx == 0 else cn
                elif mode == "left_all": a = "left"
                elif mode == "center_all": a = "center"
                elif mode == "right_all": a = "right"
                elif mode == "right_numeric": a = "right" if num else "left"
                elif mode == "auto_skip_first": a = "left" if idx == 0 else ("center" if num else "left")
                else: a = "center" if num else "left"
                td['class'] = [c for c in (td.get('class', []) if isinstance(td.get('class', []), list) else td.get('class', '').split()) if not c.startswith("manual-align-")] + [f"manual-align-{a}"]
                apply_align(td, a)
                for child in td.find_all(['p', 'span']): apply_align(child, a)

def infer_heading_levels_from_prefix(soup_or_html, style_map: dict | None = None):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _infer_heading_levels_from_prefix_impl(soup, style_map)
        return str(soup)
    _infer_heading_levels_from_prefix_impl(soup_or_html, style_map)

def _infer_heading_levels_from_prefix_impl(soup: BeautifulSoup, style_map: dict | None = None) -> None:
    for heading in soup.find_all(re.compile(r'^h[1-6]$')):
        parts = _extract_style_map_tokens(heading.get_text()) if style_map else _extract_heading_prefix_tokens(heading.get_text())
        if not parts: continue
        try: cur = int(heading.name[1])
        except: continue
        target = None
        if style_map:
            type = _classify_token_for_style_map(parts[-1], len(parts), style_map, prefer_roman_single=bool(re.match(r'^\s*(Chapter|Section)\b', heading.get_text(), re.IGNORECASE)))
            if type in style_map: target = style_map[type]
        if not target:
            eff = parts[1:] if cur > 1 and len(parts) > 1 and _is_numeric_or_roman(parts[0]) else parts[:]
            if len(eff) > 0: target = min(6, max(cur, 1 + len(eff)))
        if target and target != cur: heading.name = f"h{target}"

def strip_toc_sections_dom(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _strip_toc_sections_dom_impl(soup)
        return str(soup)
    _strip_toc_sections_dom_impl(soup_or_html)

def _strip_toc_sections_dom_impl(soup: BeautifulSoup) -> None:
    container = soup.find('div', class_='manual') or soup
    for heading in soup.find_all(re.compile(r'^h[1-6]$')):
        if re.search(r'Table of Contents', heading.get_text(), re.IGNORECASE):
            nxt = heading.find_next_sibling()
            heading.decompose()
            while nxt and nxt.name not in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                rem = nxt; nxt = nxt.find_next_sibling(); rem.decompose()
    h1s = list(container.find_all('h1'))
    for h1 in h1s:
        txt = h1.get_text().strip()
        if (re.match(r'^Chapter\s+|^Section\s+', txt, re.IGNORECASE)) and not ('\t' in txt or (re.search(r'\s+\d+\s*$', txt) and len(txt) < 100)):
            nxt = h1.find_next_sibling(); checked = 0; has_content = False
            while nxt and checked < 5:
                if nxt.name == 'h1': break
                if nxt.name in ['h2', 'h3', 'h4', 'h5', 'h6', 'table'] or (nxt.name == 'p' and len(nxt.get_text(strip=True)) > 20):
                    has_content = True; break
                nxt = nxt.find_next_sibling(); checked += 1
            if has_content:
                prv = h1.find_previous_sibling()
                while prv: rem = prv; prv = prv.find_previous_sibling(); rem.decompose()
                break

def strip_heading_numbers_dom(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        res = _strip_heading_numbers_dom_impl(soup)
        return str(soup), res
    return _strip_heading_numbers_dom_impl(soup_or_html)

def _strip_heading_numbers_dom_impl(soup: BeautifulSoup) -> dict:
    old_map = {}
    for h in soup.find_all(re.compile(r'^h[1-6]$')):
        hid = h.get('id', '') or f"heading-{uuid.uuid4().hex[:8]}"
        h['id'] = hid
        norm = _normalized(h.get_text('', strip=False))
        m = _HEADING_PREFIX_RE.match(norm)
        if m:
            old_map[hid] = m.group(0).strip(); needed = len(m.group(0))
            def nodes(n):
                for c in list(n.children):
                    if isinstance(c, NavigableString): yield c
                    elif isinstance(c, Tag): yield from nodes(c)
            for tn in nodes(h):
                if needed <= 0: break
                orig = str(tn); consumed = 0; cut = 0
                for idx, ch in enumerate(orig):
                    if consumed >= needed: break
                    if _norm_char(ch): consumed += 1
                    cut = idx + 1
                rem = orig[cut:]
                if rem: tn.replace_with(NavigableString(rem))
                else: tn.extract()
                needed -= consumed
            for c in list(h.children):
                if isinstance(c, Tag) and not c.get_text(strip=True): c.decompose()
                else: break
    return old_map

def apply_heading_edits(soup_or_html, edits: dict | None):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _apply_heading_edits_impl(soup, edits)
        return str(soup)
    _apply_heading_edits_impl(soup_or_html, edits)

def _apply_heading_edits_impl(soup: BeautifulSoup, edits: dict | None) -> None:
    if not edits: return
    for h in soup.find_all(re.compile(r'^h[1-6]$')):
        hid = (h.get('id') or '').strip()
        if hid in edits:
            e = edits[hid]
            if 1 <= e.get("level", 0) <= 6: h.name = f"h{e['level']}"
            if e.get("text", "").strip(): h.clear(); h.append(e['text'].strip())

def apply_list_classes_and_styles(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _apply_list_classes_and_styles_impl(soup)
        return str(soup)
    _apply_list_classes_and_styles_impl(soup_or_html)

def _apply_list_classes_and_styles_impl(soup: BeautifulSoup) -> None:
    rank = _infer_list_rank_order(soup); ordered = sorted(rank.keys(), key=lambda k: rank[k]); last = {}
    for ol in soup.find_all('ol'):
        depth = len(ol.find_parents('ol'))
        style = _list_style_from_class_list(ol.get('class', []) if isinstance(ol.get('class', []), list) else (ol.get('class', '') or '').split()) or _list_style_from_type_attr(ol.get('type', '')) or _list_style_from_inline(ol.get('style', ''))
        info = _list_info_from_style(style) or last.get(depth)
        if not info:
            parent = ol.find_parent('ol')
            if parent:
                p_style = _list_style_from_class_list(parent.get('class', []) if isinstance(parent.get('class', []), list) else (parent.get('class', '') or '').split()) or _list_style_from_type_attr(parent.get('type', ''))
                p_info = _list_info_from_style(p_style)
                if p_info:
                    idx = ordered.index(p_info[0]) if p_info[0] in ordered else 0
                    info = (ordered[(idx + 1) % len(ordered)], p_info[1] or 'lower')
        if info:
            _apply_list_class(ol, ol.get('type', '') or _type_from_list_info(*info))
            _apply_list_style(ol, _style_from_list_info(*info)); last[depth] = info

def normalize_typed_lists(soup_or_html):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _normalize_typed_lists_impl(soup)
        return str(soup)
    _normalize_typed_lists_impl(soup_or_html)

def _normalize_typed_lists_impl(soup: BeautifulSoup) -> None:
    container = soup.find('div', class_='manual') or soup
    children = list(container.children); i = 0; new_nodes = []
    def run(s_idx):
        m0 = _roman.match(children[s_idx].get_text()) or _alpha.match(children[s_idx].get_text()) or _decimal.match(children[s_idx].get_text())
        bt = _list_type_for(m0); ol = soup.new_tag('ol'); ol['type'] = bt[1]; _apply_list_class(ol, bt[1])
        idx = s_idx; fv = None
        while idx < len(children):
            p = children[idx]
            if not (isinstance(p, Tag) and p.name == 'p'): break
            m = _roman.match(p.get_text()) or _alpha.match(p.get_text()) or _decimal.match(p.get_text())
            if not m or _list_type_for(m) != bt: break
            v = _list_value(m); fv = v if fv is None else fv; li = soup.new_tag('li')
            for chunk in _after_prefix(p, len(m.group(0)), soup): li.append(chunk)
            ol.append(li); idx += 1
        if fv and fv > 1: ol['start'] = str(fv)
        return ol, idx
    while i < len(children):
        n = children[i]
        if isinstance(n, Tag) and n.name == 'p' and (_roman.match(n.get_text()) or _alpha.match(n.get_text()) or _decimal.match(n.get_text())):
            ol, next_i = run(i); new_nodes.append(ol); i = next_i
        else: new_nodes.append(n); i += 1
    container.clear()
    for n in new_nodes: container.append(n)

def apply_reference_edits(soup_or_html, edits: dict, references: list, validations: dict = None, link_targets: dict = None, auto_crosswalk: dict = None, new_headings: dict = None, reference_ignored: dict = None, reference_external_urls: dict = None, skip_linked_text: bool = False, rebuild_links: bool = False):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _apply_reference_edits_impl(soup, edits, references, validations, link_targets, auto_crosswalk, new_headings, reference_ignored, reference_external_urls, skip_linked_text, rebuild_links)
        return str(soup)
    _apply_reference_edits_impl(soup_or_html, edits, references, validations, link_targets, auto_crosswalk, new_headings, reference_ignored, reference_external_urls, skip_linked_text, rebuild_links)

def _apply_reference_edits_impl(soup: BeautifulSoup, edits: dict, references: list, validations: dict = None, link_targets: dict = None, auto_crosswalk: dict = None, new_headings: dict = None, reference_ignored: dict = None, reference_external_urls: dict = None, skip_linked_text: bool = False, rebuild_links: bool = False) -> None:
    if not references or validations is None: return
    if rebuild_links:
        pat = re.compile(r'(?:Section|Chapter)\s+[\dIVXLCDM]+(?:\.[A-Za-z\d]+)+|(?<!\w)[\dIVXLCDM]+(?:\.[A-Za-z\d]+){2,}(?!\w)', re.IGNORECASE)
        for a in soup.find_all('a', href=True):
            if a.get('href', '').startswith('#') and pat.search(normalize_spaces(a.get_text() or '')): a.unwrap()
    ref_map = {}
    for r in references:
        para, old, start = r[0], r[2], r[3]; rid = generate_stable_ref_id(para, start, old)
        if reference_ignored and reference_ignored.get(rid): continue
        if not (validations.get(rid) or (edits and edits.get(rid)) or (link_targets and link_targets.get(rid)) or (reference_external_urls and reference_external_urls.get(rid))): continue
        aid = ''; target = link_targets.get(rid, '').strip() if link_targets else ''
        if target and new_headings:
            from core.manual_structure import find_heading_by_full
            _, d = find_heading_by_full(target, new_headings)
            if d: aid = d.get('id', '')
        disp = edits.get(rid, '').strip() if edits else ''
        if not disp and auto_crosswalk: disp = auto_crosswalk.get(old, '')
        if not disp: disp = old
        url = reference_external_urls.get(rid, '').strip() if reference_external_urls else ''
        ref_map.setdefault(para, []).append({'old': old, 'new': disp, 'anchor': aid, 'url': url, 'start': start})
    paragraphs = [p for p in (soup.find('div', class_='manual') or soup).find_all('p') if not p.find_parent('table')]
    for p_idx, ents in ref_map.items():
        if p_idx >= len(paragraphs): continue
        p = paragraphs[p_idx]
        for ent in sorted(ents, key=lambda x: x['start'], reverse=True):
            old_t, new_t, aid, url = ent['old'], ent['new'], ent['anchor'], ent['url']
            def rep(n, t, r, a, u):
                if isinstance(n, NavigableString):
                    if t in n:
                        idx = n.find(t); b, af = n[:idx], n[idx+len(t):]; nodes = [NavigableString(b)]
                        if u or a:
                            tag = soup.new_tag('a', href=u or f"#{a}")
                            if u: tag['target'] = "_blank"; tag['class'] = "external-link"
                            tag.string = r; nodes.append(tag)
                        else: nodes.append(NavigableString(r))
                        nodes.append(NavigableString(af)); return nodes, True
                    return [n], False
                if isinstance(n, Tag):
                    if n.name == 'a' and skip_linked_text: return [n], False
                    con = []
                    for c in list(n.children):
                        ns, ok = rep(c, t, r, a, u); con.extend(ns)
                        if ok: break
                    else: return [n], False
                    n.clear()
                    for c in con: n.append(c)
                    return [n], True
                return [n], False
            rep(p, old_t, new_t, aid, url)

def apply_css_counter_numbering(soup_or_html, manual_type: str = 'chapter', preserve: bool = False):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _apply_css_counter_numbering_impl(soup, manual_type, preserve)
        return str(soup)
    _apply_css_counter_numbering_impl(soup_or_html, manual_type, preserve)

def _apply_css_counter_numbering_impl(soup: BeautifulSoup, manual_type: str = 'chapter', preserve: bool = False) -> None:
    if preserve: return
    cnt = {'h1': 0, 'h2': 0, 'h3': 0, 'h4': 0, 'h5': 0, 'h6': 0}
    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        lvl = h.name; txt = h.get_text().strip()
        if re.match(r'^(Chapter|Section)\s+[\d.]+', txt, re.IGNORECASE) or re.match(r'^\d+(?:\.\d+)*\s+', txt): continue
        cnt[lvl] += 1
        lvls = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
        for d in lvls[lvls.index(lvl) + 1:]: cnt[d] = 0
        pref = "Chapter" if manual_type == 'chapter' else "Section"
        if lvl == 'h1': num = str(cnt['h1']); new = f"{pref} {num} - {txt}"
        else:
            if lvl == 'h2': num = f"{cnt['h1']}.{cnt['h2']}"
            elif lvl == 'h3': num = f"{cnt['h1']}.{cnt['h2']}.{cnt['h3']}"
            elif lvl == 'h4': num = f"{cnt['h1']}.{cnt['h2']}.{cnt['h3']}.{cnt['h4']}"
            elif lvl == 'h5': num = f"{cnt['h1']}.{cnt['h2']}.{cnt['h3']}.{cnt['h4']}.{cnt['h5']}"
            else: num = f"{cnt['h1']}.{cnt['h2']}.{cnt['h3']}.{cnt['h4']}.{cnt['h5']}.{cnt['h6']}"
            new = f"{num} {txt}"
        h.string = new

def process_html_pipeline(html_content: str, session_id: str, config: dict) -> tuple[str, str]:
    soup = BeautifulSoup(html_content, _HTML_PARSER)
    strip_pandoc_styles(soup)
    strip_images_and_figures(soup)
    body = soup.find('body')
    if body:
        soup = BeautifulSoup(body.decode_contents(), _HTML_PARSER)
    _strip_toc_sections_dom_impl(soup)
    if config.get('mapping_mode') == "map_new" and config.get('infer_heading_depth'):
        _infer_heading_levels_from_prefix_impl(soup, config.get('infer_style_map'))
    if not config.get('preserve_numbers'): _strip_heading_numbers_dom_impl(soup)
    _add_heading_ids_impl(soup, stable_map=config.get('stable_heading_map'))
    if config.get('heading_edits'): _apply_heading_edits_impl(soup, config.get('heading_edits'))
    _normalize_typed_lists_impl(soup)
    _apply_list_classes_and_styles_impl(soup)
    _format_manual_tables_impl(soup, config.get('table_align_mode', 'auto'), config.get('table_col1_align'), config.get('table_coln_align'), config.get('table_header_align'))
    if config.get('references'):
        _apply_reference_edits_impl(soup, config.get('reference_edits', {}), config.get('references', []), config.get('reference_validations', {}), config.get('reference_link_targets', {}), auto_crosswalk=config.get('auto_crosswalk', {}), new_headings=config.get('new_headings', {}), reference_ignored=config.get('reference_ignored', {}), reference_external_urls=config.get('reference_external_urls', {}), skip_linked_text=config.get('skip_linked_text', False), rebuild_links=config.get('rebuild_links', False))
    return str(soup), generate_server_side_toc(soup, config.get('toc_depth', 2))

def has_tables_in_html(html_path) -> bool:
    """Return True if the HTML file at html_path contains at least one <table> element."""
    try:
        html = Path(html_path).read_text(encoding='utf-8', errors='ignore')
        return bool(BeautifulSoup(html, _HTML_PARSER).find('table'))
    except Exception:
        return False

def strip_inline_formatting(html: str) -> str:
    """Remove inline formatting tags (b, i, em, strong, span, u, s, sub, sup) while preserving text."""
    soup = BeautifulSoup(html, _HTML_PARSER)
    for tag in soup.find_all(['b', 'i', 'em', 'strong', 'span', 'u', 's', 'sub', 'sup']):
        tag.unwrap()
    return str(soup)

def sanitize_docx_ids_for_export(html: str) -> str:
    """Normalize heading id attributes to be valid DOCX bookmark names for Pandoc HTML→DOCX export."""
    soup = BeautifulSoup(html, _HTML_PARSER)
    for h in soup.find_all(re.compile(r'^h[1-6]$')):
        hid = h.get('id', '')
        if hid:
            sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', hid)[:40]
            if sanitized and sanitized[0].isdigit():
                sanitized = 'h_' + sanitized
            h['id'] = sanitized
    return str(soup)

def parse_heading_id_map_json(raw_text: str) -> dict:
    """
    Parse a heading-map JSON file. Accepts three input shapes:
      1. Structured: {"version": 1, "entries": [{"signature": ..., "id": ...}, ...]}
      2. Bare list:  [{"signature": ..., "id": ...}, ...]
      3. Flat dict:  {"<signature>": "<id>", ...}
    Returns a dict {normalized_signature: heading_id}.
    """
    if not raw_text:
        return {}
    try:
        data = json.loads(raw_text)
    except Exception as exc:
        print(f"DEBUG: Failed to parse heading map JSON: {exc}")
        return {}
    entries = []
    if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
        entries = data["entries"]
    elif isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        for key, value in data.items():
            entries.append({"signature": key, "id": value})
    heading_map = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        signature = normalize_heading_signature(entry.get("signature") or "")
        heading_id = (entry.get("id") or "").strip()
        if signature and heading_id:
            heading_map[signature] = heading_id
    return heading_map


def build_manual_grid_block(body_html: str, toc_depth: int, manual_type: str, numbering_mode: str, heading_offset: int = 0, theme_id: str = "manual") -> str:
    """Assemble the full manual grid HTML block with accessible TOC and search."""
    body_html = format_manual_tables(body_html)

    offset_attr = f' data-heading-offset="{heading_offset}"' if heading_offset else ""
    theme_attr = f' data-theme="{sanitize_theme_id(theme_id, "manual")}"'
    return (
        '<!-- ACCESSIBILITY: Skip navigation link for keyboard users (WCAG 2.4.1) -->\n'
        '<a href="#main-content" class="skip-to-main">Skip to main content</a>\n'
        f'<div class="manual-grid" data-toc-depth="{toc_depth}" data-manual-type="{manual_type}" data-numbering-mode="{numbering_mode}"{offset_attr}{theme_attr}>\n'
            '  <nav class="manual-toc" role="navigation" aria-label="Table of Contents">\n'
            '    <h2 id="toc-heading">Table of Contents</h2>\n'
            '    <div class="manual-search">\n'
            '      <input type="text" class="manual-search-input" placeholder="Search headings and content..." aria-label="Search table of contents" aria-describedby="search-help" role="searchbox">\n'
            '      <button type="button" class="manual-search-clear" aria-label="Clear search">X</button>\n'
            '    </div>\n'
            '    <span id="search-help" class="sr-only">Type to filter headings and content</span>\n'
            '    <ul aria-labelledby="toc-heading" aria-live="polite"></ul>\n'
            '  </nav>\n'
            f'  <main class="manual" id="main-content" role="main" tabindex="-1">\n'
            f'    {body_html}\n'
            '  </main>\n'
            '</div>\n'
        )
