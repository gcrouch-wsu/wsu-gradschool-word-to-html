import re
import logging

logger = logging.getLogger(__name__)

# Spelled-out numbers used to normalize "Chapter One" -> "Chapter 1" etc.
SPELLED_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20
}

# --- Manual type ---------------------------------------------------------
# Documents are labeled "Chapter N" or "Section N" at the top level.
# Detection prefers those heading labels (see detect_manual_type_from_docx).
# "policy" is still accepted as an alias for section-style manuals (upload
# override / older sessions) and collapses to the same prefix as "section".
#
# Everything that needs the label word must go through manual_prefix(). It used
# to be decided independently in five places that disagreed: ensure_prefixed
# said "Chapter" for a policy manual while apply_css_counter_numbering said
# "Section", so a map_new conversion numbered headings one way and built its
# crosswalk keys the other and auto-matching silently found nothing.
_SECTION_STYLE_MANUAL_TYPES = frozenset({"section", "policy"})


def normalize_manual_type(manual_type: str | None) -> str:
    """Collapse a detected manual type to the two the renderer understands."""
    return "section" if is_section_style(manual_type) else "chapter"


def is_section_style(manual_type: str | None) -> bool:
    """True when this manual numbers its top level "Section N"."""
    return str(manual_type or "").strip().lower() in _SECTION_STYLE_MANUAL_TYPES


def manual_prefix(manual_type: str | None) -> str:
    """The heading label word for a manual type: "Chapter" or "Section"."""
    return "Section" if is_section_style(manual_type) else "Chapter"


def normalize_heading_signature(text: str) -> str:
    """
    Normalize a heading's full text into a stable lookup signature for the
    heading map. Lowercases, strips all non-alphanumeric characters
    (keeping spaces), and collapses whitespace.

    Example:
        "Chapter One - Administration of Graduate Programs"
        -> "chapter one  administration of graduate programs"
    """
    cleaned = re.sub(r"\s+", " ", text or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9 ]+", "", cleaned)
    return cleaned

def normalize_heading_ref(ref: str) -> str:
    """
    Normalize a heading reference string for consistent comparisons.
    - Trim whitespace/nbsp
    - Drop trailing punctuation (., :, -)
    - Convert leading spelled-out number ("Chapter One" -> "Chapter 1")
    """
    if ref is None:
        return ""
    cleaned = str(ref).replace('\u00a0', ' ').strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'[.\-:\u2014\u2013]+$', '', cleaned).strip()
    m = re.match(r'^(Chapter|Section)\s+([A-Za-z]+)\b(.*)$', cleaned, re.IGNORECASE)
    if m:
        prefix = m.group(1)
        word = m.group(2).lower()
        rest = m.group(3)
        if word in SPELLED_NUMS:
            cleaned = f"{prefix} {SPELLED_NUMS[word]}{rest}"
    return cleaned

def ensure_prefixed(ref: str, manual_type: str = "chapter") -> str:
    """
    Ensure a heading ref has a Chapter/Section word prefix that matches manual_type.
    Does NOT add abbreviated prefixes like "CH." or "POL." — those were never used
    in the original V4.
    """
    if not ref:
        return ""
    if re.match(r'^(Chapter|Section)\s+', ref, re.IGNORECASE):
        return ref.strip()
    return f"{manual_prefix(manual_type)} {ref.strip()}"
