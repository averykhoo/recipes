# recipe_parser/utils/conversions.py
import csv
import fnmatch
from pathlib import Path
from typing import Dict
from typing import Optional

from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import UnitClass

# Standard conversion multipliers to standard metric base units (ml for volume, g for weight)
METRIC_CONVERSIONS: Dict[str, float] = {
    # Weight (Base: gram)
    "gram":       1.0,
    "kilogram":   1000.0,
    "ounce":      28.3495,
    "pound":      453.5923,
    # Volume (Base: milliliter)
    "milliliter": 1.0,
    "liter":      1000.0,
    "tablespoon": 14.7868,
    "teaspoon":   4.92892,
    "cup":        240.0,
}

# Nominal weights (g) for discrete items
PIECEWISE_WEIGHTS: Dict[str, float] = {
    "egg":          50.0,
    "butter_stick": 250.0,  # Tailored to local 250g butter sticks
    "garlic_clove": 5.0,
    "lemon":        100.0,
}


def load_densities_from_csv() -> Dict[str, float]:
    """
    Loads ingredient densities from the sibling CSV configuration file.
    Falls back to basic standard defaults if the file is missing or corrupted.
    """
    csv_path = Path(__file__).parent / "ingredient_densities.csv"
    if not csv_path.exists():
        return {
            "powdered_sugar":    0.50,
            "granulated_sugar":  0.85,
            "all_purpose_flour": 0.52,
            "water":             1.00,
            "butter":            0.96,
            "whole_milk":        1.03,
            "olive_oil":         0.91,
        }

    densities = {}
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pattern = row["pattern"].strip()
                try:
                    density = float(row["density"].strip())
                    densities[pattern] = density
                except (ValueError, KeyError):
                    continue
    except Exception:
        # Graceful fallback to avoid pipeline crashes
        return {
            "powdered_sugar":    0.50,
            "granulated_sugar":  0.85,
            "all_purpose_flour": 0.52,
            "water":             1.00,
            "butter":            0.96,
            "whole_milk":        1.03,
            "olive_oil":         0.91,
        }
    return densities


# Dynamic, package-relative density lookup dictionary
INGREDIENT_DENSITIES = load_densities_from_csv()


def normalize_measurement_to_grams(measurement: Measurement, ingredient_name: str) -> Optional[float]:
    """
    Translates any volumetric, weight-based, or piece-based measurement into standard grams.
    """
    details = get_normalization_details(measurement, ingredient_name)
    return details.get("value")


def get_normalization_details(measurement: Measurement, ingredient_name: str) -> dict:
    """
    Returns a dictionary containing the matched category, density/piece weight,
    and normalized gram weight for debugging/validation purposes.
    """
    normalized_name = ingredient_name.lower().replace(" ", "_").replace("-", "_").replace("/", "_")

    # 1. Nesting Piece Case
    if measurement.unit_class == UnitClass.PIECE and measurement.nested_capacity:
        outer_multiplier = measurement.value
        inner_details = get_normalization_details(measurement.nested_capacity, ingredient_name)
        total_g = outer_multiplier * inner_details.get("value", 0.0)
        return {
            "value":   total_g,
            "unit":    measurement.unit,
            "details": f"Nested Piece container: {measurement.value} * {inner_details.get('value')}g ({inner_details.get('details')})"
        }

    # 2. Piece Case
    if measurement.unit_class == UnitClass.PIECE:
        singular_unit = measurement.unit.rstrip("s").lower()
        weight = PIECEWISE_WEIGHTS.get(singular_unit, 0.0)
        return {
            "value":   measurement.value * weight,
            "unit":    measurement.unit,
            "details": f"Piece weight for '{singular_unit}': {weight}g/pc" if weight > 0 else f"No piecewise weight matched for '{singular_unit}' (defaulting to 0.0g)"
        }

    # 3. Weight Case
    if measurement.unit_class == UnitClass.WEIGHT:
        factor = METRIC_CONVERSIONS.get(measurement.unit.lower(), 1.0)
        return {
            "value":   measurement.value * factor,
            "unit":    measurement.unit,
            "details": f"Weight conversion factor: {factor}g/{measurement.unit}"
        }

    # 4. Volume Case (Requires glob density lookup)
    if measurement.unit_class == UnitClass.VOLUME:
        factor = METRIC_CONVERSIONS.get(measurement.unit.lower(), 1.0)
        total_ml = measurement.value * factor

        # Search logic utilizing fnmatch globs
        matched_key = "water (default)"
        density = 1.0

        # Try direct match first
        if normalized_name in INGREDIENT_DENSITIES:
            matched_key = normalized_name
            density = INGREDIENT_DENSITIES[normalized_name]
        else:
            # Sort keys by length descending to match more specific glob pattern keys first
            sorted_keys = sorted(INGREDIENT_DENSITIES.keys(), key=len, reverse=True)
            for key in sorted_keys:
                if fnmatch.fnmatch(normalized_name, key) or fnmatch.fnmatch(normalized_name, f"*{key}*"):
                    matched_key = key
                    density = INGREDIENT_DENSITIES[key]
                    break

        return {
            "value":   total_ml * density,
            "unit":    measurement.unit,
            "details": f"Volume conversion factor: {factor}ml/{measurement.unit}, Density for pattern '{matched_key}': {density}g/ml"
        }

    return {"value": 0.0, "unit": measurement.unit, "details": "Unknown unit class"}


def calculate_mass_discrepancy(mass_a: float, mass_b: float) -> float:
    """
    Returns the percentage discrepancy between two masses.
    """
    return abs(mass_a - mass_b) / max(mass_a, mass_b)


def check_temperature_discrepancy(temp_celsius: float, temp_fahrenheit: float) -> Optional[float]:
    """
    Returns the absolute difference in Celsius between a Celsius temperature
    and its Fahrenheit alternative.
    """
    converted_c = (temp_fahrenheit - 32.0) * (5.0 / 9.0)
    return abs(temp_celsius - converted_c)
