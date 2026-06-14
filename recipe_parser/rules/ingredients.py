# recipe_parser/rules/ingredients.py
"""
Rule processor for parsing individual ingredient lines, extracting
canonical units, state modifiers, quantities, and optional flags.
"""

import re
from typing import Optional

from recipe_parser.models.schemas import Ingredient
from recipe_parser.utils.numeric import parse_quantity_string
from recipe_parser.utils.sanitizer import strip_html_and_markdown_comments

# Normalization structure for mapping variations to standardized units.
# Each key represents the standardized canonical unit of measure,
# and the corresponding list contains the various aliases to match against.
CANONICAL_UNITS: dict[str, list[str]] = {
    "l":        ["l", "litre", "litres", "liter", "liters"],
    "ml":       ["ml", "millilitre", "milli-litre", "milli litre", "millilitres", "milliliters", "milliliter",
                 "milli-liter"],
    "g":        ["g", "gram", "grams"],
    "mg":       ["mg", "milligram", "milligrams"],
    "kg":       ["kg", "kilogram", "kilograms"],
    "oz":       ["oz", "ounce", "ounces", "-ounce"],
    "qt":       ["qt", "quart", "quarts"],
    "fl":       ["fl", "fl-oz", "fl. oz.", "fluid-ounce", "fluid ounce"],
    "tsp":      ["tsp", "tsps", "tsp.", "tsps.", "teaspoon", "teaspoons"],
    "Tbsp":     ["tbsp", "tbs", "tbsps", "tbsp.", "tbsps.", "tablespoon", "tablespoons"],
    "cup":      ["cup", "cups", "c.", "c"],
    "pint":     ["pint", "pints"],
    "pinch":    ["pinch", "pinches"],
    "strip":    ["strip", "strips"],
    "envelope": ["envelope", "envelopes", "sheet", "sheets"],
    "gal":      ["gal", "gallon", "gallons"],
    "dash":     ["dash", "dashes"],
    "can":      ["can", "cans"],
    "lb":       ["lb", "lbs", "lb.", "lbs.", "pound", "pounds", "-pound"],
    "whole":    ["whole"],
    "head":     ["head", "heads"],
    "clove":    ["clove", "cloves"],
    "bunch":    ["bunch", "bunches"],
    "handful":  ["handful", "handfuls"],
    "piece":    ["piece", "pieces", "pc", "pc.", "pcs"],
    "inch":     ["inch", "inches", "\""],
    "cm":       ["cm"]
}

# Expand variations into a flat lookup table mapping lowercase strings to canonical keys
UNIT_LOOKUP: dict[str, str] = {}
for canonical_key, variations in CANONICAL_UNITS.items():
    for variation in variations:
        UNIT_LOOKUP[variation.lower()] = canonical_key

# Matches numbers, fractions, ranges, or approximate values at the beginning of a string
RE_LEADING_QUANTITY = re.compile(
    r"^(?P<qty>~\s*\d+(?:\s*/\s*|\s+-?\s*)\d+|\d+\s*-\s*\d+|~\s*\d+(?:\.\d+)?|\d+(?:\s*/\s*|\s+-?\s*)\d+|\d+(?:\.\d+)?|[\u00BC-\u00BE\u2150-\u215E])\s*(?P<rest>.+)$",
    re.UNICODE
)


def extract_optional_status(raw_item: str) -> tuple[str, bool]:
    """
    Detects if an ingredient is marked as optional, returning the cleaned
    string with the comments stripped and the optional status.
    """
    is_optional = False
    cleaned_string = raw_item.strip()

    # Look for leading "Optional: " text
    if cleaned_string.lower().startswith("optional:"):
        is_optional = True
        cleaned_string = cleaned_string[len("optional:"):].strip()

    # Look for trailing "(optional)" or ", optional" patterns
    if cleaned_string.lower().endswith("(optional)"):
        is_optional = True
        cleaned_string = cleaned_string[:-len("(optional)")].strip().rstrip(",").strip()
    elif cleaned_string.lower().endswith(", optional"):
        is_optional = True
        cleaned_string = cleaned_string[:-len(", optional")].strip()

    return cleaned_string, is_optional


def parse_ingredient_line(raw_line: str) -> Optional[Ingredient]:
    """
    Tokenizes raw Markdown ingredient strings into validated schemas,
    extracting quantities, canonical units, and modifiers.
    """
    cleaned_line = strip_html_and_markdown_comments(raw_line).strip()
    if not cleaned_line:
        return None

    # Remove standard list item prefixes
    cleaned_line = re.sub(r"^[\*\-+]\s+", "", cleaned_line)

    # Extract the optional flag status
    cleaned_line, is_optional = extract_optional_status(cleaned_line)

    quantity_part = ""
    unit_part = ""
    name_part = cleaned_line
    modifier_part = None

    # Scan for a leading quantity format
    qty_match = RE_LEADING_QUANTITY.match(cleaned_line)
    if qty_match:
        raw_qty = qty_match.group("qty")
        remaining_text = qty_match.group("rest").strip()

        # Check if the subsequent word matches a recognized unit
        words_in_rest = remaining_text.split(" ", 1)
        first_word = words_in_rest[0].rstrip(".").strip()

        if first_word.lower() in UNIT_LOOKUP:
            quantity_part = parse_quantity_string(raw_qty)
            unit_part = UNIT_LOOKUP[first_word.lower()]
            name_part = words_in_rest[1].strip() if len(words_in_rest) > 1 else ""
        else:
            # Simple count items (such as: "2 eggs")
            quantity_part = parse_quantity_string(raw_qty)
            name_part = remaining_text

    # Extract preparation details separated by a comma (for example: "onions, diced")
    if "," in name_part:
        comma_parts = name_part.split(",", 1)
        # Avoid splitting decimal coordinates or conversion brackets
        if not (comma_parts[0] and comma_parts[0][-1].isdigit() and comma_parts[1] and comma_parts[1][0].isdigit()):
            name_part = comma_parts[0].strip()
            modifier_part = comma_parts[1].strip()

    return Ingredient(
        raw=raw_line.strip(),
        quantity=quantity_part,
        unit=unit_part,
        name=name_part,
        modifier=modifier_part,
        optional=is_optional
    )
