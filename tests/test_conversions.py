"""Tests for recipe_parser.utils.conversions.

Covers the metric constants, the four normalisation branches (weight, volume,
piece, nested container), the water fallback, the discrepancy helpers, and the
specificity ranking of the glob-based density lookup.
"""
import csv
import fnmatch
from pathlib import Path

import pytest

from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import UnitClass
from recipe_parser.utils import conversions as C


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def weight(value: float, unit: str) -> Measurement:
    return Measurement(value=value, unit=unit, unit_class=UnitClass.WEIGHT)


def volume(value: float, unit: str) -> Measurement:
    return Measurement(value=value, unit=unit, unit_class=UnitClass.VOLUME)


def piece(value: float, unit: str, nested: Measurement = None) -> Measurement:
    return Measurement(value=value, unit=unit, unit_class=UnitClass.PIECE, nested_capacity=nested)


# --------------------------------------------------------------------------
# METRIC_CONVERSIONS
# --------------------------------------------------------------------------

class TestMetricConstants:
    def test_metric_base_units_are_identities(self):
        assert C.METRIC_CONVERSIONS["gram"] == 1.0
        assert C.METRIC_CONVERSIONS["milliliter"] == 1.0
        assert C.METRIC_CONVERSIONS["kilogram"] == 1000.0
        assert C.METRIC_CONVERSIONS["liter"] == 1000.0

    def test_pound_is_the_exact_international_definition(self):
        # NIST: 1 lb (avoirdupois) = 0.45359237 kg exactly.
        assert C.METRIC_CONVERSIONS["pound"] == pytest.approx(453.59237, abs=1e-9)

    def test_ounce_is_exactly_one_sixteenth_of_a_pound(self):
        # NIST: 1 oz (avoirdupois) = 1/16 lb = 28.349523125 g exactly.
        assert C.METRIC_CONVERSIONS["ounce"] == pytest.approx(28.349523125, abs=1e-9)
        assert C.METRIC_CONVERSIONS["ounce"] * 16 == pytest.approx(
            C.METRIC_CONVERSIONS["pound"], rel=1e-12
        )

    def test_volume_units_are_internally_coherent(self):
        # Whichever system is chosen, a cup must be 16 tablespoons and 48 teaspoons.
        cup = C.METRIC_CONVERSIONS["cup"]
        tbsp = C.METRIC_CONVERSIONS["tablespoon"]
        tsp = C.METRIC_CONVERSIONS["teaspoon"]
        assert cup == pytest.approx(16 * tbsp, rel=1e-6)
        assert cup == pytest.approx(48 * tsp, rel=1e-6)
        assert tbsp == pytest.approx(3 * tsp, rel=1e-6)

    def test_volume_units_match_the_fda_legal_definitions(self):
        # 21 CFR 101.9(b)(5)(viii): cup = 240 mL, tablespoon = 15 mL, teaspoon = 5 mL.
        assert C.METRIC_CONVERSIONS["cup"] == pytest.approx(240.0)
        assert C.METRIC_CONVERSIONS["tablespoon"] == pytest.approx(15.0)
        assert C.METRIC_CONVERSIONS["teaspoon"] == pytest.approx(5.0)


# --------------------------------------------------------------------------
# weight normalisation
# --------------------------------------------------------------------------

class TestWeightNormalisation:
    def test_grams_pass_through(self):
        assert C.normalize_measurement_to_grams(weight(250.0, "gram"), "flour") == pytest.approx(250.0)

    def test_kilograms(self):
        assert C.normalize_measurement_to_grams(weight(1.5, "kilogram"), "beef") == pytest.approx(1500.0)

    def test_pounds_and_ounces(self):
        assert C.normalize_measurement_to_grams(weight(1.0, "pound"), "butter") == pytest.approx(453.59237)
        assert C.normalize_measurement_to_grams(weight(8.0, "ounce"), "flour") == pytest.approx(226.796185)

    def test_unit_lookup_is_case_insensitive(self):
        assert C.normalize_measurement_to_grams(weight(1.0, "Pound"), "butter") == pytest.approx(453.59237)

    def test_unknown_weight_unit_falls_back_to_factor_one(self):
        assert C.normalize_measurement_to_grams(weight(7.0, "smidgen"), "salt") == pytest.approx(7.0)

    def test_details_string_reports_the_factor(self):
        d = C.get_normalization_details(weight(2.0, "ounce"), "flour")
        assert "Weight conversion factor" in d["details"]
        assert d["unit"] == "ounce"


# --------------------------------------------------------------------------
# volume normalisation
# --------------------------------------------------------------------------

class TestVolumeNormalisation:
    def test_water_is_one_gram_per_millilitre(self):
        assert C.normalize_measurement_to_grams(volume(250.0, "milliliter"), "water") == pytest.approx(250.0)

    def test_known_density_is_applied(self):
        # olive_oil is an exact key in the CSV at 0.91 g/ml.
        grams = C.normalize_measurement_to_grams(volume(1.0, "cup"), "olive oil")
        assert grams == pytest.approx(240.0 * 0.91)

    def test_density_lookup_normalises_spaces_hyphens_and_slashes(self):
        expected = 240.0 * C.INGREDIENT_DENSITIES["all_purpose_flour"]
        for name in ("all purpose flour", "all-purpose flour", "all/purpose/flour", "ALL PURPOSE FLOUR"):
            assert C.normalize_measurement_to_grams(volume(1.0, "cup"), name) == pytest.approx(expected)

    def test_unmatched_ingredient_falls_back_to_water(self):
        d = C.get_normalization_details(volume(1.0, "cup"), "zzz unlisted substance")
        assert d["value"] == pytest.approx(240.0)
        assert "water (default)" in d["details"]

    def test_matched_ingredient_does_not_report_the_water_fallback(self):
        d = C.get_normalization_details(volume(1.0, "cup"), "pecan halves")
        assert "water (default)" not in d["details"]
        assert d["value"] < 240.0

    def test_teaspoon_and_tablespoon_scale_together(self):
        tsp = C.normalize_measurement_to_grams(volume(3.0, "teaspoon"), "water")
        tbsp = C.normalize_measurement_to_grams(volume(1.0, "tablespoon"), "water")
        assert tsp == pytest.approx(tbsp)


# --------------------------------------------------------------------------
# density pattern specificity
# --------------------------------------------------------------------------

class TestDensityPatternMatching:
    def test_csv_has_no_duplicate_patterns(self):
        # Duplicate keys are silently collapsed by the dict, so the later row wins
        # and the earlier (often correct) one disappears without warning.
        path = Path(C.__file__).parent / "ingredient_densities.csv"
        patterns = [row["pattern"].strip() for row in csv.DictReader(path.open(encoding="utf-8"))]
        duplicates = {p for p in patterns if patterns.count(p) > 1}
        assert not duplicates, f"duplicate density patterns: {sorted(duplicates)}"

    def test_every_density_is_physically_plausible(self):
        for pattern, density in C.INGREDIENT_DENSITIES.items():
            assert 0.0 < density < 2.0, f"implausible density for {pattern!r}: {density}"

    def test_specific_pattern_beats_broad_wildcard(self):
        # '*cocoa_powder*' must win over the much broader '*powder*'.
        cocoa = C.get_normalization_details(volume(1.0, "cup"), "unsweetened dutch-process cocoa powder")
        assert "cocoa_powder" in cocoa["details"]

        # '*brown_sugar*' must win over '*sugar*'.
        brown = C.get_normalization_details(volume(1.0, "cup"), "light brown sugar")
        assert "brown_sugar" in brown["details"]

        # An exact key must win over any wildcard that also matches.
        exact = C.get_normalization_details(volume(1.0, "cup"), "all_purpose_flour")
        assert "'all_purpose_flour'" in exact["details"]

    def test_broad_wildcards_do_not_shadow_specific_spice_patterns(self):
        # '*ground*' and '*powder*' are deliberately broad catch-alls; anything more
        # specific must outrank them.
        for name, expected in [
            ("ground ginger", "ground_ginger"),
            ("garlic powder", "garlic_powder"),
            ("onion powder", "onion_powder"),
            ("smoked paprika", "paprika"),
            ("ground nutmeg", "nutmeg"),
            ("vanilla bean powder", "vanilla_bean_powder"),
        ]:
            details = C.get_normalization_details(volume(1.0, "teaspoon"), name)["details"]
            assert expected in details, f"{name!r} matched {details!r}"

    def test_specificity_ranking_is_deterministic(self):
        # No ingredient may tie on the full specificity score with a pattern of a
        # different density, otherwise the winner depends on CSV row order.
        def score(key: str, name: str):
            return (key == name, len(key.replace("*", "").replace("?", "")), len(key))

        names = [
            "ground ginger", "ground nutmeg", "ground savory", "icing sugar",
            "garlic powder", "onion powder", "cocoa powder", "light brown sugar",
            "chocolate chips", "kosher salt", "sesame oil", "rice vinegar",
        ]
        for raw in names:
            name = raw.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
            matches = [
                k for k in C.INGREDIENT_DENSITIES
                if fnmatch.fnmatch(name, k) or fnmatch.fnmatch(name, f"*{k}*")
            ]
            matches.sort(key=lambda k: score(k, name), reverse=True)
            if len(matches) > 1 and score(matches[0], name) == score(matches[1], name):
                assert C.INGREDIENT_DENSITIES[matches[0]] == C.INGREDIENT_DENSITIES[matches[1]], (
                    f"{name!r} ties between {matches[0]!r} and {matches[1]!r} with different densities"
                )


# --------------------------------------------------------------------------
# piece normalisation
# --------------------------------------------------------------------------

class TestPieceNormalisation:
    def test_known_piece_weight_is_applied_as_a_midpoint(self):
        low, high = C.PIECEWISE_WEIGHTS["*egg*"]
        expected = 3.0 * (low + high) / 2.0
        assert C.normalize_measurement_to_grams(piece(3.0, "count"), "eggs") == pytest.approx(expected)

    def test_piece_weight_carries_its_uncertainty(self):
        """A nominal piece weight is a range; the bounds must survive the conversion."""
        low, high = C.PIECEWISE_WEIGHTS["*egg*"]
        d = C.get_normalization_details(piece(3.0, "count"), "eggs")
        assert d["value_min"] == pytest.approx(3.0 * low)
        assert d["value_max"] == pytest.approx(3.0 * high)

    def test_every_configured_piece_weight_is_a_sane_range(self):
        for pattern, bounds in C.PIECEWISE_WEIGHTS.items():
            low, high = bounds
            assert 0 < low <= high, f"{pattern} has a nonsensical range {bounds}"

    def test_all_configured_piece_weights_resolve_by_name(self):
        for pattern in C.PIECEWISE_WEIGHTS:
            name = pattern.strip("*")
            assert C.normalize_measurement_to_grams(piece(1.0, "count"), name) is not None

    def test_unknown_piece_weight_is_none_not_zero(self):
        # "Unknown" must not be reported as zero grams: zero is a confident claim that
        # the ingredient is weightless, which turns an uncheckable line into a 100% error.
        d = C.get_normalization_details(piece(2.0, "count"), "sprigs of thyme")
        assert d["value"] is None
        assert "unknown" in d["details"].lower()

    def test_piece_weights_are_keyed_by_ingredient_name(self):
        # The unit says how the thing is portioned ("count", "clove"); the name says what
        # it is. Only the name can identify the weight.
        low, high = C.PIECEWISE_WEIGHTS["*lemon*"]
        d = C.get_normalization_details(piece(2.0, "count"), "lemons")
        assert d["value"] == pytest.approx(2.0 * (low + high) / 2.0)

    def test_piece_weight_ignores_the_unit_word(self):
        by_count = C.get_normalization_details(piece(1.0, "count"), "garlic")
        by_clove = C.get_normalization_details(piece(1.0, "clove"), "garlic")
        assert by_count["value"] == by_clove["value"]
        assert by_count["value"] is not None

    def test_container_units_stay_unknown_regardless_of_name(self):
        # A can of tomatoes weighs whatever is in the can, not whatever a tomato weighs.
        d = C.get_normalization_details(piece(2.0, "can"), "tomatoes")
        assert d["value"] is None

    def test_piece_weight_uses_specificity_ranking(self):
        # "*egg_yolk*" must beat the broader "*egg*".
        yolk = C.get_normalization_details(piece(1.0, "count"), "egg yolks")
        whole = C.get_normalization_details(piece(1.0, "count"), "eggs")
        assert "egg_yolk" in yolk["details"]
        assert yolk["value"] < whole["value"]


# --------------------------------------------------------------------------
# nested container capacity
# --------------------------------------------------------------------------

class TestNestedCapacity:
    def test_cans_of_a_weight_capacity(self):
        # '2 cans (15 oz each)'
        m = piece(2.0, "can", nested=weight(15.0, "ounce"))
        assert C.normalize_measurement_to_grams(m, "tomatoes") == pytest.approx(2 * 15 * 28.349523125)

    def test_cans_of_a_volume_capacity_use_the_ingredient_density(self):
        # '3 cans (1 cup each)' of olive oil
        m = piece(3.0, "can", nested=volume(1.0, "cup"))
        assert C.normalize_measurement_to_grams(m, "olive oil") == pytest.approx(3 * 240.0 * 0.91)

    def test_nested_details_mention_the_inner_conversion(self):
        m = piece(2.0, "can", nested=weight(15.0, "ounce"))
        d = C.get_normalization_details(m, "tomatoes")
        assert "Nested Piece container" in d["details"]
        assert "Weight conversion factor" in d["details"]

    def test_nested_capacity_of_an_unknown_ingredient_falls_back_to_water(self):
        m = piece(2.0, "can", nested=volume(1.0, "cup"))
        assert C.normalize_measurement_to_grams(m, "zzz unlisted") == pytest.approx(480.0)


# --------------------------------------------------------------------------
# discrepancy helpers
# --------------------------------------------------------------------------

class TestMassDiscrepancy:
    def test_identical_masses_have_no_discrepancy(self):
        assert C.calculate_mass_discrepancy(100.0, 100.0) == pytest.approx(0.0)

    def test_discrepancy_is_relative_to_the_larger_mass(self):
        assert C.calculate_mass_discrepancy(90.0, 100.0) == pytest.approx(0.10)
        assert C.calculate_mass_discrepancy(100.0, 90.0) == pytest.approx(0.10)

    def test_discrepancy_is_symmetric(self):
        assert C.calculate_mass_discrepancy(53.8, 60.0) == pytest.approx(
            C.calculate_mass_discrepancy(60.0, 53.8)
        )

    def test_a_zero_mass_reads_as_a_total_discrepancy(self):
        # Relevant to the 'count' case, which normalises to 0.0 g.
        assert C.calculate_mass_discrepancy(0.0, 200.0) == pytest.approx(1.0)

    def test_pecan_halves_are_within_tolerance_of_a_reasonable_statement(self):
        # 1 cup pecan halves is about 100 g (USDA / King Arthur), not 240 g of water.
        grams = C.normalize_measurement_to_grams(volume(1.0, "cup"), "pecan halves")
        assert C.calculate_mass_discrepancy(grams, 100.0) < 0.10


class TestTemperatureDiscrepancy:
    def test_exact_equivalents_agree(self):
        assert C.check_temperature_discrepancy(100.0, 212.0) == pytest.approx(0.0)
        assert C.check_temperature_discrepancy(0.0, 32.0) == pytest.approx(0.0)
        assert C.check_temperature_discrepancy(-40.0, -40.0) == pytest.approx(0.0)

    def test_typical_oven_rounding_is_small(self):
        # 180 C is commonly written as 350 F (176.67 C).
        assert C.check_temperature_discrepancy(180.0, 350.0) == pytest.approx(3.333, abs=1e-3)

    def test_a_wrong_conversion_is_reported_as_a_large_gap(self):
        assert C.check_temperature_discrepancy(200.0, 350.0) == pytest.approx(23.333, abs=1e-3)

    def test_result_is_always_non_negative(self):
        for c_temp, f_temp in [(10.0, 200.0), (200.0, 10.0), (0.0, 0.0)]:
            assert C.check_temperature_discrepancy(c_temp, f_temp) >= 0.0


# --------------------------------------------------------------------------
# CSV loading
# --------------------------------------------------------------------------

class TestDensityLoading:
    def test_densities_load_from_the_sibling_csv(self):
        assert len(C.INGREDIENT_DENSITIES) > 50
        assert C.INGREDIENT_DENSITIES["water"] == pytest.approx(1.0)

    def test_loader_returns_defaults_when_the_csv_is_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(C, "__file__", str(tmp_path / "conversions.py"))
        fallback = C.load_densities_from_csv()
        assert fallback["water"] == pytest.approx(1.0)
        assert "all_purpose_flour" in fallback

    def test_loader_skips_rows_with_an_unparseable_density(self, monkeypatch, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "ingredient_densities.csv").write_text(
            "pattern,density\ngood,0.5\nbad,not-a-number\n", encoding="utf-8"
        )
        monkeypatch.setattr(C, "__file__", str(pkg / "conversions.py"))
        loaded = C.load_densities_from_csv()
        assert loaded == {"good": 0.5}


# --------------------------------------------------------------------------
# unknown unit class
# --------------------------------------------------------------------------

def test_non_mass_unit_class_returns_zero_with_an_explanation():
    m = Measurement(value=30.0, unit="minute", unit_class=UnitClass.DURATION)
    d = C.get_normalization_details(m, "resting time")
    assert d["value"] == 0.0
    assert d["details"] == "Unknown unit class"
