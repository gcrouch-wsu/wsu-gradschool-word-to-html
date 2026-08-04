import os
import re
import json
import logging
import uuid
import hashlib
from pathlib import Path
from bs4 import BeautifulSoup, Tag, NavigableString
from .permalinks import normalize_heading_signature, manual_prefix, normalize_manual_type
from utils.helpers import sanitize_theme_id, roman_to_int
from config import SessionDir

logger = logging.getLogger(__name__)

# Detect lxml once at import time; fall back to built-in parser if unavailable.
try:
    import lxml as _lxml_check  # noqa: F401
    _HTML_PARSER = 'lxml'
except ImportError:
    _HTML_PARSER = 'html.parser'

try:
    import bleach
    try:
        from bleach.css_sanitizer import CSSSanitizer
        # Only the inline CSS the pipeline itself emits: list markers on <ol>
        # and per-column alignment on table cells. Everything else is stripped.
        _CSS_SANITIZER = CSSSanitizer(
            allowed_css_properties=["list-style-type", "text-align"]
        )
    except ImportError:  # tinycss2 missing — bleach drops style values entirely
        _CSS_SANITIZER = None
except ImportError:  # pragma: no cover
    bleach = None  # type: ignore
    _CSS_SANITIZER = None

from utils.url_policy import is_safe_href, sanitize_external_href

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


def find_manual_container(soup: BeautifulSoup) -> Tag | None:
    """Return div.manual, main.manual (exporter grid), or body."""
    if soup is None:
        return None
    for finder in (
        lambda s: s.find('div', class_='manual'),
        lambda s: s.find('main', class_='manual'),
    ):
        el = finder(soup)
        if el is not None:
            return el
    return soup.find('body')


# Allowlist for policy-manual HTML (import + post-pipeline hardening)
_BLEACH_TAGS = frozenset({
    'a', 'abbr', 'article', 'aside', 'b', 'blockquote', 'br', 'caption', 'cite', 'code', 'col', 'colgroup',
    'dd', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'header', 'hr', 'i', 'img', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'small', 'span', 'strong',
    'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul',
})
_BLEACH_ATTRS = {
    '*': [
        'class', 'id', 'style', 'role', 'aria-label', 'aria-labelledby', 'aria-describedby',
        'aria-live', 'tabindex', 'colspan', 'rowspan', 'scope', 'headers', 'lang', 'title',
    ],
    'a': ['href', 'name', 'target', 'rel', 'class', 'id', 'title'],
    'img': ['src', 'alt', 'width', 'height', 'loading', 'class', 'decoding', 'title'],
    'th': ['abbr', 'scope', 'colspan', 'rowspan', 'headers', 'class', 'id'],
    'td': ['colspan', 'rowspan', 'headers', 'class', 'id'],
    # The exporter stamps the manual's own settings onto .manual-grid and reads
    # them back on import (extract_manual_fragment). They must survive
    # sanitization: bleach dropped every data-* here, so re-importing a
    # downloaded fragment silently lost its numbering mode, TOC depth, theme,
    # and — worst — its data-heading-offset, so the +1 heading shift baked into
    # a fragment was never undone and chapters stayed demoted to h2.
    # Values are re-validated on read (build_manual_grid_block normalizes the
    # enums; import_html coerces the integers), so allowing the names is safe.
    'div': [
        'class', 'id', 'style', 'role', 'aria-label', 'aria-labelledby',
        'data-toc-depth', 'data-manual-type', 'data-numbering-mode',
        'data-heading-offset', 'data-theme',
    ],
    'ol': ['type', 'start', 'class', 'id', 'data-list-style'],
    'ul': ['class', 'id'],
    'li': ['class', 'id', 'value'],
    'input': ['type', 'class', 'placeholder', 'aria-label', 'aria-describedby', 'role', 'disabled', 'readonly'],
    'button': ['type', 'class', 'aria-label', 'disabled'],
}


def sanitize_manual_html_fragment(html: str) -> str:
    """
    Allowlisted HTML cleanup: strips scripts, event-handler attributes, and unsafe URL schemes.
    Used after import and on final body fragments before preview/export where applicable.
    """
    if not html or not html.strip():
        return html or ''
    if bleach is None:
        soup = BeautifulSoup(html, _HTML_PARSER)
        for tag in soup.find_all(['script', 'style']):
            tag.decompose()
        for link in soup.find_all('link'):
            rel = link.get('rel') or []
            if not isinstance(rel, list):
                rel = [str(rel)]
            if 'stylesheet' in [r.lower() for r in rel]:
                link.decompose()
        return str(soup)
    return bleach.clean(
        html,
        tags=sorted(_BLEACH_TAGS),
        attributes=_BLEACH_ATTRS,
        protocols=['http', 'https', 'mailto'],
        strip=True,
        css_sanitizer=_CSS_SANITIZER,
    )


# comprehensive prefix matcher (on normalized text)
# IMPORTANT: Must require whitespace after the prefix so "I.A.3.Duties" is not
# consumed as "I.A.3.D"; the trailing separator class includes en/em dashes
# (–, —) so "Chapter 2 – Title" strips cleanly.
_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?i:(?:Chapter|Section))\s+[IVXLCDM\d]+(?:\.[A-Z\d]+)*(?:\s*[:.–—\-])?\s+|"
    r"(?:\d+|[IVXLCDM]{1,6}|[A-Z]{1,3}|[a-z]{1,3})(?:[.\s]+(?:\d+|[IVXLCDM]{1,6}|[A-Z]{1,3}|[a-z]{1,3})){1,5}\.?\s+(?:[:.–—\-]\s*)?|"
    r"(?i:[IVXLCDM]+)\.(?:[A-Z]{1,3}|[a-z]{1,3})(?:\.\d+){0,3}\.?\s+(?:[:.–—\-]\s*)?|"
    r"(?i:[IVXLCDM]+)(?:\.\d+){0,3}\.?\s+(?:[:.–—\-]\s*)?|"
    r"(?:[A-Z]{1,3}|[a-z]{1,3})\.\s+(?:[:.–—\-]\s*)?|"
    r"\d+(?:\.\d+){0,3}(?:[.)])?\s+(?:[:.–—\-]\s*)?"
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
    # Map each heading signature to the LIST of ids it carries in document
    # order. Storing a list (not a single id) keeps the map lossless when two
    # headings share normalized text — a flat {sig: id} dropped all but the
    # last, which made re-applying the map non-idempotent (ids drifting
    # overview -> overview-1 -> overview-1-1 on every reconversion).
    soup = BeautifulSoup(final_html, _HTML_PARSER)
    heading_map: dict[str, list[str]] = {}
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        hid = (heading.get('id') or '').strip()
        if not hid:
            continue
        text = heading.get_text().strip()
        sig = normalize_heading_signature(text)
        if sig and hid:
            heading_map.setdefault(sig, []).append(hid)
    session = SessionDir(session_id)
    session.stable_map_json.write_text(
        json.dumps(heading_map, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    logger.info("Saved stable heading map: %d entries", len(heading_map))

def strip_html_assets(html: str) -> str:
    """Remove head assets and apply allowlisted sanitization (event handlers, unsafe URLs)."""
    soup = BeautifulSoup(html, _HTML_PARSER)
    for tag in soup.find_all(['script', 'style']):
        tag.decompose()
    for link in soup.find_all('link'):
        rel = link.get('rel') or []
        if not isinstance(rel, list):
            rel = [str(rel)]
        if 'stylesheet' in [r.lower() for r in rel]:
            link.decompose()
    return sanitize_manual_html_fragment(str(soup))

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
        manual = grid.find('div', class_='manual') or grid.find('main', class_='manual')
        meta = {
            'manual_type': grid.get('data-manual-type'),
            'toc_depth': grid.get('data-toc-depth'),
            'numbering_mode': grid.get('data-numbering-mode'),
            'heading_offset': grid.get('data-heading-offset'),
            'theme_id': grid.get('data-theme')
        }
    else:
        manual = find_manual_container(soup) or soup

    if manual is None:
        return '', meta
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

def _heading_slug_from_text(text: str) -> str:
    """Branch-3 slug used when no stable-map id applies (shared with JS recovery)."""
    slug = re.sub(
        r'^(?:Chapter|Section)\s+[\dIVXLCDM]+(?:\.[A-Za-z\d]+)*\s*(?:--|[-:.])\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    slug = re.sub(r'^([A-Z0-9]+(?:\.[A-Z0-9]+)+|[A-Z0-9]+\.)\s+', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug.strip('-').lower()[:50]

def _add_heading_ids_impl(soup: BeautifulSoup, overwrite_existing: bool = True, stable_map: dict | None = None) -> dict[str, str]:
    """Assign heading ids. Returns {old_id: new_id} for ids that changed.

    Pandoc/Word often emit heading ids and body ``href="#…"`` pairs that use a
    different slug alphabet than this app. Callers should rewrite internal
    hrefs with the returned map so Word hyperlinks survive re-iding.
    """
    used_ids = set()
    sig_occurrence: dict[str, int] = {}  # how many headings of each signature seen so far
    id_remap: dict[str, str] = {}
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = heading.get_text().strip()
        existing_id = (heading.get('id') or '').strip()
        slug = ""

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
            if existing_id and existing_id != slug:
                id_remap[existing_id] = slug
            continue

        # Branch 2: stable map lookup by content signature. The map stores a
        # list of ids per signature (document order); consume the Nth id for
        # the Nth heading that shares a signature so duplicate-text headings
        # keep distinct, stable anchors instead of all claiming the first id.
        if stable_map:
            sig = normalize_heading_signature(text)
            mapped = stable_map.get(sig) if sig else None
            if isinstance(mapped, str):  # tolerate legacy flat {sig: id} maps
                mapped = [mapped]
            if mapped:
                occ = sig_occurrence.get(sig, 0)
                sig_occurrence[sig] = occ + 1
                slug = mapped[occ] if occ < len(mapped) else ""
                if slug:
                    if slug in used_ids:
                        base_slug = slug
                        counter = 1
                        while slug in used_ids:
                            slug = f"{base_slug}-{counter}"
                            counter += 1
                    heading['id'] = slug
                    used_ids.add(slug)
                    if existing_id and existing_id != slug:
                        id_remap[existing_id] = slug
                    continue
                # More occurrences than the map recorded: fall through to
                # generate a fresh slug rather than reusing an exhausted id.

        # Branch 3: generate slug from heading text
        base_slug = _heading_slug_from_text(text) or "heading"
        slug = base_slug
        counter = 1
        while slug in used_ids:
            slug = f"{base_slug}-{counter}"
            counter += 1
        heading['id'] = slug
        used_ids.add(slug)
        if existing_id and existing_id != slug:
            id_remap[existing_id] = slug
    return id_remap

def _rewrite_internal_hrefs(soup: BeautifulSoup, id_remap: dict[str, str]) -> int:
    """Rewrite ``href="#old"`` to ``href="#new"`` using an id remap. Returns count."""
    if not id_remap:
        return 0
    changed = 0
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        if not href.startswith('#') or len(href) < 2:
            continue
        old = href[1:]
        new = id_remap.get(old)
        if new and new != old:
            a['href'] = f'#{new}'
            changed += 1
    return changed

def _unwrap_dead_fragment_links(soup: BeautifulSoup) -> int:
    """Unwrap internal ``#`` links whose target id is missing (e.g. Word bookmarks)."""
    keep = {'main-content', 'toc-heading', 'search-help'}
    live_ids = {
        (h.get('id') or '').strip()
        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if (h.get('id') or '').strip()
    }
    live_ids.update(keep)
    # Also keep any non-heading element ids present in the fragment
    for tag in soup.find_all(id=True):
        live_ids.add(tag['id'].strip())
    unwrapped = 0
    for a in list(soup.find_all('a', href=True)):
        href = (a.get('href') or '').strip()
        if not href.startswith('#') or href == '#':
            continue
        target = href[1:]
        if target in live_ids:
            continue
        a.unwrap()
        unwrapped += 1
    return unwrapped

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

def format_manual_tables(
    soup_or_html,
    align_mode: str = "auto",
    col1_align: str | None = None,
    coln_align: str | None = None,
    header_align: str | None = None,
    *,
    col2_align: str | None = None,
    col3_align: str | None = None,
):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _format_manual_tables_impl(
            soup, align_mode, col1_align, col2_align, col3_align, coln_align, header_align
        )
        return str(soup)
    _format_manual_tables_impl(
        soup_or_html, align_mode, col1_align, col2_align, col3_align, coln_align, header_align
    )


def describe_tables(html_path, overrides: dict | None = None) -> list[dict]:
    """Summarize each table for the Table Review step.

    Returns the first two rows as text so the operator can see which row the
    conversion currently treats as the header and correct it when Word left a
    title row or an ordinary data row in ``<thead>``.
    """
    overrides = {str(k): str(v) for k, v in (overrides or {}).items()}
    try:
        path = Path(html_path)
        if not path.is_file():
            return []
        soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='ignore'), _HTML_PARSER)
    except (OSError, ValueError):
        return []

    def cells_of(row):
        if row is None:
            return []
        return [c.get_text(" ", strip=True)[:60] for c in row.find_all(['th', 'td'])]

    described = []
    for index, table in enumerate(soup.find_all('table')):
        thead = table.find('thead')
        head_row = thead.find('tr') if thead is not None else None
        body_rows = [
            tr for tr in table.find_all('tr')
            if head_row is None or tr is not head_row
        ]
        columns = _table_columns(table)
        caption = table.find('caption')
        described.append({
            "index": index,
            "mode": overrides.get(str(index), "auto"),
            "columns": columns,
            "row_count": len(table.find_all('tr')),
            "caption": caption.get_text(" ", strip=True) if caption else "",
            "head_cells": cells_of(head_row),
            "first_body_cells": cells_of(body_rows[0] if body_rows else None),
            "second_body_cells": cells_of(body_rows[1] if len(body_rows) > 1 else None),
            "looks_like_title_row": bool(
                head_row is not None and _row_is_full_width_title(head_row, columns)
            ),
            "has_header": head_row is not None,
        })
    return described


def max_columns_in_first_table(html_path) -> int:
    """Return max column count among rows of the first <table>, or 0 if none."""
    try:
        p = Path(html_path) if not isinstance(html_path, Path) else html_path
        if not p.is_file():
            return 0
        html = p.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, _HTML_PARSER)
        table = soup.find("table")
        if not table:
            return 0
        m = 0
        for tr in table.find_all("tr"):
            n = len(tr.find_all(["th", "td"]))
            if n > m:
                m = n
        return m
    except Exception:
        return 0


def _format_manual_tables_impl(
    soup: BeautifulSoup,
    align_mode: str = "auto",
    col1_align: str | None = None,
    col2_align: str | None = None,
    col3_align: str | None = None,
    coln_align: str | None = None,
    header_align: str | None = None,
) -> None:
    mode = (align_mode or "auto").strip().lower()
    def norm_align(v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("", "auto", "none"):
            return None
        return s if s in ("left", "center", "right") else None
    c1 = norm_align(col1_align)
    c2 = norm_align(col2_align)
    c3 = norm_align(col3_align)
    cn = norm_align(coln_align)
    ha = norm_align(header_align)

    def auto_align(idx: int, num: bool) -> str:
        if mode == "left_all":
            return "left"
        if mode == "center_all":
            return "center"
        if mode == "right_all":
            return "right"
        if mode == "right_numeric":
            return "right" if num else "left"
        if mode == "auto_skip_first":
            return "left" if idx == 0 else ("center" if num else "left")
        return "center" if num else "left"

    def pick_col_align(idx: int, num: bool) -> str:
        if idx == 0 and c1 is not None:
            return c1
        if idx == 1 and c2 is not None:
            return c2
        if idx == 2 and c3 is not None:
            return c3
        if idx >= 3 and cn is not None:
            return cn
        return auto_align(idx, num)

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
            in_thead = row.parent and row.parent.name == 'thead'
            for idx, td in enumerate(cells):
                num = is_num(td.get_text().strip())
                if in_thead and td.name == "th" and ha:
                    a = ha
                else:
                    a = pick_col_align(idx, num)
                td['class'] = [c for c in (td.get('class', []) if isinstance(td.get('class', []), list) else td.get('class', '').split()) if not c.startswith("manual-align-")] + [f"manual-align-{a}"]
                apply_align(td, a)
                for child in td.find_all(['p', 'span']): apply_align(child, a)

# Per-table header handling. "auto" applies the title-row repair below; the
# others are operator overrides set in the Table Review step.
TABLE_HEADER_MODES = ("auto", "first_row", "title_row", "none")


def _table_columns(table: Tag) -> int:
    widest = 0
    for tr in table.find_all('tr'):
        n = sum(
            max(1, int(c.get('colspan') or 1)) if str(c.get('colspan') or 1).isdigit() else 1
            for c in tr.find_all(['th', 'td'])
        )
        widest = max(widest, n)
    return widest


def _row_is_full_width_title(row: Tag, columns: int) -> bool:
    """True when a row is really a table title: one cell spanning every column."""
    cells = row.find_all(['th', 'td'])
    if len(cells) != 1 or columns < 2:
        return False
    raw_span = str(cells[0].get('colspan') or 1)
    span = int(raw_span) if raw_span.isdigit() else 1
    return span >= columns and bool(cells[0].get_text(strip=True))


def _promote_row_to_header(row: Tag) -> None:
    for cell in row.find_all(['th', 'td']):
        cell.name = 'th'
        cell['scope'] = 'col'


def _demote_row_to_body(row: Tag) -> None:
    for cell in row.find_all(['th', 'td']):
        cell.name = 'td'
        cell.attrs.pop('scope', None)


def normalize_table_headers(soup_or_html, overrides: dict | None = None):
    """Give every table a defensible header structure.

    Word tables arrive with whatever row Pandoc happened to put in ``<thead>``,
    and the alignment pass then stamped ``scope="col"`` on it without asking
    whether it was a header at all. Two real shapes came out wrong:

    * A merged title row ("Advance Notice Table") became the ``<thead>`` while
      the actual column headers sat in the body as plain ``<td>`` — so the
      table had no programmatic headers (WCAG 1.3.1) and the title took the
      header styling.
    * An ordinary data row was promoted to ``<thead>``, so screen readers
      announced that row's text as the header of every column.

    The first is repaired automatically (a full-width single cell is a caption,
    not a header). The second cannot be detected reliably, so ``overrides``
    carries the operator's choice from the Table Review step, keyed by the
    table's position in the document: one of ``TABLE_HEADER_MODES``.
    """
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _normalize_table_headers_impl(soup, overrides)
        return str(soup)
    _normalize_table_headers_impl(soup_or_html, overrides)


def _normalize_table_headers_impl(soup: BeautifulSoup, overrides: dict | None = None) -> None:
    overrides = {str(k): str(v) for k, v in (overrides or {}).items()}
    for index, table in enumerate(soup.find_all('table')):
        mode = overrides.get(str(index), 'auto')
        if mode not in TABLE_HEADER_MODES:
            mode = 'auto'
        columns = _table_columns(table)
        thead = table.find('thead')
        tbody = table.find('tbody')

        if mode == 'none':
            if thead is not None:
                for row in list(thead.find_all('tr')):
                    _demote_row_to_body(row)
                    if tbody is not None:
                        tbody.insert(0, row.extract())
                if not thead.find('tr'):
                    thead.decompose()
            continue

        head_row = thead.find('tr') if thead is not None else None

        # Title row -> <caption>, and the row beneath it becomes the header.
        wants_title_fix = mode in ('auto', 'title_row')
        if wants_title_fix and head_row is not None and _row_is_full_width_title(head_row, columns):
            title_text = head_row.get_text(" ", strip=True)
            if not table.find('caption'):
                caption = soup.new_tag('caption')
                caption.string = title_text
                table.insert(0, caption)
            head_row.extract()
            next_row = tbody.find('tr') if tbody is not None else table.find('tr')
            if next_row is not None:
                _promote_row_to_header(next_row)
                thead.append(next_row.extract())
            elif not thead.find('tr'):
                thead.decompose()
            logger.info("Table %d: converted full-width title row to <caption>", index)
            continue

        # Explicit "the first body row is the header".
        if mode == 'first_row' and head_row is None:
            first = tbody.find('tr') if tbody is not None else table.find('tr')
            if first is not None:
                _promote_row_to_header(first)
                new_head = soup.new_tag('thead')
                new_head.append(first.extract())
                table.insert(0, new_head)


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
    container = find_manual_container(soup) or soup
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
    container = find_manual_container(soup) or soup
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

def _ordered_text_nodes(paragraph: Tag) -> list[NavigableString]:
    out: list[NavigableString] = []
    for n in paragraph.descendants:
        if not isinstance(n, NavigableString):
            continue
        if n.parent and getattr(n.parent, "name", None) in ("script", "style"):
            continue
        out.append(n)
    return out


def _replace_reference_first_occurrence(
    paragraph: Tag,
    old_t: str,
    new_t: str,
    anchor: str,
    url: str,
    soup: BeautifulSoup,
    skip_linked_text: bool,
) -> bool:
    """Legacy first-match replacement (fallback)."""
    # Guarded so this last-resort path cannot do what the primary path now
    # refuses to: match a short label inside a longer one ("Section II.F"
    # inside "Section II.F.6"), which linked the wrong target and left the
    # remaining ".6" stranded outside the anchor.
    guard = _guarded_ref_regex(re.escape(old_t).replace(r'\ ', r'\s+'))

    def rep(n, t, r, a, u):
        if isinstance(n, NavigableString):
            m = guard.search(str(n))
            if m:
                idx = m.start()
                b, af = n[:idx], n[m.end() :]
                nodes = [NavigableString(b)]
                safe_u = sanitize_external_href(u) if u else ""
                if safe_u or a:
                    tag = soup.new_tag("a", href=safe_u or f"#{a}")
                    if safe_u:
                        tag["target"] = "_blank"
                        tag["rel"] = "noopener noreferrer"
                        tag["class"] = "external-link"
                    tag.string = r
                    nodes.append(tag)
                else:
                    nodes.append(NavigableString(r))
                nodes.append(NavigableString(af))
                return nodes, True
            return [n], False
        if isinstance(n, Tag):
            if n.name == "a" and skip_linked_text:
                return [n], False
            con = []
            for c in list(n.children):
                ns, ok = rep(c, t, r, a, u)
                con.extend(ns)
                if ok:
                    break
            else:
                return [n], False
            n.clear()
            for c in con:
                n.append(c)
            return [n], True
        return [n], False

    rep(paragraph, old_t, new_t, anchor, url)
    return True


def _replace_reference_at_offset(
    paragraph: Tag,
    old_t: str,
    new_t: str,
    anchor: str,
    url: str,
    soup: BeautifulSoup,
    start_offset: int,
    skip_linked_text: bool,
) -> bool:
    """Replace old_t in paragraph at character offset (matches DOCX/HTML ref extraction)."""
    flat = paragraph.get_text(separator="", strip=False)
    # The slice must be the whole label, not the head of a longer one: at this
    # offset "Section II.F" also slices cleanly out of "Section II.F.6".
    end_offset = start_offset + len(old_t)
    offset_is_whole_label = (
        start_offset >= 0
        and end_offset <= len(flat)
        and flat[start_offset:end_offset] == old_t
        and not re.match(r'\.?\w', flat[end_offset:end_offset + 2])
        and not re.search(r'[\w.]$', flat[:start_offset])
    )
    if not offset_is_whole_label:
        return _replace_reference_first_occurrence(
            paragraph, old_t, new_t, anchor, url, soup, skip_linked_text
        )
    cum = 0
    for node in _ordered_text_nodes(paragraph):
        seg = str(node)
        L = len(seg)
        if cum + L <= start_offset:
            cum += L
            continue
        local = start_offset - cum
        if seg[local : local + len(old_t)] != old_t:
            return _replace_reference_first_occurrence(
                paragraph, old_t, new_t, anchor, url, soup, skip_linked_text
            )
        before, after = seg[:local], seg[local + len(old_t) :]
        safe_u = sanitize_external_href(url) if url else ""
        new_fragments: list = [NavigableString(before)]
        if safe_u:
            tag = soup.new_tag(
                "a",
                href=safe_u,
                target="_blank",
                rel="noopener noreferrer",
                **{"class": "external-link"},
            )
            tag.string = new_t
            new_fragments.append(tag)
        elif anchor:
            tag = soup.new_tag("a", href=f"#{anchor}")
            tag.string = new_t
            new_fragments.append(tag)
        else:
            new_fragments.append(NavigableString(new_t))
        new_fragments.append(NavigableString(after))
        first, *rest = new_fragments
        node.replace_with(first)
        ref = first
        for piece in rest:
            ref.insert_after(piece)
            ref = piece
        return True
    return _replace_reference_first_occurrence(
        paragraph, old_t, new_t, anchor, url, soup, skip_linked_text
    )


def apply_reference_edits(soup_or_html, edits: dict, references: list, validations: dict = None, link_targets: dict = None, auto_crosswalk: dict = None, new_headings: dict = None, reference_ignored: dict = None, reference_external_urls: dict = None, skip_linked_text: bool = False, rebuild_links: bool = False):
    if isinstance(soup_or_html, str):
        soup = BeautifulSoup(soup_or_html, _HTML_PARSER)
        _apply_reference_edits_impl(soup, edits, references, validations, link_targets, auto_crosswalk, new_headings, reference_ignored, reference_external_urls, skip_linked_text, rebuild_links)
        return str(soup)
    _apply_reference_edits_impl(soup_or_html, edits, references, validations, link_targets, auto_crosswalk, new_headings, reference_ignored, reference_external_urls, skip_linked_text, rebuild_links)

def _strip_heading_label_prefix(value: str) -> str:
    """Strip Chapter/Section/number labels so '1.1 - Overview' → 'Overview'."""
    text = (value or "").strip()
    text = re.sub(r'^(?:Chapter|Section)\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(
        r'^[\dIVXLCDM]+(?:\.[A-Za-z\d]+)*\s*(?:[-:.\u2013\u2014]\s*)?',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()

def _resolve_reference_anchor_id(
    old: str,
    disp: str,
    target: str,
    new_headings: dict | None,
    auto_crosswalk: dict | None,
) -> str:
    """Resolve an internal heading id from link target / crosswalk / display text.

    ``new_headings`` must carry *final* live ids (scraped after final
    ``add_heading_ids``), not early upload-scrape ids.
    """
    from core.manual_structure import find_heading_by_full

    if not new_headings:
        return ''

    def _id_from_heading(data: dict | None) -> str:
        if not data:
            return ''
        return (data.get('id') or '').strip()

    def _lookup(candidate: str) -> str:
        if not candidate:
            return ''
        if candidate in new_headings:
            aid = _id_from_heading(new_headings[candidate])
            if aid:
                return aid
        _, d = find_heading_by_full(candidate, new_headings)
        aid = _id_from_heading(d)
        if aid:
            return aid
        # Review targets often look like "1.1 - Overview" while final live
        # headings (after number strip) are just "Overview".
        stripped = _strip_heading_label_prefix(candidate)
        if stripped and stripped != candidate:
            _, d = find_heading_by_full(stripped, new_headings)
            aid = _id_from_heading(d)
            if aid:
                return aid
            for data in new_headings.values():
                title = (data.get('text') or data.get('title') or '').strip()
                if title and title.lower() == stripped.lower():
                    return _id_from_heading(data)
        return ''

    cross = ''
    if auto_crosswalk and old in auto_crosswalk:
        cross = (auto_crosswalk.get(old) or '').strip()

    for candidate in (target, cross, disp):
        aid = _lookup(candidate)
        if aid:
            return aid

    # Last resort: slug the semantic target and accept only if a live heading
    # already has that id (avoids inventing dead hrefs).
    for candidate in (target, cross, disp):
        if not candidate:
            continue
        for probe in (candidate, _strip_heading_label_prefix(candidate)):
            slug = _heading_slug_from_text(probe)
            if not slug:
                continue
            for data in new_headings.values():
                if (data.get('id') or '').strip() == slug:
                    return slug
    return ''

def _normalize_ws_for_ref_match(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\u00a0', ' ')).strip()

# A reference label must never match when it is merely the leading part of a
# longer label. "Section II.F" matched inside "Section II.F.6", linked the
# prefix to II.F, and left ".6" as orphaned plain text next to a wrong link.
#
# Leading guard: not preceded by a word character or a dot, so "II.F.6" cannot
# match inside "VIII.F.6".
# Trailing guard: not followed by an optional dot plus a word character, so
# "Section II.F" will not match "Section II.F.6" while a label that legitimately
# ends a sentence ("... in Section II.F.6.") still matches.
_REF_LEAD_GUARD = r'(?<![\w.])'
_REF_TAIL_GUARD = r'(?!\.?\w)'


def _guarded_ref_regex(body: str, flags=re.IGNORECASE) -> re.Pattern:
    return re.compile(_REF_LEAD_GUARD + body + _REF_TAIL_GUARD, flags)


def _ref_flexible_pattern(old_ref: str) -> re.Pattern:
    normalized = _normalize_ws_for_ref_match(old_ref)
    pattern = re.escape(normalized).replace(r'\ ', r'\s+')
    return _guarded_ref_regex(pattern)

def _absorb_split_reference_anchor(
    block: Tag, old_t: str, new_t: str, link_href: str, safe_u: str
) -> bool:
    """Repair a label split across an existing ``<a>`` boundary.

    Word cross-reference fields are often applied to only part of a label: the
    field covers "Section II.F" while the author typed the trailing ".6"
    immediately after it. Pandoc reproduces that split faithfully, so the
    anchor points at the shorter section and the remainder is stranded as plain
    text next to it — a link that reads right and goes somewhere wrong. Pull
    the remainder inside the anchor and retarget it.
    """
    if not link_href:
        return False
    want = _normalize_ws_for_ref_match(old_t)
    for a in block.find_all('a'):
        atext = _normalize_ws_for_ref_match(a.get_text())
        if not atext or atext == want or not want.startswith(atext):
            continue
        remainder = want[len(atext):]
        nxt = a.next_sibling
        if not remainder or not isinstance(nxt, NavigableString):
            continue
        tail = str(nxt)
        if not tail.startswith(remainder):
            continue
        # The label must end here, not continue into a longer one.
        if re.match(r'\.?\w', tail[len(remainder):len(remainder) + 2]):
            continue
        a['href'] = link_href
        if safe_u:
            a['target'] = '_blank'
            a['rel'] = 'noopener noreferrer'
            classes = a.get('class') or []
            if isinstance(classes, str):
                classes = [classes]
            if 'external-link' not in classes:
                a['class'] = list(classes) + ['external-link']
        else:
            a.attrs.pop('target', None)
        a.clear()
        a.append(new_t)
        nxt.replace_with(NavigableString(tail[len(remainder):]))
        logger.info(
            "Repaired split reference anchor: %r + %r -> %r", atext, remainder, new_t
        )
        return True
    return False


def _replace_ref_in_block(
    soup: BeautifulSoup,
    block: Tag,
    old_t: str,
    new_t: str,
    anchor: str,
    url: str,
    skip_linked_text: bool,
    occurrence: int = 0,
) -> bool:
    """Replace/link one reference inside a single block. Updates existing ``<a>`` hrefs.

    ``occurrence`` selects *which* copy of ``old_t`` to act on when the same
    label appears more than once in the block (0 = first). Without it every
    reference in a paragraph resolved to the first match, so a paragraph like
    "...for Patents, Section IV.G.8, or for Plant Varieties, Section IV.G.9"
    linked only the first of each pair and left the rest as plain text.

    Callers process work items in descending ``(paragraph, start)`` order, which
    keeps this index stable: replacing a later occurrence never shifts the
    position of an earlier one.
    """
    if block.find_parent(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        return False
    pat = _ref_flexible_pattern(old_t)
    raw_pat = _guarded_ref_regex(re.escape(old_t).replace(r'\ ', r'\s+'))
    safe_u = sanitize_external_href(url) if url else ''
    link_href = safe_u if safe_u else (f'#{anchor}' if anchor else '')
    target_occurrence = max(0, int(occurrence or 0))
    seen = 0

    for element in list(block.find_all(string=True)):
        if not isinstance(element, NavigableString):
            continue
        if element.parent and getattr(element.parent, 'name', None) in ('script', 'style'):
            continue
        parent = element.parent
        if parent and parent.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            continue
        if parent and parent.find_parent(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            continue

        original = str(element)
        spans = [m.span() for m in raw_pat.finditer(original)]
        if not spans:
            # Whitespace-tolerant fallback for labels split by odd spacing.
            if pat.search(_normalize_ws_for_ref_match(original)):
                idx = original.find(old_t)
                if idx >= 0:
                    spans = [(idx, idx + len(old_t))]
            if not spans:
                continue

        # Walk past text nodes holding earlier occurrences of the same label.
        if seen + len(spans) <= target_occurrence:
            seen += len(spans)
            continue
        local_index = target_occurrence - seen
        seen += len(spans)

        existing_a = None
        if parent:
            if parent.name == 'a':
                existing_a = parent
            else:
                existing_a = parent.find_parent('a')
        if existing_a is not None and skip_linked_text:
            continue

        start, end = spans[local_index]
        before, after = original[:start], original[end:]

        if existing_a is not None:
            if link_href:
                existing_a['href'] = link_href
                if safe_u:
                    existing_a['target'] = '_blank'
                    existing_a['rel'] = 'noopener noreferrer'
                    classes = existing_a.get('class') or []
                    if isinstance(classes, str):
                        classes = [classes]
                    if 'external-link' not in classes:
                        existing_a['class'] = list(classes) + ['external-link']
                else:
                    existing_a.attrs.pop('target', None)
            if _normalize_ws_for_ref_match(existing_a.get_text() or '') == _normalize_ws_for_ref_match(old_t):
                existing_a.clear()
                existing_a.append(new_t)
            else:
                element.replace_with(NavigableString(before + new_t + after))
            return True

        nodes: list = []
        if before:
            nodes.append(NavigableString(before))
        if link_href:
            tag = soup.new_tag('a', href=link_href)
            if safe_u:
                tag['target'] = '_blank'
                tag['rel'] = 'noopener noreferrer'
                tag['class'] = 'external-link'
            tag.string = new_t
            nodes.append(tag)
        else:
            nodes.append(NavigableString(new_t))
        if after:
            nodes.append(NavigableString(after))
        if not nodes:
            continue
        first, *rest = nodes
        element.replace_with(first)
        ref = first
        for piece in rest:
            ref.insert_after(piece)
            ref = piece
        return True

    # No single text node held the label. It may be split across an existing
    # anchor boundary (Word cross-reference fields do this) — try to repair
    # that before the caller falls back to offset-based replacement.
    if not skip_linked_text and target_occurrence == 0:
        return _absorb_split_reference_anchor(block, old_t, new_t, link_href, safe_u)
    return False

def _find_reference_block(
    paragraphs: list[Tag],
    block_index: list[tuple[Tag, str]],
    para_idx: int,
    old_t: str,
    prefer_para_text: str | None,
) -> Tag | None:
    """Locate the HTML block for a DOCX reference without scanning text nodes."""
    # Guarded matching throughout: a bare `old_t in text` substring test let a
    # short label ("Section II.F") claim the block belonging to a longer one
    # ("Section II.F.6") and link the wrong target.
    pat = _ref_flexible_pattern(old_t)

    # 1) Fast path: DOCX paragraph index → non-table <p> list
    if isinstance(para_idx, int) and 0 <= para_idx < len(paragraphs):
        p = paragraphs[para_idx]
        if pat.search(_normalize_ws_for_ref_match(p.get_text())):
            return p

    # 2) Prefer DOCX paragraph full-text match
    prefer_norm = _normalize_ws_for_ref_match(prefer_para_text) if prefer_para_text else ''
    if prefer_norm:
        for block, norm in block_index:
            if norm == prefer_norm:
                return block

    # 3) First block that contains the reference text
    for block, norm in block_index:
        if pat.search(norm):
            return block
    return None

def _apply_reference_edits_impl(soup: BeautifulSoup, edits: dict, references: list, validations: dict = None, link_targets: dict = None, auto_crosswalk: dict = None, new_headings: dict = None, reference_ignored: dict = None, reference_external_urls: dict = None, skip_linked_text: bool = False, rebuild_links: bool = False) -> None:
    if not references or validations is None:
        return
    if rebuild_links:
        pat = re.compile(r'(?:Section|Chapter)\s+[\dIVXLCDM]+(?:\.[A-Za-z\d]+)+|(?<!\w)[\dIVXLCDM]+(?:\.[A-Za-z\d]+){2,}(?!\w)', re.IGNORECASE)
        for a in soup.find_all('a', href=True):
            if a.get('href', '').startswith('#') and pat.search(normalize_spaces(a.get_text() or '')):
                a.unwrap()

    # Every id present once heading ids have been assigned. Used to reject
    # stale internal anchors saved in the External URL field (see below).
    live_ids = {
        (t.get('id') or '').strip()
        for t in soup.find_all(id=True)
        if (t.get('id') or '').strip()
    }

    # Ordinal of each reference among the references sharing its paragraph and
    # label, so two copies of the same label in one paragraph link separately.
    # Built over *all* detected references (not just the approved ones) because
    # the ordinal must match the text, where unapproved copies remain in place.
    starts_by_label: dict[tuple, list] = {}
    for r in references:
        starts_by_label.setdefault(
            (r[0], _normalize_ws_for_ref_match(r[2]).lower()), []
        ).append(r[3])
    for starts in starts_by_label.values():
        starts.sort()

    work: list[dict] = []
    for r in references:
        para = r[0]
        para_text = r[1] if len(r) > 1 else ''
        old = r[2]
        start = r[3]
        rid = generate_stable_ref_id(para, start, old)
        if reference_ignored and reference_ignored.get(rid):
            continue
        if not (
            validations.get(rid)
            or (edits and edits.get(rid))
            or (link_targets and link_targets.get(rid))
            or (reference_external_urls and reference_external_urls.get(rid))
        ):
            continue
        target = (link_targets.get(rid) or '').strip() if link_targets else ''
        disp = (edits.get(rid) or '').strip() if edits else ''
        if not disp and auto_crosswalk:
            disp = auto_crosswalk.get(old, '') or ''
        if not disp:
            disp = old
        url = (reference_external_urls.get(rid) or '').strip() if reference_external_urls else ''
        # An internal anchor saved in the External URL field is usually a
        # prefill carried over from an earlier cycle. If its target no longer
        # exists, honoring it built a link that _unwrap_dead_fragment_links then
        # stripped, silently demoting the reference to plain text. Fall back to
        # the anchor this conversion resolved instead.
        if url.startswith('#') and url[1:] not in live_ids:
            logger.warning(
                "Reference %r: External URL %r has no matching id in this "
                "conversion; using the resolved anchor instead.", old, url,
            )
            url = ''
        aid = _resolve_reference_anchor_id(old, disp, target, new_headings, auto_crosswalk)
        label_key = (para, _normalize_ws_for_ref_match(old).lower())
        starts = starts_by_label.get(label_key) or [start]
        work.append({
            'para': para,
            'para_text': para_text,
            'old': old,
            'new': disp,
            'anchor': aid,
            'url': url,
            'start': start,
            'occurrence': starts.index(start) if start in starts else 0,
        })

    if not work:
        return

    # Build lookup structures once — full-document rescans per ref were timing
    # out Gunicorn on large manuals (Faculty Manual ~2 minutes for 80 refs).
    manual_root = find_manual_container(soup) or soup
    paragraphs = [p for p in manual_root.find_all('p') if not p.find_parent('table')]
    blocks: list[Tag] = []
    for tag_name in ('p', 'li', 'td', 'th', 'dd', 'blockquote'):
        blocks.extend(manual_root.find_all(tag_name))
    block_index = [
        (b, _normalize_ws_for_ref_match(b.get_text()))
        for b in blocks
        if not b.find_parent(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    ]

    for ent in sorted(work, key=lambda x: (x['para'], x['start']), reverse=True):
        block = _find_reference_block(
            paragraphs,
            block_index,
            ent['para'],
            ent['old'],
            ent.get('para_text') or None,
        )
        if block is None:
            continue
        if not _replace_ref_in_block(
            soup,
            block,
            ent['old'],
            ent['new'],
            ent['anchor'],
            ent['url'],
            skip_linked_text,
            occurrence=ent.get('occurrence', 0),
        ):
            # Offset-based legacy path when the block was found by index but
            # text-node walk missed (unusual formatting).
            if block.name == 'p' and block in paragraphs:
                _replace_reference_at_offset(
                    block,
                    ent['old'],
                    ent['new'],
                    ent['anchor'],
                    ent['url'],
                    soup,
                    ent['start'],
                    skip_linked_text,
                )
        # Refresh cached text for the mutated block so later refs in the same
        # paragraph still match.
        for i, (b, _norm) in enumerate(block_index):
            if b is block:
                block_index[i] = (b, _normalize_ws_for_ref_match(b.get_text()))
                break

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
        pref = manual_prefix(manual_type)
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
    if not config.get('preserve_numbers'):
        _strip_heading_numbers_dom_impl(soup)
    id_remap = _add_heading_ids_impl(soup, stable_map=config.get('stable_heading_map'))
    # Pandoc/Word body hyperlinks still point at the pre-rewrite ids — retarget
    # them before reference linking so keep_old / preserve manuals keep working.
    if id_remap:
        n = _rewrite_internal_hrefs(soup, id_remap)
        if n:
            logger.info("Rewrote %d internal href(s) after heading id assignment", n)
    if config.get('heading_edits'):
        _apply_heading_edits_impl(soup, config.get('heading_edits'))
    _normalize_typed_lists_impl(soup)
    _apply_list_classes_and_styles_impl(soup)
    # Header structure before alignment: the alignment pass stamps scope="col"
    # on whatever sits in <thead>, so the rows have to be right first.
    _normalize_table_headers_impl(soup, config.get('table_headers'))
    _format_manual_tables_impl(
        soup,
        config.get('table_align_mode', 'auto'),
        config.get('table_col1_align'),
        config.get('table_col2_align'),
        config.get('table_col3_align'),
        config.get('table_coln_align'),
        config.get('table_header_align'),
    )
    if config.get('references'):
        # Resolve anchors from *final* live heading ids (after strip/map/edits),
        # not the early upload-scrape new_headings which can diverge under
        # permalink maps / CSS-numbering scrape timing.
        from core.manual_structure import scrape_heading_structure_from_html
        live_headings = scrape_heading_structure_from_html(str(soup))
        if not live_headings:
            live_headings = config.get('new_headings', {}) or {}
        _apply_reference_edits_impl(
            soup,
            config.get('reference_edits', {}),
            config.get('references', []),
            config.get('reference_validations', {}),
            config.get('reference_link_targets', {}),
            auto_crosswalk=config.get('auto_crosswalk', {}),
            new_headings=live_headings,
            reference_ignored=config.get('reference_ignored', {}),
            reference_external_urls=config.get('reference_external_urls', {}),
            skip_linked_text=config.get('skip_linked_text', False),
            rebuild_links=config.get('rebuild_links', False),
        )
    # Drop leftover Word-bookmark / orphan # links that still have no target
    dead = _unwrap_dead_fragment_links(soup)
    if dead:
        logger.info("Unwrapped %d dead internal href(s) with missing targets", dead)
    body_html = str(soup)
    toc_html = generate_server_side_toc(soup, config.get('toc_depth', 2))
    return sanitize_manual_html_fragment(body_html), sanitize_manual_html_fragment(toc_html)

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
    Parse a heading-map JSON file. Accepts these input shapes:
      1. Structured: {"version": 1, "entries": [{"signature": ..., "id": ...}, ...]}
      2. Bare list:  [{"signature": ..., "id": ...}, ...]
      3. Flat dict (legacy): {"<signature>": "<id>", ...}
      4. Flat dict (current): {"<signature>": ["<id>", "<id>", ...], ...}
    Returns {normalized_signature: [ids in document order]}. Duplicate-text
    headings are preserved as multiple ids per signature; an ``{"ids": [...]}``
    entry or a list value is honored, and a scalar id is coerced to a 1-list.
    """
    if not raw_text:
        return {}
    try:
        data = json.loads(raw_text)
    except Exception as exc:
        logger.warning(f"Failed to parse heading map JSON: {exc}")
        return {}
    entries = []
    if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
        entries = data["entries"]
    elif isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        for key, value in data.items():
            entries.append({"signature": key, "id": value})

    def _ids_from(entry: dict) -> list[str]:
        raw = entry.get("ids")
        if raw is None:
            raw = entry.get("id")
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        s = (str(raw).strip() if raw is not None else "")
        return [s] if s else []

    heading_map: dict[str, list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        signature = normalize_heading_signature(entry.get("signature") or "")
        ids = _ids_from(entry)
        if signature and ids:
            heading_map.setdefault(signature, []).extend(ids)
    return heading_map


def build_manual_grid_block(
    body_html: str,
    toc_depth: int,
    manual_type: str,
    numbering_mode: str,
    heading_offset: int = 0,
    theme_id: str = "manual",
    *,
    toc_html: str | None = None,
) -> str:
    """Assemble the full manual grid HTML block with accessible TOC and search.

    If ``toc_html`` is set (server-rendered list from ``generate_server_side_toc``),
    it is injected inside ``<nav>``; otherwise an empty ``<ul>`` is emitted for
    client-side TOC population (``wordpress.js``).
    """
    body_html = format_manual_tables(body_html)

    # These land in HTML attributes and can arrive from an imported document's
    # own grid metadata, so constrain them rather than interpolating raw:
    #   - manual_type is collapsed to the two values the CSS and JS understand
    #     ("policy" reached the attribute and matched neither, so a policy
    #     manual silently rendered with Chapter numbering);
    #   - numbering_mode is an enum;
    #   - toc_depth / heading_offset are integers.
    grid_manual_type = normalize_manual_type(manual_type)
    grid_numbering_mode = (
        numbering_mode if numbering_mode in ("css-counters", "preserve") else "css-counters"
    )
    try:
        grid_toc_depth = max(1, min(6, int(toc_depth)))
    except (TypeError, ValueError):
        grid_toc_depth = 2
    try:
        heading_offset = max(-5, min(5, int(heading_offset or 0)))
    except (TypeError, ValueError):
        heading_offset = 0

    offset_attr = f' data-heading-offset="{heading_offset}"' if heading_offset else ""
    theme_attr = f' data-theme="{sanitize_theme_id(theme_id, "manual")}"'
    toc_block = (
        f"    {toc_html.strip()}\n"
        if (toc_html and toc_html.strip())
        else '    <ul aria-labelledby="toc-heading" aria-live="polite"></ul>\n'
    )
    return (
        '<!-- ACCESSIBILITY: Skip navigation link for keyboard users (WCAG 2.4.1) -->\n'
        '<a href="#main-content" class="skip-to-main">Skip to main content</a>\n'
        f'<div class="manual-grid" data-toc-depth="{grid_toc_depth}" data-manual-type="{grid_manual_type}" data-numbering-mode="{grid_numbering_mode}"{offset_attr}{theme_attr}>\n'
            '  <nav class="manual-toc" role="navigation" aria-label="Table of Contents">\n'
            '    <h2 id="toc-heading">Table of Contents</h2>\n'
            '    <div class="manual-search">\n'
            '      <input type="text" class="manual-search-input" placeholder="Search headings and content..." aria-label="Search table of contents" aria-describedby="search-help" role="searchbox">\n'
            '      <button type="button" class="manual-search-clear" aria-label="Clear search">X</button>\n'
            '    </div>\n'
            '    <span id="search-help" class="sr-only">Type to filter headings and content</span>\n'
            f"{toc_block}"
            '  </nav>\n'
            f'  <main class="manual" id="main-content" role="main" tabindex="-1">\n'
            f'    {body_html}\n'
            '  </main>\n'
            '</div>\n'
        )
