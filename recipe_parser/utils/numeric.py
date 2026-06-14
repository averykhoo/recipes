# recipe_parser/utils/numeric.py
"""
Utility module for converting vulgar fractions, ASCII fractions, mixed numbers,
and range strings into unified, clean decimal strings.
"""

import re
from typing import Optional

import unicodedata

# Matches mixed numbers with ASCII fractions: e.g. "1 1/2", "3 3/4"
RE_MIXED_ASCII = re.compile(r"^(?P<whole>\d+)\s+(?P<num>\d+)/(?P<den>\d+)$")

# Matches standalone ASCII fractions: e.g. "1/2", "2/3"
RE_SIMPLE_ASCII = re.compile(r"^(?P<num>\d+)/(?P<den>\d+)$")

# Matches Unicode vulgar fractions, optionally preceded by a whole number
RE_VULGAR = re.compile(r"^(?P<whole>\d+)?(?P<vulgar>[\u00BC-\u00BE\u2150-\u215E])$")

# Matches simple integers or floats
RE_DECIMAL = re.compile(r"^\d+(?:\.\d+)?$")

# Matches range indicators: e.g. "1-2", "1.5 - 2.5", "1 to 2"
RE_RANGE = re.compile(r"^(?P<start>.+?)\s*(?:-|to)\s*(?P<end>.+?)$", re.IGNORECASE)


def format_float_to_string(value: float) -> str:
    """
    Formats a floating-point value to a clean string.
    If the value represents an integer, it is serialized without decimals.
    Otherwise, it strips trailing decimal zeros.
    """
    if value.is_integer():
        return str(int(value))
    rounded_value = round(value, 3)
    return f"{rounded_value:.3f}".rstrip("0").rstrip(".")


def parse_single_quantity(quantity_string: str) -> Optional[float]:
    """
    Evaluates a substring containing a quantity and attempts to parse it.
    Returns None if the substring cannot be resolved to a numeric value.
    """
    quantity_string = quantity_string.strip()

    # Check for approximate signs
    if quantity_string.startswith("~"):
        quantity_string = quantity_string.lstrip("~").strip()

    if RE_DECIMAL.match(quantity_string):
        return float(quantity_string)

    match_mixed = RE_MIXED_ASCII.match(quantity_string)
    if match_mixed:
        whole = int(match_mixed.group("whole"))
        num = int(match_mixed.group("num"))
        den = int(match_mixed.group("den"))
        return whole + (num / den)

    match_simple = RE_SIMPLE_ASCII.match(quantity_string)
    if match_simple:
        num = int(match_simple.group("num"))
        den = int(match_simple.group("den"))
        return num / den

    match_vulgar = RE_VULGAR.match(quantity_string)
    if match_vulgar:
        whole_str = match_vulgar.group("whole")
        whole = int(whole_str) if whole_str else 0
        vulgar_char = match_vulgar.group("vulgar")
        return whole + unicodedata.numeric(vulgar_char)

    return None


def parse_quantity_string(raw_quantity: str) -> str:
    """
    Converts raw quantity inputs into standardized, unified decimal strings.
    This preserves approximate indicators and range notations cleanly.
    """
    raw_quantity = raw_quantity.strip()
    if not raw_quantity:
        return ""

    # Preserve approximate prefixes while normalising the underlying float
    is_approximate = raw_quantity.startswith("~")
    clean_raw = raw_quantity.lstrip("~").strip()

    # Check if the string represents a quantity range (for example: "1-2" or "1/2 to 3/4")
    range_match = RE_RANGE.match(clean_raw)
    if range_match:
        start_val = parse_single_quantity(range_match.group("start"))
        end_val = parse_single_quantity(range_match.group("end"))
        if start_val is not None and end_val is not None:
            prefix = "~" if is_approximate else ""
            return f"{prefix}{format_float_to_string(start_val)}-{format_float_to_string(end_val)}"

    # Check if the string is a simple single value
    single_val = parse_single_quantity(clean_raw)
    if single_val is not None:
        prefix = "~" if is_approximate else ""
        return f"{prefix}{format_float_to_string(single_val)}"

    # If the quantity cannot be parsed (for example: "some" or "a few"), return it as is
    return raw_quantity
