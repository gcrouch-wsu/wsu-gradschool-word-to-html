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
    prefix = "Section" if manual_type == "section" else "Chapter"
    return f"{prefix} {ref.strip()}"
