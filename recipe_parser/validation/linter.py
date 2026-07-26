# recipe_parser/validation/linter.py
"""
Linter module that executes mathematical conversion checkers, boundary audits,
and structural constraints on the parsed DOM block tree.
"""

import re
from typing import List

from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import Recipe
from recipe_parser.models.schemas import UnitClass
from recipe_parser.utils.conversions import check_temperature_discrepancy
from recipe_parser.utils.conversions import get_normalization_details
from recipe_parser.utils.conversions import normalize_measurement_to_grams
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity

MASS_TOLERANCE_PERCENT = 0.10  # 10% discrepancy allowed
TEMP_TOLERANCE_C = 5.0  # 5°C discrepancy allowed


def _measurement_at(measurement: Measurement, value: float) -> Measurement:
    """Clones a measurement at a specific value, keeping unit and any nested capacity."""
    return Measurement(
        value=value,
        unit=measurement.unit,
        unit_class=measurement.unit_class,
        nested_capacity=measurement.nested_capacity,
    )


def representation_gram_bounds(representation, ingredient_name: str):
    """
    Converts a representation to the closed gram interval [low, high] it denotes.

    A scalar collapses to a zero-width interval. A range like "1-2 tsp" keeps its width,
    which matters: comparing the midpoints of two ranges invents precision that the
    recipe never claimed, and reports disagreements between quantities that overlap
    perfectly well.

    Returns None when no term could be converted to a mass.
    """
    low_total = 0.0
    high_total = 0.0
    converted_any = False

    for term in representation.terms:
        low_value = term.value_min if term.value_min is not None else term.value
        high_value = term.value_max if term.value_max is not None else term.value

        # Two sources of width compose here: the range the recipe wrote ("1-2 onions")
        # and the range inherent to the conversion itself (an onion is 70-285 g).
        low_details = get_normalization_details(_measurement_at(term, low_value), ingredient_name)
        high_details = get_normalization_details(_measurement_at(term, high_value), ingredient_name)

        low_grams = low_details.get("value_min", low_details.get("value"))
        high_grams = high_details.get("value_max", high_details.get("value"))

        if low_grams is None or high_grams is None or high_grams <= 0:
            continue

        converted_any = True
        low_total += min(low_grams, high_grams)
        high_total += max(low_grams, high_grams)

    if not converted_any or high_total <= 0:
        return None
    return (low_total, high_total)


def interval_discrepancy(first, second) -> float:
    """
    Relative disagreement between two gram intervals.

    Zero when they overlap - two quantities that share any possible value are not in
    conflict. Otherwise the size of the gap between them, relative to the larger
    quantity involved.
    """
    low_a, high_a = first
    low_b, high_b = second

    gap = max(low_a - high_b, low_b - high_a)
    if gap <= 0:
        return 0.0

    scale = max(high_a, high_b)
    if scale <= 0:
        return 0.0
    return gap / scale


def format_interval(bounds) -> str:
    """Renders a gram interval, collapsing zero-width intervals to a single figure."""
    low, high = bounds
    if abs(high - low) < 0.05:
        return f"{low:.1f}g"
    return f"{low:.1f}-{high:.1f}g"


def lint_recipe_document(recipe: Recipe) -> List[Diagnostic]:
    """
    Executes structural and mathematical conversions quality checks on the recipe tree.
    """
    lint_warnings: List[Diagnostic] = []

    for block in recipe.blocks:
        if block.block_type == BlockType.LIST:
            # The section is resolved once at build time and recorded on the block itself.
            # Re-deriving it here from "closest preceding heading" used to misclassify any
            # list sitting under an H3 sub-heading, silently skipping its ingredient checks.
            is_ingredients = (block.section_type == "ingredients")

            if is_ingredients:
                for item in block.items:
                    if not item.parsed_ingredient:
                        continue

                    ing = item.parsed_ingredient

                    # Enforce only AMOUNT classes under ingredients
                    for rep in ing.representations:
                        for term in rep.terms:
                            if term.unit_class in (UnitClass.DURATION, UnitClass.TEMPERATURE):
                                lint_warnings.append(Diagnostic(
                                    severity=Severity.ERROR,
                                    code=Code.INVALID_UNIT_CLASS,
                                    recipe=recipe.title,
                                    context=ing.raw,
                                    message=(
                                        f"Ingredient '{ing.name}' uses invalid unit class "
                                        f"'{term.unit_class.value}' (unit: '{term.unit}')."
                                    ),
                                ))
                                continue

                            # Enforce Nesting constraints
                            if term.nested_capacity:
                                if term.unit_class != UnitClass.PIECE:
                                    lint_warnings.append(Diagnostic(
                                        severity=Severity.ERROR,
                                        code=Code.INVALID_NESTING,
                                        recipe=recipe.title,
                                        context=ing.raw,
                                        message=(
                                            f"Nesting capacity is only allowed inside PIECE containers "
                                            f"(found inside '{term.unit_class.value}')."
                                        ),
                                    ))
                                if term.nested_capacity.unit_class not in (UnitClass.VOLUME, UnitClass.WEIGHT):
                                    lint_warnings.append(Diagnostic(
                                        severity=Severity.ERROR,
                                        code=Code.INVALID_NESTING,
                                        recipe=recipe.title,
                                        context=ing.raw,
                                        message=(
                                            f"Nested capacity must be VOLUME or WEIGHT "
                                            f"(found: '{term.nested_capacity.unit_class.value}')."
                                        ),
                                    ))

                        # Enforce conversion sanity checking
                        if len(ing.representations) >= 2:
                            rep_primary = ing.representations[0]
                            rep_alt = ing.representations[1]

                            bounds_primary = representation_gram_bounds(rep_primary, ing.name)
                            bounds_alt = representation_gram_bounds(rep_alt, ing.name)

                            # "4 large eggs (60g each)" states 60g per egg, so the
                            # alternative has to be scaled by the count before the two
                            # can be compared at all.
                            per_unit_applied = False
                            if bounds_alt and bounds_primary:
                                item_count = sum(
                                    t.value for t in rep_primary.terms
                                    if t.unit_class == UnitClass.PIECE
                                )
                                scaled = None
                                if item_count > 1:
                                    scaled = (bounds_alt[0] * item_count, bounds_alt[1] * item_count)

                                if rep_alt.per_unit and scaled:
                                    bounds_alt = scaled
                                    per_unit_applied = True
                                elif scaled and interval_discrepancy(bounds_primary, bounds_alt) > 0 \
                                        and interval_discrepancy(bounds_primary, scaled) == 0:
                                    # "3 large (60g) eggs" omits the word "each". Read as a
                                    # total it is impossible; read as a per-item size it is
                                    # consistent, so take the reading that can be true.
                                    bounds_alt = scaled
                                    per_unit_applied = True

                            if bounds_primary and bounds_alt:
                                discrepancy = interval_discrepancy(bounds_primary, bounds_alt)
                                if discrepancy > MASS_TOLERANCE_PERCENT:
                                    primary_details_list = []
                                    for t in rep_primary.terms:
                                        det = get_normalization_details(t, ing.name)
                                        primary_details_list.append(f"{t.value} {t.unit} ({det.get('details')})")

                                    alt_details_list = []
                                    for t in rep_alt.terms:
                                        det = get_normalization_details(t, ing.name)
                                        alt_details_list.append(f"{t.value} {t.unit} ({det.get('details')})")

                                    lint_warnings.append(Diagnostic(
                                        severity=Severity.WARNING,
                                        code=Code.CONVERSION_DISCREPANCY,
                                        recipe=recipe.title,
                                        context=ing.raw,
                                        message=(
                                            f"The two stated measurements for '{ing.name}' disagree by "
                                            f"{discrepancy * 100:.1f}% (tolerance {MASS_TOLERANCE_PERCENT * 100:.0f}%)."
                                        ),
                                        detail=[
                                            f"primary:     {rep_primary.raw_text} -> {format_interval(bounds_primary)} "
                                            f"via {', '.join(primary_details_list)}",
                                            f"alternative: {rep_alt.raw_text} -> {format_interval(bounds_alt)} "
                                            f"via {', '.join(alt_details_list)}",
                                            f"the two do not overlap; nearest gap is "
                                            f"{max(bounds_primary[0] - bounds_alt[1], bounds_alt[0] - bounds_primary[1]):.1f}g",
                                        ] + ([
                                            "the alternative was read as a per-item size and scaled by the count",
                                        ] if per_unit_applied else []),
                                    ))

            elif block.section_type == "directions":
                # Under Directions, audit inline duration/temperature conversion discrepancies
                for idx, step in enumerate(block.items):
                    temps = block.extracted_temps.get(idx, [])
                    if len(temps) >= 2:
                        temp_a = temps[0]
                        temp_b = temps[1]

                        match_a = re.match(r"(\d+)°([CF])", temp_a, re.IGNORECASE)
                        match_b = re.match(r"(\d+)°([CF])", temp_b, re.IGNORECASE)

                        if match_a and match_b:
                            val_a, scale_a = float(match_a.group(1)), match_a.group(2).upper()
                            val_b, scale_b = float(match_b.group(1)), match_b.group(2).upper()

                            # Only compare scales if they are actually different (preventing range/option bugs)
                            if scale_a != scale_b:
                                temp_c = val_a if scale_a == "C" else val_b
                                temp_f = val_b if scale_b == "F" else val_a

                                diff = check_temperature_discrepancy(temp_c, temp_f)
                                if diff is not None and diff > TEMP_TOLERANCE_C:
                                    equivalent_f = temp_c * 9.0 / 5.0 + 32.0
                                    lint_warnings.append(Diagnostic(
                                        severity=Severity.WARNING,
                                        code=Code.TEMPERATURE_DISCREPANCY,
                                        recipe=recipe.title,
                                        context=step,
                                        message=(
                                            f"'{temp_a}' and '{temp_b}' are not the same temperature - "
                                            f"they differ by {diff:.1f}°C "
                                            f"(tolerance {TEMP_TOLERANCE_C:.1f}°C)."
                                        ),
                                        detail=[
                                            f"{temp_c:.0f}°C is {equivalent_f:.0f}°F",
                                            f"{temp_f:.0f}°F is {(temp_f - 32.0) * 5.0 / 9.0:.0f}°C",
                                        ],
                                    ))

    return lint_warnings
