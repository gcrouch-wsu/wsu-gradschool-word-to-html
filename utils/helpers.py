import re

def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer. Returns -1 if invalid."""
    if not s:
        return -1
    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    prev = 0
    s = s.upper()
    for ch in reversed(s):
        if ch not in roman_map:
            return -1
        val = roman_map[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total

def _int_to_roman(num: int) -> str:
    """Convert an integer to a Roman numeral string."""
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    roman_num = ''
    i = 0
    while num > 0:
        for _ in range(num // val[i]):
            roman_num += syb[i]
            num -= val[i]
        i += 1
    return roman_num

def _int_to_letters(num: int, upper: bool = True) -> str:
    """Convert an integer to a letter sequence (1=A, 26=Z, 27=AA)."""
    letters = ""
    while num > 0:
        num, remainder = divmod(num - 1, 26)
        letters = chr((65 if upper else 97) + remainder) + letters
    return letters

def _format_number(value: int, fmt: str) -> str:
    """Format a number according to a Word-style numFmt."""
    if fmt == "lowerLetter": return _int_to_letters(value, upper=False)
    if fmt == "upperLetter": return _int_to_letters(value, upper=True)
    if fmt == "lowerRoman": return _int_to_roman(value).lower()
    if fmt == "upperRoman": return _int_to_roman(value).upper()
    return str(value)

def _token_type_from_numfmt(numfmt: str) -> str:
    """Return the internal type name for a Word numFmt."""
    if numfmt in ("lowerLetter", "upperLetter"): return "alpha"
    if numfmt in ("lowerRoman", "upperRoman"): return "roman"
    return "decimal"

_HEX_COLOR_RE = re.compile(r'^(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$')


def normalize_hex_color(value: str, fallback: str = "#000000") -> str:
    """Ensure a hex color string is in #RRGGBB format.

    The digits are checked, not just the length. Accepting any six characters
    meant "a;}x{y" normalized to "#A;}X{Y", and these values are interpolated
    into a generated stylesheet — so it closed the declaration and opened a rule
    of the attacker's choosing. Reachable from a crafted session bundle, whose
    theme settings flow into the CSS download that gets pasted site-wide.
    """
    if not value:
        return fallback
    value = str(value).strip().lstrip('#')
    if not _HEX_COLOR_RE.match(value):
        return fallback
    if len(value) == 3:
        value = ''.join(c * 2 for c in value)
    return f"#{value.upper()}"

def clamp_number(value: float, min_val: float, max_val: float, fallback: float | None = None) -> float:
    """Clamp a number between a minimum and maximum value."""
    try:
        v = float(value)
        return max(min_val, min(v, max_val))
    except (ValueError, TypeError):
        return fallback if fallback is not None else min_val

def sanitize_theme_id(theme_id: str, default: str = "manual") -> str:
    """Sanitize a theme ID for use in HTML data attributes."""
    if not theme_id: return default
    return re.sub(r'[^a-z0-9_-]', '', str(theme_id).lower())
