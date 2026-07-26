# recipe_parser/rules/ingredients.py
"""
Rule processor for parsing individual ingredient lines, extracting
canonical units, alternative conversions, and piece-nested container capacities.
"""

import re
from typing import Optional

from recipe_parser.models.schemas import Ingredient
from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import QuantityRepresentation
from recipe_parser.models.schemas import UnitClass
from recipe_parser.utils.conversions import HEAPED_MULTIPLIER
from recipe_parser.utils.numeric import RANGE_SEPARATOR
from recipe_parser.utils.numeric import VULGAR_FRACTION_CLASS
from recipe_parser.utils.numeric import parse_quantity_bounds
from recipe_parser.utils.numeric import parse_single_quantity
from recipe_parser.utils.sanitizer import strip_html_and_markdown_comments

# Unified canonical unit maps (mapping variations to full proper words)
UNIT_CLASSIFICATIONS = {
    # Volume
    "tablespoon": (UnitClass.VOLUME, ["tbsp", "tbs", "tbsps", "tbsp.", "tablespoon", "tablespoons", "tbs"]),
    "teaspoon":   (UnitClass.VOLUME, ["tsp", "tsps", "tsp.", "teaspoon", "teaspoons"]),
    "milliliter": (UnitClass.VOLUME, ["ml", "milliliter", "milliliters", "millilitre", "millilitres"]),
    "liter":      (UnitClass.VOLUME, ["l", "liter", "liters", "litre", "litres"]),
    "cup":        (UnitClass.VOLUME, ["cup", "cups", "c"]),
    # Weight
    "gram":       (UnitClass.WEIGHT, ["g", "gram", "grams"]),
    "kilogram":   (UnitClass.WEIGHT, ["kg", "kilogram", "kilograms"]),
    "ounce":      (UnitClass.WEIGHT, ["oz", "ounce", "ounces"]),
    "pound":      (UnitClass.WEIGHT, ["lb", "lbs", "pound", "pounds"]),
    # Piece
    "whole":      (UnitClass.PIECE, ["whole"]),
    "clove":      (UnitClass.PIECE, ["clove", "cloves"]),
    "slice":      (UnitClass.PIECE, ["slice", "slices"]),
    "block":      (UnitClass.PIECE, ["block", "blocks"]),
    "can":        (UnitClass.PIECE, ["can", "cans"]),
    "stick":      (UnitClass.PIECE, ["stick", "sticks"]),
    "envelope":   (UnitClass.PIECE, ["envelope", "envelopes", "sheet", "sheets"]),
    "bunch":      (UnitClass.PIECE, ["bunch", "bunches"]),
    "head":       (UnitClass.PIECE, ["head", "heads"]),
    "piece":      (UnitClass.PIECE, ["piece", "pieces", "pc", "pcs"]),
}

# Reverse mapping for fast regex scanning
UNIT_LOOKUP = {}
for canonical, (u_class, aliases) in UNIT_CLASSIFICATIONS.items():
    for alias in aliases:
        UNIT_LOOKUP[alias.lower()] = (canonical, u_class)

# Unit aliases, longest first so that "tablespoons" wins over "tbs" during alternation.
unit_aliases_sorted = sorted(list(UNIT_LOOKUP.keys()), key=len, reverse=True)
escaped_aliases = [re.escape(alias) for alias in unit_aliases_sorted]
UNIT_ALTERNATION = "|".join(escaped_aliases)

# --- Leading quantity grammar -------------------------------------------------
# Built up from named pieces so the range handling is legible. The previous version
# required whitespace around the hyphen, which silently dropped the quantity from
# every "1-2 tsp" style line (the dominant range style in this corpus).
_DECIMAL = r"\d+(?:\.\d+)?"
_FRACTION = r"\d+\s*/\s*\d+"
_VULGAR = VULGAR_FRACTION_CLASS
_MIXED = rf"\d+\s*(?:{_FRACTION}|{_VULGAR})"  # "1 1/2", "1\u00BD", "1 \u00BD"

# Order matters: longest/most specific alternative first.
_SINGLE_NUM = rf"(?:{_MIXED}|{_FRACTION}|{_VULGAR}|{_DECIMAL})"

# A quantity is one number, optionally followed by a range separator and a second number.
_QUANTITY = rf"(?:{_SINGLE_NUM}(?:{RANGE_SEPARATOR}{_SINGLE_NUM})?)"

# Hedge words that precede a quantity without changing it. "About 1 to 1½ cups" is a
# quantity; the hedge only tells the cook the number is not exact.
# Deliberately excludes size adjectives such as "large" or "small": those describe the
# ingredient and belong to its name, whereas these only hedge the number.
_QUALIFIER = (
    r"(?:about|approx|approx\.|approximately|roughly|around|nearly|"
    r"scant|heaping|heaped|heaped-up|generous|rounded|level|full)"
)
_QUALIFIER_PREFIX = rf"(?:(?:a\s+)?{_QUALIFIER}\s+)*"

# The same hedge can also sit between the number and the unit: "1 heaped Tbsp butter".
RE_QUALIFIER_AFTER_NUMBER = re.compile(rf"^{_QUALIFIER}\s+", re.IGNORECASE)

# Hedges that describe how the spoon was FILLED rather than how loosely the number was
# meant. These denote a genuinely larger quantity than a level spoon.
RE_HEAPING_WORD = re.compile(r"\b(?:heaping|heaped|heaped-up|rounded)\b", re.IGNORECASE)

# Matches leading floats, fractions, vulgar fractions, mixed numbers and ranges.
# A leading "~" (approximately) or hedge word is consumed but not captured.
RE_LEADING_NUM = re.compile(
    rf"^(?P<qualifier>{_QUALIFIER_PREFIX})~?\s*(?P<val>{_QUANTITY})\s*(?P<rest>.+)?$",
    re.UNICODE | re.IGNORECASE
)

# "2x 300g", "3 × 400 ml" - a pack multiplier in front of a real measurement.
RE_PACK_MULTIPLIER = re.compile(r"^~?\s*(?P<mult>\d+)\s*[x×]\s+(?P<remainder>.+)$", re.IGNORECASE)

# A range where the unit is repeated on both ends: "500g-750g", "100 g - 200 g".
RE_DUAL_UNIT_RANGE = re.compile(
    rf"^~?\s*(?P<low>{_SINGLE_NUM})\s*(?P<low_unit>{UNIT_ALTERNATION})\s*[-–—]\s*"
    rf"(?P<high>{_SINGLE_NUM})\s*(?P<high_unit>{UNIT_ALTERNATION})\b",
    re.IGNORECASE
)

# Words that follow a number but describe a *dimension*, not a quantity of the ingredient.
# "9-inch pie shells" must not be read as 9 pieces of "inch pie shells".
DIMENSION_WORDS = {
    "inch", "inches", "in", "cm", "mm", "m", "centimeter", "centimeters",
    "centimetre", "centimetres", "millimeter", "millimeters", "foot", "feet",
    "percent", "%", "degree", "degrees",
}

# If the text immediately after a number starts with one of these, it is not a count.
RE_NOT_A_COUNT = re.compile(r"^\s*[%\u00B0/\u00D7x\d]")

# "2 cans (15 oz each) tomatoes" - a count of containers plus the capacity of each.
# Trailing text after the bracket is allowed; the ingredient name is extracted separately.
RE_NESTED_CONTAINER = re.compile(
    r"^(?P<mult>\d+)\s+(?P<container>\w+)\s*"
    r"(?P<bracket>[\(\[【（](?P<cap>[^)\]】）]+?)\s*(?:each|ea)?[\)\]】）])",
    re.IGNORECASE
)

# A leading parenthetical/bracketed aside at the very start of an ingredient line.
RE_LEADING_PAREN = re.compile(r"^[\(\[\u3010\uFF08]\s*(?P<inner>[^)\]\u3011\uFF09]*?)\s*[\)\]\u3011\uFF09]\s*")

# Marks a measurement as applying to each item rather than to the whole quantity.
RE_PER_UNIT = re.compile(r"\b(?:each|ea|apiece|per)\b\.?\s*$", re.IGNORECASE)

# The word "optional", tolerating a trailing question mark.
RE_OPTIONAL_WORD = re.compile(r"optional\??", re.IGNORECASE)

# Trailing optional marker: "(optional)", ", optional", " - optional"
RE_TRAILING_OPTIONAL = re.compile(r"\s*[,;(\-\u2013\u2014]?\s*\(?\s*optional\s*\)?\s*$", re.IGNORECASE)

# Strips "<quantity> [unit] [of]" from the head of an ingredient line so that only the
# name survives. Every part except the first number is optional, so this single rule
# covers bare counts ("2 lemons"), hyphenated units ("6-pound pumpkin"), pack
# multipliers ("2x 300g spinach") and ranges with the unit on either or both ends
# ("1-2 tsp", "500g-750g").
_UNIT_SUFFIX = rf"(?:[-–—]?\s*(?:{_QUALIFIER}\s+)?(?:{UNIT_ALTERNATION})\b\.?\s*)?"
RE_NAME_STRIP = re.compile(
    rf"^\s*{_QUALIFIER_PREFIX}~?\s*"
    rf"(?:\d+\s*[x×]\s+)?"
    rf"{_SINGLE_NUM}{_UNIT_SUFFIX}"
    rf"(?:{RANGE_SEPARATOR}{_SINGLE_NUM}{_UNIT_SUFFIX})?"
    rf"(?:of\s+)?",
    re.IGNORECASE
)


def parse_single_term(term_text: str, allow_bare_count: bool = False) -> Optional[Measurement]:
    """
    Extracts a single structured measurement from a trimmed string run (e.g. '1/2 cup').

    When `allow_bare_count` is set, a leading number with no recognised unit word is
    read as a count of whole pieces ("2 large lemons" -> 2 pieces). This is only safe
    at the top level of a representation, never for a nested container capacity, so it
    is opt-in.
    """
    raw_text = term_text.strip()

    # "2x 300g baby spinach" - a pack count in front of a real measurement.
    pack_match = RE_PACK_MULTIPLIER.match(raw_text)
    if pack_match:
        inner = parse_single_term(pack_match.group("remainder"), allow_bare_count=False)
        if inner is not None:
            multiplier = float(pack_match.group("mult"))
            return Measurement(
                value=inner.value * multiplier,
                value_min=inner.value_min * multiplier if inner.value_min is not None else None,
                value_max=inner.value_max * multiplier if inner.value_max is not None else None,
                unit=inner.unit,
                unit_class=inner.unit_class,
            )

    # "500g-750g tomatoes" - the unit is repeated on both ends of the range.
    dual_match = RE_DUAL_UNIT_RANGE.match(raw_text)
    if dual_match:
        low_canonical, low_class = UNIT_LOOKUP[dual_match.group("low_unit").lower()]
        high_canonical, _ = UNIT_LOOKUP[dual_match.group("high_unit").lower()]
        low_val = parse_single_quantity(dual_match.group("low"))
        high_val = parse_single_quantity(dual_match.group("high"))
        if low_canonical == high_canonical and low_val is not None and high_val is not None:
            return Measurement(
                value=(low_val + high_val) / 2.0,
                value_min=min(low_val, high_val),
                value_max=max(low_val, high_val),
                unit=low_canonical,
                unit_class=low_class,
            )

    match = RE_LEADING_NUM.match(raw_text)
    if not match:
        return None

    raw_val = match.group("val")
    rest = (match.group("rest") or "").strip()

    # "6-pound pumpkin" hyphenates the number to its unit. The range branch above has
    # already consumed any "1-2" style hyphen, so a leftover leading hyphen followed by
    # a letter is a compound adjective, not a range.
    if re.match(r"^[-–—]\s*[a-z]", rest, re.IGNORECASE):
        rest = rest[1:].strip()

    # "1 heaped Tbsp butter" hedges between the number and the unit. Without this the
    # unit is never seen and the line collapses to a bare count of 1.
    qualifier_text = match.group("qualifier") or ""
    mid_qualifier = RE_QUALIFIER_AFTER_NUMBER.match(rest)
    if mid_qualifier:
        qualifier_text += " " + mid_qualifier.group(0)
        rest = rest[mid_qualifier.end():].strip()

    fill_state = "heaped" if RE_HEAPING_WORD.search(qualifier_text) else None

    parsed_val = parse_single_quantity(raw_val)
    if parsed_val is None:
        return None

    bounds = parse_quantity_bounds(raw_val)
    value_min, value_max = bounds if bounds else (None, None)

    first_word = rest.split(" ", 1)[0].rstrip(".").strip().lower() if rest else ""

    if first_word in UNIT_LOOKUP:
        canonical_name, unit_class = UNIT_LOOKUP[first_word]

        # A heaped spoon holds more than a level one, by an amount nobody has ever
        # standardised. Widen the interval rather than inventing a point value.
        if fill_state == "heaped" and unit_class == UnitClass.VOLUME:
            low_multiplier, high_multiplier = HEAPED_MULTIPLIER
            base_min = value_min if value_min is not None else parsed_val
            base_max = value_max if value_max is not None else parsed_val
            value_min = base_min * low_multiplier
            value_max = base_max * high_multiplier
            parsed_val = (value_min + value_max) / 2.0
        else:
            fill_state = None

        return Measurement(
            value=parsed_val,
            value_min=value_min,
            value_max=value_max,
            unit=canonical_name,
            unit_class=unit_class,
            fill_state=fill_state,
        )

    if not allow_bare_count:
        return None

    # Bare count inference. Reject anything that looks like a dimension, a percentage,
    # or another number rather than a countable noun.
    if not rest:
        return None
    if RE_NOT_A_COUNT.match(rest):
        return None
    if first_word in DIMENSION_WORDS:
        return None
    # The number must be separated from what follows, otherwise "70%" style runs slip in.
    # Measured from the end of the captured quantity, so a leading hedge word or "~"
    # does not defeat the check.
    trailing = raw_text[match.end("val"):]
    if trailing and not trailing[0].isspace():
        return None

    return Measurement(
        value=parsed_val,
        value_min=value_min,
        value_max=value_max,
        unit="count",
        unit_class=UnitClass.PIECE,
        implicit_unit=True,
    )


def parse_representation(text_run: str, allow_bare_count: bool = False) -> QuantityRepresentation:
    """
    Parses additive terms inside a single representation run (e.g. '0.5 cup + 1 teaspoon').

    `allow_bare_count` is forwarded to the standard-term parser so that unitless counts
    are only inferred for the primary representation of an ingredient line.
    """
    representation = QuantityRepresentation(raw_text=text_run.strip())

    # Split on standard addition operators
    raw_terms = re.split(r"\s+(?:\+|\bplus\b|\band\b)\s+", text_run, flags=re.IGNORECASE)

    for raw_term in raw_terms:
        # Check if the term represents a piece-nested capacity: e.g. "2 cans (15 oz each)"
        nested_match = RE_NESTED_CONTAINER.match(raw_term.strip())
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
        meas = parse_single_term(raw_term, allow_bare_count=allow_bare_count)
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

    # A wrapped list item arrives with embedded newlines. None of the quantity patterns
    # are multi-line, so an ingredient that wraps would otherwise lose its measurement
    # entirely. Collapse to a single logical line before anything else looks at it.
    cleaned_line = re.sub(r"\s+", " ", cleaned_line).strip()

    cleaned_line = re.sub(r"^[\*\-+]\s+", "", cleaned_line)

    # Check for optional flags
    is_optional = False
    annotation = None

    if cleaned_line.lower().startswith("optional:"):
        is_optional = True
        cleaned_line = cleaned_line[len("optional:"):].strip()

    # Trailing optional marker: "(optional)", ", optional", "- optional"
    trailing_optional = RE_TRAILING_OPTIONAL.search(cleaned_line)
    if trailing_optional:
        is_optional = True
        cleaned_line = cleaned_line[:trailing_optional.start()].strip().rstrip(",;-").strip()

    # Leading parenthetical. Either an optional marker, or an authorial aside such as
    # "(erin's mile-high) 1 Tbsp grand marnier" which would otherwise block the quantity
    # parser from ever seeing the leading number.
    leading_paren = RE_LEADING_PAREN.match(cleaned_line)
    if leading_paren:
        inner = leading_paren.group("inner").strip()
        remainder = cleaned_line[leading_paren.end():].strip()
        if RE_OPTIONAL_WORD.fullmatch(inner):
            is_optional = True
            cleaned_line = remainder
        elif remainder and not RE_LEADING_NUM.match(inner):
            # Keep the aside rather than discarding it, and unblock the remainder.
            annotation = inner
            if RE_OPTIONAL_WORD.match(inner):
                is_optional = True
            cleaned_line = remainder

    # Extract alternative representations inside parentheses or brackets
    representations_text = []
    main_and_modifier = cleaned_line

    # Matches brackets like (65g) or 【118 mL】
    bracket_matches = list(re.finditer(r"[\(\[【（](?P<inner>.+?)[\)\]】）]", cleaned_line))

    # A bracket that states the capacity of a preceding container ("2 cans (15 oz each)")
    # is not an alternative measurement of the whole line - it nests inside the count.
    # Leave it in place so the representation parser can build the nested measurement.
    container_capacity = RE_NESTED_CONTAINER.match(cleaned_line)
    container_bracket_span = None
    if container_capacity:
        container_word = container_capacity.group("container").lower().rstrip("s")
        if container_word in UNIT_LOOKUP and UNIT_LOOKUP[container_word][1] == UnitClass.PIECE:
            container_bracket_span = container_capacity.span("bracket")

    # We only treat bracketed runs as alternative units if they begin with a digit
    for match in bracket_matches:
        inner_text = match.group("inner").strip()
        if container_bracket_span is not None and match.span() == container_bracket_span:
            continue
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

    primary_rep = parse_representation(primary_text, allow_bare_count=True)

    parsed_representations = [primary_rep]
    for alt_text in representations_text:
        alt_rep = parse_representation(alt_text)
        if alt_rep.terms:
            # "(60g each)" states the size of one item, not the total for all of them.
            alt_rep.per_unit = bool(RE_PER_UNIT.search(alt_text))
            parsed_representations.append(alt_rep)

    # Extract the true ingredient name by removing the leading quantity and unit.
    ingredient_name = primary_text

    # Strip "<quantity> [unit] [of]" from the front. This covers unitless counts
    # ("2 large lemons" -> "large lemons") as well as ranges ("1-2 tsp butter" -> "butter").
    stripped_name = RE_NAME_STRIP.sub("", ingredient_name).strip()
    # If stripping the number leaves a dangling "%" or "-", the number was part of the
    # name ("70% dark chocolate", "9-inch pie shell") rather than a quantity of it.
    if stripped_name and not re.match(r"^[%°\-–—]", stripped_name):
        ingredient_name = stripped_name

    # 2. Strip Markdown link brackets: [self-raising flour](...) -> self-raising flour
    ingredient_name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", ingredient_name)

    # 3. Strip any remaining descriptive brackets or parentheticals from the name
    ingredient_name = re.sub(r"[\(\[【（].*?[\)\]】）]", "", ingredient_name).strip()

    # 4. Clean up multiple spaces and trailing/leading junk. Removing a parenthetical can
    #    strand the punctuation that introduced it, e.g. "Custard Powder (...):" -> "... :".
    ingredient_name = re.sub(r"\s+", " ", ingredient_name).strip()
    ingredient_name = ingredient_name.strip(" ,;:-–—").strip()

    return Ingredient(
        raw=raw_line.strip(),
        representations=parsed_representations,
        name=ingredient_name or primary_text,
        modifier=modifier,
        optional=is_optional,
        annotation=annotation
    )
