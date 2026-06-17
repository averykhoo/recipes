# recipe_parser/validation/linter.py
"""
Linter module that executes mathematical conversion checkers, boundary audits,
and structural constraints on the parsed DOM block tree.
"""

import re
from typing import List
from recipe_parser.models.schemas import Recipe, BlockType, UnitClass
from recipe_parser.utils.conversions import (
    normalize_measurement_to_grams, calculate_mass_discrepancy, check_temperature_discrepancy
)

MASS_TOLERANCE_PERCENT = 0.10  # 10% discrepancy allowed
TEMP_TOLERANCE_C = 5.0  # 5°C discrepancy allowed


def lint_recipe_document(recipe: Recipe) -> List[str]:
    """
    Executes structural and mathematical conversions quality checks on the recipe tree.
    """
    lint_warnings = []

    for block in recipe.blocks:
        if block.block_type == BlockType.LIST:
            # Find closest preceding header to identify section context
            is_ingredients = False
            preceding_heading = None
            for b in recipe.blocks:
                if b == block:
                    break
                if b.block_type == BlockType.HEADING:
                    preceding_heading = b

            if preceding_heading and preceding_heading.section_type == "ingredients":
                is_ingredients = True

            if is_ingredients:
                for item in block.items:
                    if not item.parsed_ingredient:
                        continue

                    ing = item.parsed_ingredient

                    # Enforce only AMOUNT classes under ingredients
                    for rep in ing.representations:
                        for term in rep.terms:
                            if term.unit_class in (UnitClass.DURATION, UnitClass.TEMPERATURE):
                                lint_warnings.append(
                                    f"[{recipe.title}] Lint Error: Ingredient '{ing.name}' "
                                    f"uses invalid unit class '{term.unit_class}' (unit: '{term.unit}')"
                                )
                                continue

                            # Enforce Nesting constraints
                            if term.nested_capacity:
                                if term.unit_class != UnitClass.PIECE:
                                    lint_warnings.append(
                                        f"[{recipe.title}] Lint Error: Nesting capacity is "
                                        f"only allowed inside PIECE containers (found inside '{term.unit_class}')"
                                    )
                                if term.nested_capacity.unit_class not in (UnitClass.VOLUME, UnitClass.WEIGHT):
                                    lint_warnings.append(
                                        f"[{recipe.title}] Lint Error: Nested capacity must "
                                        f"be VOLUME or WEIGHT (found: '{term.nested_capacity.unit_class}')"
                                    )

                        # Enforce conversion sanity checking
                        if len(ing.representations) >= 2:
                            rep_primary = ing.representations[0]
                            rep_alt = ing.representations[1]

                            mass_primary = 0.0
                            for t in rep_primary.terms:
                                grams = normalize_measurement_to_grams(t, ing.name)
                                if grams is not None:
                                    mass_primary += grams

                            mass_alt = 0.0
                            for t in rep_alt.terms:
                                grams = normalize_measurement_to_grams(t, ing.name)
                                if grams is not None:
                                    mass_alt += grams

                            if mass_primary > 0 and mass_alt > 0:
                                discrepancy = calculate_mass_discrepancy(mass_primary, mass_alt)
                                if discrepancy > MASS_TOLERANCE_PERCENT:
                                    lint_warnings.append(
                                        f"[{recipe.title}] Conversion discrepancy: '{ing.name}' alternative "
                                        f"({rep_alt.raw_text}) is inconsistent with primary ({rep_primary.raw_text}) "
                                        f"by {discrepancy * 100:.1f}% (exceeds allowed {MASS_TOLERANCE_PERCENT * 100:.0f}%)"
                                    )

            else:
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

                            celsius = val_a if scale_a == "C" else (val_a - 32.0) * (5.0 / 9.0)
                            fahr = val_b if scale_b == "F" else (val_b * (9.0 / 5.0)) + 32.0

                            diff = check_temperature_discrepancy(celsius, fahr)
                            if diff is not None and diff > TEMP_TOLERANCE_C:
                                lint_warnings.append(
                                    f"[{recipe.title}] Temperature discrepancy in step: "
                                    f"'{temp_a}' is inconsistent with alternative '{temp_b}' "
                                    f"by {diff:.1f}°C (exceeds allowed {TEMP_TOLERANCE_C:.1f}°C offset)"
                                )

    return lint_warnings