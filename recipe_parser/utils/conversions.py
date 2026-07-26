# recipe_parser/utils/conversions.py
import csv
import fnmatch
from pathlib import Path
from typing import Dict
from typing import Optional

from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import UnitClass

# Standard conversion multipliers to standard metric base units (ml for volume, g for weight)
#
# Weight factors are the exact international (1959) definitions, per NIST:
#   1 lb (avoirdupois) = 0.453 592 37 kg exactly  -> 453.59237 g
#   1 oz (avoirdupois) = 1/16 lb exactly          ->  28.349523125 g
#   NIST HB 44 App. C: https://www.nist.gov/document/2023-nist-handbook-44-appendix-c-0
#   NIST SP 811 App. B.9: https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9
#
# Volume factors use the FDA "legal"/labelling definitions (21 CFR 101.9(b)(5)(viii)):
#   1 cup = 240 mL, 1 tablespoon = 15 mL, 1 teaspoon = 5 mL
#   https://www.ecfr.gov/current/title-21/chapter-I/subchapter-B/part-101/subpart-A/section-101.9
#
# NOTE ON THE CHOICE OF SYSTEM. The US *customary* set is cup = 236.5882365 mL,
# tablespoon = 14.78676478 mL, teaspoon = 4.92892159 mL. Either system is defensible,
# but they must not be mixed: this table previously paired a legal 240 mL cup with
# customary 14.7868/4.92892 spoons, which implies 16.23 tablespoons per cup instead of 16.
# The FDA set is used here because it keeps the invariant cup == 16 * tablespoon == 48 * teaspoon,
# it preserves the 240 mL cup the recipes in this repo were already written against, and the
# 15 mL / 5 mL spoons match the UK/metric sources in the corpus as well as the US ones.
METRIC_CONVERSIONS: Dict[str, float] = {
    # Weight (Base: gram)
    "gram":       1.0,
    "kilogram":   1000.0,
    "ounce":      28.349523125,
    "pound":      453.59237,
    # Volume (Base: milliliter)
    "milliliter": 1.0,
    "liter":      1000.0,
    "tablespoon": 15.0,
    "teaspoon":   5.0,
    "cup":        240.0,
}

# Nominal weights (g) for discrete items, keyed by glob patterns matched against the
# *ingredient name* - not the unit. "2 cloves garlic" carries the unit "clove" and the
# name "garlic", so the name is the only place the identity of the thing being counted
# actually lives.
#
# An unmatched piece measurement yields None, meaning "unknown", never 0 g. Zero is a
# confident claim that the ingredient is weightless, and it made "2 lemons (200 g)" look
# like a 100% conversion error rather than something the parser simply cannot check.
#
# Reference values (USDA FoodData Central): large egg without shell = 50 g;
# 1 garlic clove = 3 g (real cloves span roughly 3-7 g); lemon without peel = 58 g,
# whole medium lemon = 100-110 g.
# Each entry is the (min, max) weight of one item in grams. A range, not a point: a
# "small potato" and a "large potato" differ by a factor of three, and pretending a
# nominal figure is exact turns every honest count into a spurious conversion error.
# The comparison logic works on intervals, so the uncertainty propagates properly.
PIECEWISE_WEIGHTS: Dict[str, tuple] = {
    "*egg*":         (44.0, 63.0),    # USDA medium (44g) to jumbo (63g), shelled
    "*egg_yolk*":    (15.0, 20.0),
    "*egg_white*":   (29.0, 38.0),
    "*garlic*":      (3.0, 7.0),      # per clove; USDA nominal is 3 g
    "*lemon*":       (58.0, 120.0),
    "*lime*":        (44.0, 90.0),
    "*onion*":       (70.0, 400.0),   # small to large
    "*shallot*":     (20.0, 50.0),
    "*carrot*":      (45.0, 90.0),
    "*potato*":      (90.0, 300.0),   # small to large
    "*banana*":      (90.0, 145.0),   # peeled
    "*zucchini*":    (120.0, 320.0),
    "*eggplant*":    (300.0, 550.0),
    "*bell_pepper*": (90.0, 170.0),
    "*capsicum*":    (90.0, 170.0),
    "*tomato*":      (90.0, 250.0),   # salad tomato to beefsteak
}

# A "heaped" spoon relative to a level one, as a (min, max) multiplier.
#
# No standards body defines this. The FDA (21 CFR 101.9) and NIST HB 44 App. C define
# only the level spoon - NIST calls even that an "imprecise unit" - and level measuring
# exists specifically to replace heaping (Fannie Farmer, 1896). Published rules of thumb
# disagree by a factor of nearly four, from 1.3x up to "4-5x for fine powders".
#
# The bounds below come from the two things that are actually evidence:
#   - Measurement: Nichols et al., J Pediatr Pharmacol Ther, June 2024, weighed level vs
#     heaping household spoons of PEG-3350 and found ~1.5x (10 g -> 15 g), while noting
#     heaping was the most variable method tested. https://pubmed.ncbi.nlm.nih.gov/38863850/
#   - Geometry: the heap is a cone at the material's angle of repose. Rice (~25-31 deg)
#     implies ~1.4-1.5x, flour and cocoa (~40-50 deg) imply ~1.7-2.0x. The often-quoted
#     3x would need a repose angle of 58-76 deg, which no dry food sustains - it would
#     avalanche off the spoon. So 3x and above are physically unrealisable, not merely
#     unsourced.
#
# The interval starts above 1.0 deliberately: a heaped spoon is definitionally more than
# a level one, so "1 heaped Tbsp" must not silently agree with "1 Tbsp".
HEAPED_MULTIPLIER = (1.3, 2.0)

# Piece units that name a container or portion rather than the ingredient itself.
# Their weight depends on what is inside them, so they are never guessed from the name.
OPAQUE_PIECE_UNITS = {"can", "block", "envelope", "bunch", "head", "stick", "piece", "slice"}


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


def match_by_specificity(normalized_name: str, table: Dict[str, float]):
    """
    Finds the most specific glob pattern in `table` matching an ingredient name.

    Ranking is (exact match, literal character count, total pattern length), all
    descending, so "*ground_ginger*" beats the catch-all "*ground*" regardless of the
    order the patterns happen to appear in. Returns (pattern, value), or (None, None).
    """
    matching_keys = [
        key for key in table
        if fnmatch.fnmatch(normalized_name, key) or fnmatch.fnmatch(normalized_name, f"*{key}*")
    ]
    if not matching_keys:
        return (None, None)

    def specificity(pattern: str) -> tuple:
        is_exact = (pattern == normalized_name)
        literal_length = len(pattern.replace("*", "").replace("?", ""))
        return (is_exact, literal_length, len(pattern))

    best = max(matching_keys, key=specificity)
    return (best, table[best])


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
    # Clean up name strings containing slashes or dashes to allow clean pattern matching
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

    # 2. Piece Case - resolved from the ingredient name, since the unit ("clove", "count")
    #    says how it is portioned but not what it is.
    if measurement.unit_class == UnitClass.PIECE:
        unit_name = measurement.unit.lower()
        if unit_name in OPAQUE_PIECE_UNITS:
            return {
                "value":   None,
                "unit":    measurement.unit,
                "details": f"'{unit_name}' is a container unit; its weight depends on the contents (unknown)"
            }

        matched_pattern, weight_range = match_by_specificity(normalized_name, PIECEWISE_WEIGHTS)
        if weight_range is None:
            return {
                "value":   None,
                "unit":    measurement.unit,
                "details": f"No piece weight known for '{normalized_name}' (unknown, not zero)"
            }
        low_weight, high_weight = weight_range
        return {
            "value":     measurement.value * (low_weight + high_weight) / 2.0,
            "value_min": measurement.value * low_weight,
            "value_max": measurement.value * high_weight,
            "unit":      measurement.unit,
            "details":   f"Piece weight for pattern '{matched_pattern}': {low_weight:g}-{high_weight:g}g each"
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

        matched_key, density = match_by_specificity(normalized_name, INGREDIENT_DENSITIES)
        if density is None:
            matched_key = "water (default)"
            density = 1.0

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
