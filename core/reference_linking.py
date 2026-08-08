import logging
import re
from bs4 import BeautifulSoup, NavigableString

logger = logging.getLogger(__name__)

_REF_PATTERN = re.compile(
    r'(?:Section|Chapter)\s+[\dIVXLCDM]+(?:\.[A-Za-z\d]+)+|'
    r'(?<!\w)[\dIVXLCDM]+(?:\.[A-Za-z\d]+){2,}(?!\w)',
    re.IGNORECASE
)

# Degree / credential acronyms that match the bare dotted-ref pattern (e.g. D.V.M.)
# but are never internal manual cross-references.
_DEGREE_ACRONYM_RE = re.compile(
    r"^(?:"
    r"D\.?V\.?M|"
    r"D\.?N\.?P|"
    r"D\.?M\.?D|"
    r"Ed\.?D|"
    r"Ph\.?D|"
    r"M\.?S\.?N|"
    r"M\.?P\.?H|"
    r"M\.?B\.?A|"
    r"M\.?Ed|"
    r"M\.?S|"
    r"M\.?A|"
    r"B\.?S|"
    r"B\.?A|"
    r"B\.?S\.?N|"
    r"LL\.?M|"
    r"J\.?D|"
    r"O\.?D|"
    r"D\.?D\.?S|"
    r"Psy\.?D"
    r")\.?$",
    re.IGNORECASE,
)
# Bare letter-only dotted tokens with no digits (e.g. D.V.M., A.B.C.) — not section numbers.
_BARE_LETTER_DOTTED_RE = re.compile(
    r"^[A-Za-z]{1,4}(?:\.[A-Za-z]{1,4}){1,4}\.?$"
)


def is_non_reference_token(ref: str) -> bool:
    """True when a regex hit is a degree/credential acronym, not a manual cite."""
    s = (ref or "").strip()
    if not s:
        return True
    if re.match(r"^(?:Chapter|Section)\s+", s, re.IGNORECASE):
        return False
    if _DEGREE_ACRONYM_RE.match(s):
        return True
    if not re.search(r"\d", s) and _BARE_LETTER_DOTTED_RE.match(s):
        return True
    return False


def _normalize_spaces(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def extract_references_from_html(html: str) -> list:
    """
    Identify academic-style references block by block.
    Searches p, li, td, blockquote, dt, dd elements.
    Returns: list of (block_index, full_text, old_ref_string, start_pos, end_pos, is_linked)
    """
    soup = BeautifulSoup(html, 'html.parser')
    references = []

    blocks = soup.find_all(['p', 'li', 'td', 'blockquote', 'dt', 'dd'])
    for idx, block in enumerate(blocks):
        text_parts = []
        segments = []
        pos = 0

        for node in block.descendants:
            if isinstance(node, NavigableString):
                text = _normalize_spaces(str(node))
                if not text:
                    continue
                text_parts.append(text)
                end_pos = pos + len(text)
                parent = node.parent
                in_link = False
                if parent:
                    if parent.name == 'a' or parent.find_parent('a'):
                        in_link = True
                segments.append((pos, end_pos, in_link))
                pos = end_pos

        full_text = ''.join(text_parts)
        if not full_text.strip():
            continue

        for match in _REF_PATTERN.finditer(full_text):
            old_ref = match.group(0)
            if is_non_reference_token(old_ref):
                continue
            start_pos = match.start()
            end_pos = match.end()
            is_linked = False
            for seg_start, seg_end, in_link in segments:
                if in_link and start_pos < seg_end and end_pos > seg_start:
                    is_linked = True
                    break
            references.append((idx, full_text, old_ref, start_pos, end_pos, is_linked))

    return references

def extract_external_links_from_reference_text(references: list) -> dict:
    """
    Scan a references list (6-tuples) for paragraphs containing external URLs.
    Returns {para_idx: [url, ...]} for any http/https URLs found in reference text.
    """
    external_links = {}
    url_pattern = re.compile(r'https?://[^\s\)\]\}>"\']+')
    for ref in references or []:
        if len(ref) < 2:
            continue
        para_idx = ref[0]
        full_text = ref[1] or ''
        urls = url_pattern.findall(full_text)
        if urls:
            bucket = external_links.setdefault(para_idx, set())
            bucket.update(urls)
    return {idx: sorted(list(urls)) for idx, urls in external_links.items()}

def extract_external_links_from_html(html: str) -> dict:
    """
    Extract all external absolute URLs from the HTML, grouped by block index.
    Searches p, li, td, blockquote, dt, dd elements.
    Returns {block_idx: [url, ...]}
    """
    soup = BeautifulSoup(html, 'html.parser')
    external_links = {}
    blocks = soup.find_all(['p', 'li', 'td', 'blockquote', 'dt', 'dd'])
    for idx, block in enumerate(blocks):
        hrefs = []
        for anchor in block.find_all('a', href=True):
            href = anchor.get('href', '').strip()
            if href.lower().startswith(('http://', 'https://')):
                hrefs.append(href)
        if hrefs:
            external_links[idx] = sorted(set(hrefs))
    return external_links
