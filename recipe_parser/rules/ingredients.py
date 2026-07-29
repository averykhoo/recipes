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
from recipe_parser.rules.links import RE_MARKDOWN_LINK_OR_IMAGE
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
    # Length. A few ingredients are genuinely portioned by length rather than by mass:
    # "0.5-1 inch ginger" is how much ginger to use, and no weight in grams says the same
    # thing to a cook holding a rhizome. Which ingredients those are is decided by
    # LENGTH_MEASURED_FOODS below; for everything else a length states a size, not an
    # amount. The bare word "in" is deliberately absent - it is far more often the
    # preposition than the unit - and stays in DIMENSION_WORDS instead.
    "inch":       (UnitClass.LENGTH, ["inch", "inches", "\""]),
    "centimeter": (UnitClass.LENGTH, ["cm", "centimeter", "centimeters", "centimetre", "centimetres"]),
    "millimeter": (UnitClass.LENGTH, ["mm", "millimeter", "millimeters", "millimetre", "millimetres"]),
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

# The same alternation minus the length units. A number hyphenated to its unit is a
# compound adjective, and for a length that always describes an object rather than an
# amount: "6-pound pumpkin" is six pounds of pumpkin, but "9-inch pie shell" is not nine
# inches of pie shell. Only the non-length units may be reached across a hyphen.
NON_LENGTH_ALTERNATION = "|".join(
    re.escape(alias) for alias in unit_aliases_sorted
    if UNIT_LOOKUP[alias][1] != UnitClass.LENGTH
)

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
# The trailing unit is closed with a lookahead rather than \b for the same reason
# build_name_stripper is: one alias is the inch symbol, and \b never holds after a
# quotation mark, so '3"-4" ginger' could never match a rule that ended in \b.
RE_DUAL_UNIT_RANGE = re.compile(
    rf"^~?\s*(?P<low>{_SINGLE_NUM})\s*(?P<low_unit>{UNIT_ALTERNATION})\s*[-–—]\s*"
    rf"(?P<high>{_SINGLE_NUM})\s*(?P<high_unit>{UNIT_ALTERNATION})(?![A-Za-z0-9])",
    re.IGNORECASE
)

# Words that follow a number but describe a *dimension*, not a quantity of the ingredient.
# "5 percent milk" must not be read as 5 pieces of "percent milk".
#
# This list only ever gates the *bare count* fallback, which is reached solely when the
# word after the number is not a unit at all. Every length alias - "inch", "cm", "mm" and
# the rest - therefore belonged here only in appearance: they are in UNIT_LOOKUP, so the
# unit branch always claims them first and their entries here were unreachable. Deleting
# them left the corpus and the probe output byte-identical. What remains are the words
# that really are not units: "in" (deliberately kept out of UNIT_LOOKUP as it is far more
# often the preposition), the imperial lengths this parser does not measure in, and the
# non-length dimensions.
DIMENSION_WORDS = {
    "in", "m", "foot", "feet", "percent", "%", "degree", "degrees",
}

# If the text immediately after a number starts with one of these, it is not a count.
RE_NOT_A_COUNT = re.compile(r"^\s*[%\u00B0/\u00D7x\d]")

# Geometric or positional words that turn a length into a description of how something is
# shaped, cut or placed ("1 inch thick", "8 inches below the tongs", "1 cm dice"). These
# are checked on the word immediately after the unit, before anything else, so that
# "1 inch thick slices of ginger" stays a cut instruction rather than becoming an amount.
LENGTH_DESCRIBES_SHAPE = {
    "thick", "thickness", "thin", "deep", "depth", "wide", "width", "long", "length",
    "lengths", "tall", "high", "height", "square", "squares", "round", "rounds",
    "diameter", "across", "apart", "below", "above", "between", "from", "by", "x",
    "cube", "cubes", "chunk", "chunks", "strip", "strips", "ball", "balls",
    "log", "logs", "circle", "circles",
    "dice", "diced", "julienne", "matchstick", "matchsticks", "baton", "batons",
    "wedge", "wedges", "sliver", "slivers", "shred", "shreds",
}

# Foodstuffs that are genuinely portioned by length. This is an ALLOWlist, and it is the
# only route by which "<number> <length unit> <text>" is read as an amount.
#
# The dominant English reading of "N inch X" is a SIZE, not a quantity of X: "6 inch
# tortillas", '24" pizza base' and "9 inch pie shell" all say how big something is, and
# reading them as amounts invents measurements that no cook wrote. A denylist of shape
# words cannot separate the two, because the distinguishing information is not in the
# following word's grammar - it is in what the ingredient physically is. Worse, an
# open heuristic swallows typos with total confidence: "2 cm flour" is "2 c flour"
# mistyped and "500 mm milk" is "500 ml", and both used to parse as lengths.
#
# The genuine cases all share one shape: a long, roughly uniform thing the cook cuts to
# length, where grams are not the instruction the recipe is actually giving.
# "0.5-1 inch ginger" is how much ginger to use; "10 g" does not say the same thing to
# someone holding a rhizome. This is the entire reason length units exist in this parser.
#
# To extend: add the ingredient's own word in the singular. Plurals are handled
# automatically, and the word may be matched anywhere in the text following the unit, so
# "1 inch piece of ginger" and "2 inch knob of fresh ginger" both resolve through "ginger".
LENGTH_MEASURED_FOODS = {
    # Rhizomes and roots, cut across a length of the raw root.
    "ginger", "galangal", "turmeric", "horseradish", "wasabi", "lotus root",
    "burdock", "gobo", "daikon", "mooli",
    # Stalks and stems, trimmed to length.
    "lemongrass", "lemon grass", "leek", "rhubarb", "sugarcane", "sugar cane",
    "spring onion", "scallion", "green onion", "negi", "cucumber",
    # Barks, pods and quills, broken to length.
    "cinnamon", "cassia", "vanilla", "vanilla bean", "vanilla pod", "pandan",
    # Sea vegetables, cut from a sheet or a strap.
    "kombu", "konbu", "kelp", "dashima",
    # Long baked or cured goods, cut from a stick.
    "baguette",
}

# Longest first so that "lemon grass" wins over "leek" would-be prefixes during alternation,
# and an optional trailing "s" covers the plural of every entry above.
RE_LENGTH_MEASURED_FOOD = re.compile(
    r"\b(?:{})s?\b".format(
        "|".join(re.escape(food) for food in sorted(LENGTH_MEASURED_FOODS, key=len, reverse=True))
    ),
    re.IGNORECASE,
)

# A length can reach its ingredient through a portion noun: "1 inch piece of ginger" is an
# inch of ginger, spelled with an extra word in the middle. The noun says nothing the
# measurement has not already said, so it is dropped from the name once the length has
# been accepted as an amount.
RE_LENGTH_PORTION_HEAD = re.compile(
    r"^(?:piece|chunk|knob|length|segment|section|stick|nub|thumb|stub|bit|hunk)s?"
    r"\s+(?:of\s+)?",
    re.IGNORECASE,
)

# "2 cans (15 oz each) tomatoes" - a count of containers plus the capacity of each.
# Trailing text after the bracket is allowed; the ingredient name is extracted separately.
RE_NESTED_CONTAINER = re.compile(
    r"^(?P<mult>\d+)\s+(?P<container>\w+)\s*"
    r"(?P<bracket>[\(\[【（](?P<cap>[^)\]】）]+?)\s*(?:each|ea)?[\)\]】）])",
    re.IGNORECASE
)

# A leading parenthetical/bracketed aside at the very start of an ingredient line.
RE_LEADING_PAREN = re.compile(r"^[\(\[\u3010\uFF08]\s*(?P<inner>[^)\]\u3011\uFF09]*?)\s*[\)\]\u3011\uFF09]\s*")

# A Markdown link or image: "[bolognese](ragu-alla-bolognese.md)". The link text is the
# ingredient's own words and the target is a cross-reference to another recipe, so the
# two are separated rather than either being discarded. Shared with rules/links.py rather
# than spelled a second time here: the local copy could not span a parenthesised URL, so
# "[custard](https://en.wikipedia.org/wiki/Custard_(dessert))" lost the tail of its target
# and gained a stray ")" on the end of its name.
RE_MARKDOWN_LINK = RE_MARKDOWN_LINK_OR_IMAGE

# An optional link title trailing the target: "(file.md \"My Title\")".
RE_LINK_TITLE = re.compile(r"\s+(?:\"[^\"]*\"|'[^']*')$")

# A clause that prepares or qualifies a linked ingredient rather than continuing its name.
# "[mornay](../bechamel.md) using parmesan" is mornay, prepared a particular way, whereas
# "[Bird's Custard](...) powder" is simply the name of the thing spelled across the link.
RE_LINK_CLAUSE = re.compile(
    r"^(?:using|made|prepared|seasoned|flavou?red|thinned|mixed|blended|folded|topped|"
    r"with|without|plus)\b",
    re.IGNORECASE
)

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
#
# The two branches differ only in which units may follow a hyphen: a length hyphenated to
# its number sizes an object ("9-inch pie shells") and must be left in the name, so the
# stripper never reaches across a hyphen to one. The unit is closed with a lookahead
# rather than \b because one alias is the inch symbol, after which \b never holds.
_UNIT_HEAD = rf"(?:{_QUALIFIER}\s+)?"


def build_name_stripper(alternation: str) -> re.Pattern:
    """Compiles the head-stripping rule over a given set of unit aliases."""
    unit_suffix = (
        rf"(?:\s*{_UNIT_HEAD}(?:{alternation})(?![A-Za-z0-9])\.?\s*"
        rf"|[-–—]\s*{_UNIT_HEAD}(?:{NON_LENGTH_ALTERNATION})(?![A-Za-z0-9])\.?\s*)?"
    )
    return re.compile(
        rf"^\s*{_QUALIFIER_PREFIX}~?\s*"
        rf"(?:\d+\s*[x×]\s+)?"
        rf"{_SINGLE_NUM}{unit_suffix}"
        rf"(?:{RANGE_SEPARATOR}{_SINGLE_NUM}{unit_suffix})?"
        rf"(?:of\s+)?",
        re.IGNORECASE
    )


RE_NAME_STRIP = build_name_stripper(UNIT_ALTERNATION)

# The same rule with the length units withheld. A length is only sometimes an amount, so
# the name stripper must follow whatever the measurement parser decided: "0.5-1 inch
# ginger" leaves "ginger", but "8 inches below the tongs" carries no amount and the word
# "inches" belongs to the text that remains.
RE_NAME_STRIP_NO_LENGTH = build_name_stripper(NON_LENGTH_ALTERNATION)


def length_reads_as_an_amount(hyphenated: bool, text_after_unit: str) -> bool:
    """
    Decides whether "<number> <length unit> <rest>" measures out the ingredient or merely
    describes something's size.

    The default answer is no. In English "N inch X" overwhelmingly gives the size of X
    rather than an amount of it, so a length counts as an amount only when the text after
    the unit names something on LENGTH_MEASURED_FOODS - an ingredient people really do
    portion by length. "0.5-1 inch ginger" is how much ginger to buy; "6 inch tortillas"
    is how wide the tortillas are.

    Three things rule it out before the ingredient is even consulted: the number being
    hyphenated onto the unit as a compound adjective ("9-inch pie shells"), nothing
    following the unit at all (a length with no ingredient after it measures nothing), and
    a geometric or positional word coming next ("1 inch thick slices of ginger" describes
    the cut, not the amount, even though ginger is on the list).
    """
    if hyphenated:
        return False

    remainder = text_after_unit.strip()
    if not remainder:
        return False

    next_word = remainder.split(" ", 1)[0].strip(".,;:").lower()
    if next_word in LENGTH_DESCRIBES_SHAPE:
        return False

    return RE_LENGTH_MEASURED_FOOD.search(remainder) is not None


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
        # A pack multiplier may never multiply a length. "2 x 20 cm cake tins" is two tins
        # that are 20 cm each, not 40 cm of tin, and the same is true of every "<count> x
        # <size> <object>" line - the length sizes one item rather than totalling them.
        # This is also the only place the dimension guard could be evaded: the recursive
        # call starts a fresh parse in which the number is no longer hyphenated to its
        # unit, so "2 x 9 inch pans" looked like a clean "<n> <length> <noun>" run.
        if inner is not None and inner.unit_class == UnitClass.LENGTH:
            inner = None
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

        # A length spelled on both ends of a range is still only sometimes an amount, and
        # this branch used to return before the guard could ever see it: "9 inch - 10 inch
        # pie shells" became nine-and-a-half inches of pie shell. Falling through when the
        # guard says no leaves the ordinary rules to read the line.
        length_is_a_dimension = (
            low_class == UnitClass.LENGTH
            and not length_reads_as_an_amount(False, raw_text[dual_match.end():])
        )

        units_agree = low_canonical == high_canonical
        if units_agree and not length_is_a_dimension and low_val is not None and high_val is not None:
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
    # a letter is a compound adjective, not a range. Whether the unit arrived that way
    # matters for lengths, which read as a size rather than an amount when they do.
    hyphenated_unit = False
    if re.match(r"^[-–—]\s*[a-z]", rest, re.IGNORECASE):
        rest = rest[1:].strip()
        hyphenated_unit = True

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

        # A length only measures out an ingredient in some grammatical positions; in the
        # rest it is sizing an object and there is no amount on the line to extract.
        if unit_class == UnitClass.LENGTH:
            text_after_unit = rest.split(" ", 1)[1] if " " in rest else ""
            if not length_reads_as_an_amount(hyphenated_unit, text_after_unit):
                return None

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


def parse_ingredient_line(raw_line: str, force_optional: bool = False) -> Optional[Ingredient]:
    """
    Transforms raw lists into Pydantic models. Resolves alternatives
    nested inside brackets or parentheses.

    `force_optional` marks the ingredient optional regardless of what the line itself
    says, for children of an "optional:" group header that carries the marker for them.
    """
    cleaned_line = strip_html_and_markdown_comments(raw_line).strip()
    if not cleaned_line:
        return None

    # A wrapped list item arrives with embedded newlines. None of the quantity patterns
    # are multi-line, so an ingredient that wraps would otherwise lose its measurement
    # entirely. Collapse to a single logical line before anything else looks at it.
    cleaned_line = re.sub(r"\s+", " ", cleaned_line).strip()

    cleaned_line = re.sub(r"^[\*\-+]\s+", "", cleaned_line)

    # Markdown links resolve to their link text before anything else reads the line.
    # RE_LEADING_PAREN treats "[" as the opening of an aside, so a line that *starts* with
    # a link ("[bolognese](ragu-alla-bolognese.md)") would otherwise have its link text
    # taken for an annotation and its URL left behind as the ingredient name.
    link_target = None
    link_clause = None
    clause_was_optional = False

    leading_link = RE_MARKDOWN_LINK.match(cleaned_line)
    if leading_link and not leading_link.group("image"):
        trailing_text = cleaned_line[leading_link.end():].strip()

        # An "optional" marker at the end of the line belongs to the ingredient, not to
        # the clause. It is lifted off first because taking the clause truncates the line
        # to the link, which would otherwise carry the marker away with the rest of the
        # tail and leave a required ingredient where the recipe wrote an optional one.
        clause_optional = RE_TRAILING_OPTIONAL.search(trailing_text)
        if clause_optional:
            trailing_text = trailing_text[:clause_optional.start()].strip().rstrip(",;-").strip()

        if RE_LINK_CLAUSE.match(trailing_text):
            # "[mornay](../bechamel.md) using parmesan": the clause says how the linked
            # ingredient is prepared, so it is a modifier rather than part of the name.
            link_clause = trailing_text
            clause_was_optional = bool(clause_optional)
            cleaned_line = cleaned_line[:leading_link.end()]

    def unwrap_markdown_link(match) -> str:
        nonlocal link_target
        if match.group("image"):
            # An image is decoration; its alt text is not the name of an ingredient.
            return ""
        if link_target is None:
            link_target = RE_LINK_TITLE.sub("", match.group("target")).strip().strip("<>")
        return match.group("text")

    cleaned_line = RE_MARKDOWN_LINK.sub(unwrap_markdown_link, cleaned_line).strip()

    # Check for optional flags
    is_optional = force_optional or clause_was_optional
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
    # A length word is only removed when it was read as an amount; where it merely sizes
    # something ("8 inches below the tongs") it is part of what the line says, not a unit.
    measured_a_length = any(
        term.unit_class == UnitClass.LENGTH for term in primary_rep.terms
    )
    stripper = RE_NAME_STRIP if measured_a_length else RE_NAME_STRIP_NO_LENGTH
    stripped_name = stripper.sub("", ingredient_name).strip()
    # If stripping the number leaves a dangling "%", "-" or inch mark, the number was part
    # of the name ("70% dark chocolate", "9-inch pie shell", '24" pizza base') rather than
    # a quantity of it.
    if stripped_name and not re.match(r"^[%°\-–—\"]", stripped_name):
        ingredient_name = stripped_name

    # 1b. A length that was read as an amount often reaches its ingredient through a
    #     portion noun: "1 inch piece of ginger" leaves "piece of ginger" behind. The noun
    #     repeats what the measurement already says, so it goes.
    if measured_a_length:
        ingredient_name = RE_LENGTH_PORTION_HEAD.sub("", ingredient_name).strip()

    # 2. Strip any remaining descriptive brackets or parentheticals from the name. Markdown
    #    links are already gone: they were resolved to their link text at the top of this
    #    function, before any rule that could mistake a link for a bracketed aside.
    ingredient_name = re.sub(r"[\(\[【（].*?[\)\]】）]", "", ingredient_name).strip()

    # 3. Clean up multiple spaces and trailing/leading junk. Removing a parenthetical can
    #    strand the punctuation that introduced it, e.g. "Custard Powder (...):" -> "... :".
    ingredient_name = re.sub(r"\s+", " ", ingredient_name).strip()
    ingredient_name = ingredient_name.strip(" ,;:-–—").strip()

    # A comma inside the link text produces a modifier of its own ("[cream, whipped](x.md)
    # with sugar"), and the clause after the link lives nowhere else once the line has been
    # truncated to the link. Keeping only one of the two silently deleted the other, so
    # both are kept, in the order the line wrote them.
    modifier_parts = [part for part in (modifier, link_clause) if part]
    combined_modifier = ", ".join(modifier_parts) or None

    return Ingredient(
        raw=raw_line.strip(),
        representations=parsed_representations,
        name=ingredient_name or primary_text,
        modifier=combined_modifier,
        optional=is_optional,
        annotation=annotation,
        link=link_target
    )
