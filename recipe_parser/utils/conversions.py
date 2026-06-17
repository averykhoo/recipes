# recipe_parser/utils/conversions.py
from typing import Dict, Optional
from recipe_parser.models.schemas import UnitClass, Measurement

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

# Average ingredient densities (g/ml)
INGREDIENT_DENSITIES: Dict[str, float] = {
    "powdered_sugar":    0.50,
    "granulated_sugar":  0.85,
    "all_purpose_flour": 0.52,
    "water":             1.00,
    "butter":            0.96,
    "whole_milk":        1.03,
    "olive_oil":         0.91,
}

# Nominal weights (g) for discrete items
PIECEWISE_WEIGHTS: Dict[str, float] = {
    "egg":          50.0,
    "butter_stick": 250.0,  # Tailored to local 250g butter sticks
    "garlic_clove": 5.0,
    "lemon":        100.0,
}


def normalize_measurement_to_grams(measurement: Measurement, ingredient_name: str) -> Optional[float]:
    """
    Translates any volumetric, weight-based, or piece-based measurement into standard grams.
    """
    normalized_name = ingredient_name.lower().replace(" ", "_")

    # 1. Nesting Multiplication Case (Multi-pack piece containers)
    if measurement.unit_class == UnitClass.PIECE and measurement.nested_capacity:
        outer_multiplier = measurement.value
        inner_capacity = normalize_measurement_to_grams(measurement.nested_capacity, ingredient_name)
        if inner_capacity is not None:
            return outer_multiplier * inner_capacity
        return None

    # 2. Base Piece Case
    if measurement.unit_class == UnitClass.PIECE:
        # Match standard singular terms
        singular_unit = measurement.unit.rstrip("s").lower()
        if singular_unit in PIECEWISE_WEIGHTS:
            return measurement.value * PIECEWISE_WEIGHTS[singular_unit]
        return None

    # 3. Weight Case
    if measurement.unit_class == UnitClass.WEIGHT:
        factor = METRIC_CONVERSIONS.get(measurement.unit.lower())
        if factor:
            return measurement.value * factor
        return None

    # 4. Volume Case (Requires density lookup)
    if measurement.unit_class == UnitClass.VOLUME:
        factor = METRIC_CONVERSIONS.get(measurement.unit.lower())
        if factor:
            total_ml = measurement.value * factor
            # Retrieve density, default to water (1.0) if ingredient is unknown
            density = INGREDIENT_DENSITIES.get(normalized_name, 1.0)
            return total_ml * density
        return None

    return None


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