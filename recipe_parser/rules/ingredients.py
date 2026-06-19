# recipe_parser/rules/ingredients.py
"""
Rule processor for parsing individual ingredient lines, extracting
canonical units, alternative conversions, and piece-nested container capacities.
"""

import re
from typing import List, Optional

from recipe_parser.models.schemas import Ingredient, QuantityRepresentation, Measurement, UnitClass
from recipe_parser.utils.numeric import parse_single_quantity
from recipe_parser.utils.sanitizer import strip_html_and_markdown_comments

# Unified canonical unit maps (mapping variations to full proper words)
UNIT_CLASSIFICATIONS = {
    # Volume
    "tablespoon": (UnitClass.VOLUME, ["tbsp", "tbs", "tbsps", "tbsp.", "tablespoon", "tablespoons", "tbs"]),
    "teaspoon": (UnitClass.VOLUME, ["tsp", "tsps", "tsp.", "teaspoon", "teaspoons"]),
    "milliliter": (UnitClass.VOLUME, ["ml", "milliliter", "milliliters", "millilitre", "millilitres"]),
    "liter": (UnitClass.VOLUME, ["l", "liter", "liters", "litre", "litres"]),
    "cup": (UnitClass.VOLUME, ["cup", "cups", "c"]),
    # Weight
    "gram": (UnitClass.WEIGHT, ["g", "gram", "grams"]),
    "kilogram": (UnitClass.WEIGHT, ["kg", "kilogram", "kilograms"]),
    "ounce": (UnitClass.WEIGHT, ["oz", "ounce", "ounces"]),
    "pound": (UnitClass.WEIGHT, ["lb", "lbs", "pound", "pounds"]),
    # Piece
    "whole": (UnitClass.PIECE, ["whole"]),
    "clove": (UnitClass.PIECE, ["clove", "cloves"]),
    "slice": (UnitClass.PIECE, ["slice", "slices"]),
    "block": (UnitClass.PIECE, ["block", "blocks"]),
    "can": (UnitClass.PIECE, ["can", "cans"]),
    "stick": (UnitClass.PIECE, ["stick", "sticks"]),
    "envelope": (UnitClass.PIECE, ["envelope", "envelopes", "sheet", "sheets"]),
    "bunch": (UnitClass.PIECE, ["bunch", "bunches"]),
    "head": (UnitClass.PIECE, ["head", "heads"]),
    "piece": (UnitClass.PIECE, ["piece", "pieces", "pc", "pcs"]),
}

# Reverse mapping for fast regex scanning
UNIT_LOOKUP = {}
for canonical, (u_class, aliases) in UNIT_CLASSIFICATIONS.items():
    for alias in aliases:
        UNIT_LOOKUP[alias.lower()] = (canonical, u_class)

# Matches leading floats, fractions, or range-midpoints
RE_LEADING_NUM = re.compile(
    r"^(?P<val>\d+(?:\s*/\s*|\s+-?\s*)\d+|\d+(?:\.\d+)?|[\u00BC-\u00BE\u2150-\u215E])\s*(?P<rest>.+)?$",
    re.UNICODE
)

# Strips leading quantity values, approximate symbols, and canonical unit keywords
unit_aliases_sorted = sorted(list(UNIT_LOOKUP.keys()), key=len, reverse=True)
escaped_aliases = [re.escape(alias) for alias in unit_aliases_sorted]
RE_UNIT_STRIP = re.compile(
    r"^\s*~?\s*\d*(?:\s*/\s*|\s+-?\s*|\s*\.\s*)?\d*\s*(?:" + "|".join(escaped_aliases) + r")\s*(?:of\s+)?",
    re.IGNORECASE
)


def parse_single_term(term_text: str) -> Optional[Measurement]:
    """
    Extracts a single structured measurement from a trimmed string run (e.g. '1/2 cup').
    """
    match = RE_LEADING_NUM.match(term_text.strip())
    if not match:
        return None

    raw_val = match.group("val")
    rest = (match.group("rest") or "").strip()

    words = rest.split(" ", 1)
    if not words:
        return None

    first_word = words[0].rstrip(".").strip().lower()

    if first_word in UNIT_LOOKUP:
        canonical_name, unit_class = UNIT_LOOKUP[first_word]
        parsed_val = parse_single_quantity(raw_val)
        if parsed_val is not None:
            return Measurement(value=parsed_val, unit=canonical_name, unit_class=unit_class)

    return None


def parse_representation(text_run: str) -> QuantityRepresentation:
    """
    Parses additive terms inside a single representation run (e.g. '0.5 cup + 1 teaspoon').
    """
    representation = QuantityRepresentation(raw_text=text_run.strip())

    # Split on standard addition operators
    raw_terms = re.split(r"\s+(?:\+|\bplus\b|\band\b)\s+", text_run, flags=re.IGNORECASE)

    for raw_term in raw_terms:
        # Check if the term represents a piece-nested capacity: e.g. "2 cans (15 oz each)"
        nested_match = re.match(
            r"^(?P<mult>\d+)\s+(?P<container>\w+)\s*[\(\[【（](?P<cap>.+?)\s*(?:each|ea)?[\)\]】）]$",
            raw_term.strip(),
            re.IGNORECASE
        )
        if nested_match:
            mult_val = parse_single_quantity(nested_match.group("mult"))
            container_word = nested_match.group("container").lower().rstrip("s")

            if container_word in UNIT_LOOKUP and mult_val is not None:
                container_canonical, container_class = UNIT_LOOKUP[container_word]
                if container_class == UnitClass.PIECE:
                    nested_meas = parse_single_term(nested_match.group("cap"))
                    if nested_meas and nested_meas.unit_class in (UnitClass.VOLUME, UnitClass.WEIGHT):
                        meas = Measurement(
                            value=mult_val,
                            unit=container_canonical,
                            unit_class=container_class,
                            nested_capacity=nested_meas
                        )
                        representation.terms.append(meas)
                        continue

        # Standard Term Case
        meas = parse_single_term(raw_term)
        if meas:
            representation.terms.append(meas)

    return representation


def parse_ingredient_line(raw_line: str) -> Optional[Ingredient]:
    """
    Transforms raw lists into Pydantic models. Resolves alternatives
    nested inside brackets or parentheses.
    """
    cleaned_line = strip_html_and_markdown_comments(raw_line).strip()
    if not cleaned_line:
        return None

    cleaned_line = re.sub(r"^[\*\-+]\s+", "", cleaned_line)

    # Check for optional flags
    is_optional = False
    if cleaned_line.lower().startswith("optional:"):
        is_optional = True
        cleaned_line = cleaned_line[len("optional:"):].strip()
    if cleaned_line.lower().endswith("(optional)"):
        is_optional = True
        cleaned_line = cleaned_line[:-len("(optional)")].strip().rstrip(",").strip()

    # Extract alternative representations inside parentheses or brackets
    representations_text = []
    main_and_modifier = cleaned_line

    # Matches brackets like (65g) or 【118 mL】
    bracket_matches = list(re.finditer(r"[\(\[【（](?P<inner>.+?)[\)\]】）]", cleaned_line))

    # We only treat bracketed runs as alternative units if they begin with a digit
    for match in bracket_matches:
        inner_text = match.group("inner").strip()
        if RE_LEADING_NUM.match(inner_text):
            representations_text.append(inner_text)
            # Remove the bracketed alternative from the main parsing string
            main_and_modifier = main_and_modifier.replace(match.group(0), "").strip()

    # Parse the primary representation (everything before the alternative brackets)
    primary_text = ""
    modifier = None

    # Split preparation details on comma
    if "," in main_and_modifier:
        parts = main_and_modifier.split(",", 1)
        # Prevent splitting decimals
        if not (parts[0][-1].isdigit() and parts[1][0].isdigit()):
            primary_text = parts[0].strip()
            modifier = parts[1].strip()
    else:
        primary_text = main_and_modifier

    primary_rep = parse_representation(primary_text)

    parsed_representations = [primary_rep]
    for alt_text in representations_text:
        alt_rep = parse_representation(alt_text)
        if alt_rep.terms:
            parsed_representations.append(alt_rep)

    # Extract the true ingredient name by removing measurements
    ingredient_name = primary_text

    # 1. Strip leading unit and quantity if matched
    if primary_rep.terms:
        # Strip unit prefix cleanly
        stripped_name = RE_UNIT_STRIP.sub("", ingredient_name).strip()
        if stripped_name:
            ingredient_name = stripped_name
        else:
            # Fallback if stripping emptied it
            for _ in primary_rep.terms:
                ingredient_name = re.sub(r"\b\d+.*?\b", "", ingredient_name).strip()
    else:
        # Fallback for plain names with leading numbers but no units
        ingredient_name = re.sub(r"^\s*~?\s*\d*(?:\s*/\s*|\s+-?\s*|\s*\.\s*)?\d*\s*", "", ingredient_name).strip()

    # 2. Strip Markdown link brackets: [self-raising flour](...) -> self-raising flour
    ingredient_name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", ingredient_name)

    # 3. Strip any remaining descriptive brackets or parentheticals from the name
    ingredient_name = re.sub(r"[\(\[【（].*?[\)\]】）]", "", ingredient_name).strip()

    # 4. Clean up multiple spaces and trailing/leading junk
    ingredient_name = re.sub(r"\s+", " ", ingredient_name).strip()

    return Ingredient(
        raw=raw_line.strip(),
        representations=parsed_representations,
        name=ingredient_name or primary_text,
        modifier=modifier,
        optional=is_optional
    )