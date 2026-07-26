"""Tests for ingredient line parsing.

Many of these encode specific bugs that silently dropped measurements. The parser never
raises on a bad line, it just produces an ingredient with no quantity, so a regression
here is invisible without a test.
"""

import pytest

from recipe_parser.models.schemas import UnitClass
from recipe_parser.rules.ingredients import parse_ingredient_line


def terms_of(line):
    """All measurement terms across every representation of a parsed line."""
    ingredient = parse_ingredient_line(line)
    assert ingredient is not None
    return [term for rep in ingredient.representations for term in rep.terms]


def only_term(line):
    """The single measurement term of a line, asserting there is exactly one."""
    terms = terms_of(line)
    assert len(terms) == 1, f"expected exactly one term, got {terms}"
    return terms[0]


class TestUnitRecognition:
    @pytest.mark.parametrize("line, value, unit, unit_class", [
        ("225g flour", 225.0, "gram", UnitClass.WEIGHT),
        ("1.5 kg potatoes", 1.5, "kilogram", UnitClass.WEIGHT),
        ("8 oz butter", 8.0, "ounce", UnitClass.WEIGHT),
        ("2 lbs beef", 2.0, "pound", UnitClass.WEIGHT),
        ("3 cups milk", 3.0, "cup", UnitClass.VOLUME),
        ("1 tbsp oil", 1.0, "tablespoon", UnitClass.VOLUME),
        ("2 tsp salt", 2.0, "teaspoon", UnitClass.VOLUME),
        ("150ml stock", 150.0, "milliliter", UnitClass.VOLUME),
        ("1 clove garlic", 1.0, "clove", UnitClass.PIECE),
        ("2 slices bread", 2.0, "slice", UnitClass.PIECE),
    ])
    def test_canonical_units(self, line, value, unit, unit_class):
        term = only_term(line)
        assert term.value == pytest.approx(value)
        assert term.unit == unit
        assert term.unit_class == unit_class

    def test_unit_alias_case_is_ignored(self):
        assert only_term("2 TBSP oil").unit == "tablespoon"

    def test_of_is_stripped_from_the_name(self):
        ingredient = parse_ingredient_line("1 clove of garlic")
        assert ingredient.name == "garlic"

    def test_trailing_period_on_unit(self):
        assert only_term("2 tsp. vanilla").unit == "teaspoon"


class TestRanges:
    """Regression: hyphen ranges without surrounding whitespace lost their quantity."""

    @pytest.mark.parametrize("line, midpoint, low, high, unit", [
        ("1-2 tsp butter", 1.5, 1.0, 2.0, "teaspoon"),
        ("2-3 cups dashi", 2.5, 2.0, 3.0, "cup"),
        ("70-140g diced red onion", 105.0, 70.0, 140.0, "gram"),
        ("50-75 ml sour cream", 62.5, 50.0, 75.0, "milliliter"),
    ])
    def test_hyphen_range_with_unit(self, line, midpoint, low, high, unit):
        term = only_term(line)
        assert term.value == pytest.approx(midpoint)
        assert term.value_min == pytest.approx(low)
        assert term.value_max == pytest.approx(high)
        assert term.unit == unit
        assert term.is_range

    def test_en_dash_range(self):
        term = only_term("200–300 ml cream")
        assert term.value_min == 200.0 and term.value_max == 300.0
        assert term.unit == "milliliter"

    def test_word_to_range(self):
        term = only_term("0.5 to 1 Tbsp ginger")
        assert term.value == pytest.approx(0.75)
        assert term.unit == "tablespoon"

    @pytest.mark.parametrize("line, low, high, unit", [
        ("500g-750g tomatoes", 500.0, 750.0, "gram"),
        ("100g-200g bacon", 100.0, 200.0, "gram"),
    ])
    def test_unit_repeated_on_both_ends_of_range(self, line, low, high, unit):
        """"500g-750g" repeats the unit; only the first one should be kept."""
        term = only_term(line)
        assert term.value_min == pytest.approx(low)
        assert term.value_max == pytest.approx(high)
        assert term.unit == unit

    def test_range_of_bare_counts(self):
        term = only_term("2-3 carrots")
        assert term.value == pytest.approx(2.5)
        assert term.unit == "count"
        assert term.implicit_unit

    def test_scalar_is_not_a_range(self):
        assert not only_term("2 cups flour").is_range


class TestBareCounts:
    """A leading number with no unit word is a count of whole things."""

    @pytest.mark.parametrize("line, value, name", [
        ("5 eggs", 5.0, "eggs"),
        ("2 large lemons", 2.0, "large lemons"),
        ("1 onion", 1.0, "onion"),
        ("2 medium yellow onions", 2.0, "medium yellow onions"),
    ])
    def test_counts(self, line, value, name):
        ingredient = parse_ingredient_line(line)
        term = only_term(line)
        assert term.value == pytest.approx(value)
        assert term.unit == "count"
        assert term.unit_class == UnitClass.PIECE
        assert term.implicit_unit is True
        assert ingredient.name == name

    def test_explicit_units_are_not_marked_implicit(self):
        assert only_term("2 cups flour").implicit_unit is False

    @pytest.mark.parametrize("line", [
        "70% dark chocolate",  # a percentage, not 70 pieces
        "9-inch pie shell",  # a dimension, not 9 pieces
        "0.5-1 inch ginger",  # a dimension range
        "6cm piece of ginger",  # a dimension
    ])
    def test_dimensions_and_percentages_are_not_counts(self, line):
        """These must produce no measurement rather than a nonsense count."""
        assert terms_of(line) == []

    def test_hyphenated_unit_is_still_a_unit(self):
        """"6-pound pumpkin" hyphenates the number to a real unit, unlike "9-inch"."""
        term = only_term("6-pound cheese pumpkin, halved")
        assert term.value == 6.0
        assert term.unit == "pound"

    @pytest.mark.parametrize("line, name", [
        ("70% dark chocolate", "70% dark chocolate"),
        ("9-inch pie shell", "9-inch pie shell"),
    ])
    def test_a_number_that_belongs_to_the_name_is_kept(self, line, name):
        """Stripping the leading number here would mangle the ingredient's own name."""
        assert parse_ingredient_line(line).name == name

    @pytest.mark.parametrize("line, value, name", [
        ("about 2 lemons", 2.0, "lemons"),
        ("~3 onions", 3.0, "onions"),
        ("roughly 4 eggs", 4.0, "eggs"),
    ])
    def test_hedged_bare_counts(self, line, value, name):
        """Regression: a hedge word or "~" used to suppress the inferred count entirely."""
        term = only_term(line)
        assert term.value == pytest.approx(value)
        assert term.unit == "count"
        assert parse_ingredient_line(line).name == name


class TestApproximateAndMultipliers:
    def test_tilde_prefix_is_tolerated(self):
        term = only_term("~1 tsp black pepper")
        assert term.value == 1.0
        assert term.unit == "teaspoon"

    def test_tilde_prefix_with_fraction(self):
        term = only_term("~3/4 cup iced water")
        assert term.value == pytest.approx(0.75)
        assert term.unit == "cup"

    def test_pack_multiplier(self):
        """"2x 300g" means two 300g packs."""
        term = only_term("2x 300g baby spinach, washed")
        assert term.value == pytest.approx(600.0)
        assert term.unit == "gram"

    def test_pack_multiplier_name(self):
        assert parse_ingredient_line("2x 300g baby spinach").name == "baby spinach"


class TestOptionalMarkers:
    @pytest.mark.parametrize("line", [
        "optional: dijon mustard",
        "dijon mustard (optional)",
        "(optional) dijon mustard",
        "dijon mustard, optional",
        "dijon mustard - optional",
    ])
    def test_optional_is_detected_in_every_position(self, line):
        assert parse_ingredient_line(line).optional is True

    def test_leading_optional_does_not_block_the_quantity(self):
        """Regression: a leading "(optional)" hid the number from the parser."""
        term = only_term("(optional) 2-4 Tbsp shoyu")
        assert term.value == pytest.approx(3.0)
        assert term.unit == "tablespoon"
        assert parse_ingredient_line("(optional) 2-4 Tbsp shoyu").optional is True

    def test_optional_is_stripped_from_the_name(self):
        assert parse_ingredient_line("(optional) dijon mustard").name == "dijon mustard"

    def test_non_optional_line(self):
        assert parse_ingredient_line("2 cups flour").optional is False


class TestAnnotations:
    def test_leading_aside_is_captured_not_discarded(self):
        ingredient = parse_ingredient_line("(erin's mile-high) 1 Tbsp grand marnier")
        assert ingredient.annotation == "erin's mile-high"
        assert ingredient.name == "grand marnier"
        assert ingredient.representations[0].terms[0].unit == "tablespoon"

    def test_no_annotation_on_a_plain_line(self):
        assert parse_ingredient_line("2 cups flour").annotation is None

    def test_leading_bracket_holding_a_quantity_is_not_an_annotation(self):
        """"(15 oz) tomatoes" opens with a measurement, which is not an aside."""
        assert parse_ingredient_line("(15 oz) tomatoes").annotation is None


class TestAlternativeRepresentations:
    def test_parenthetical_metric_conversion(self):
        ingredient = parse_ingredient_line("1 cup (240ml) milk")
        assert len(ingredient.representations) == 2
        assert ingredient.representations[0].terms[0].unit == "cup"
        assert ingredient.representations[1].terms[0].unit == "milliliter"
        assert ingredient.name == "milk"

    def test_lenticular_bracket_conversion(self):
        ingredient = parse_ingredient_line("1 cup 【240 ml】 milk")
        assert len(ingredient.representations) == 2

    def test_descriptive_parenthetical_is_not_a_representation(self):
        ingredient = parse_ingredient_line("1 clove garlic (crushed or minced)")
        assert len(ingredient.representations) == 1

    def test_nested_container_capacity(self):
        term = only_term("2 cans (15 oz each)")
        assert term.unit == "can"
        assert term.nested_capacity is not None
        assert term.nested_capacity.unit == "ounce"


class TestNameAndModifier:
    @pytest.mark.parametrize("line, name", [
        ("2 cups flour", "flour"),
        ("225g self-raising flour", "self-raising flour"),
        ("1 onion, chopped fine", "onion"),
        ("225g [self-raising flour](self-raising-flour.html)", "self-raising flour"),
        ("salt", "salt"),
        ("black pepper to taste", "black pepper to taste"),
    ])
    def test_name_extraction(self, line, name):
        assert parse_ingredient_line(line).name == name

    def test_modifier_is_split_on_the_comma(self):
        assert parse_ingredient_line("1 onion, chopped fine").modifier == "chopped fine"

    def test_no_modifier_when_no_comma(self):
        assert parse_ingredient_line("2 cups flour").modifier is None

    def test_raw_line_is_preserved_verbatim(self):
        raw = "1-2 tsp butter, melted"
        assert parse_ingredient_line(raw).raw == raw


class TestWrappedLines:
    def test_a_wrapped_ingredient_keeps_its_quantity(self):
        """Regression: an embedded newline defeated every quantity pattern."""
        wrapped = "1.5 cups heavy whipping cream (DO NOT SUBSTITUTE - I've tried!\nThese biscuits will only rise with heavy cream)"
        term = only_term(wrapped)
        assert term.value == pytest.approx(1.5)
        assert term.unit == "cup"


class TestDegenerateInput:
    @pytest.mark.parametrize("line", ["", "   ", "\n", "\t"])
    def test_blank_lines_return_none(self, line):
        assert parse_ingredient_line(line) is None

    @pytest.mark.parametrize("line", [
        "salt",
        "a handful of parsley",
        "pepper?",
        "-",
        "...",
        "1",
        "(",
        "[unclosed",
        "* * *",
        "🥕",
    ])
    def test_degenerate_lines_do_not_raise(self, line):
        parse_ingredient_line(line)  # must not raise

    def test_list_marker_is_stripped(self):
        assert parse_ingredient_line("* 2 cups flour").name == "flour"

    def test_very_long_line_is_handled(self):
        line = "2 cups flour, " + ("very " * 2000) + "finely sifted"
        ingredient = parse_ingredient_line(line)
        assert ingredient.name == "flour"

    def test_html_comment_is_stripped(self):
        assert parse_ingredient_line("2 cups flour <!-- todo: weigh this -->").name == "flour"
