"""Tests for range semantics.

A range is an interval, not a single number. Collapsing "1-2 tsp" to 1.5 and comparing
midpoints invents precision the recipe never claimed, so the comparison logic works on
intervals and treats any overlap as agreement.
"""

import pytest

from recipe_parser.models.schemas import Measurement
from recipe_parser.models.schemas import QuantityRepresentation
from recipe_parser.models.schemas import UnitClass
from recipe_parser.rules.ingredients import parse_ingredient_line
from recipe_parser.validation.linter import format_interval
from recipe_parser.validation.linter import interval_discrepancy
from recipe_parser.validation.linter import representation_gram_bounds


def grams(value, value_min=None, value_max=None):
    return Measurement(
        value=value, value_min=value_min, value_max=value_max,
        unit="gram", unit_class=UnitClass.WEIGHT,
    )


def representation(*terms):
    return QuantityRepresentation(raw_text="x", terms=list(terms))


class TestQualifierWords:
    """Hedge words in front of a quantity must not hide it."""

    @pytest.mark.parametrize("line, value, unit, name", [
        ("approximately 2 cups flour", 2.0, "cup", "flour"),
        ("about 3 tbsp oil", 3.0, "tablespoon", "oil"),
        ("roughly 3 cloves garlic", 3.0, "clove", "garlic"),
        ("a scant 1/2 cup sugar", 0.5, "cup", "sugar"),
        ("heaping 1 tbsp cocoa", 1.0, "tablespoon", "cocoa"),
        ("generous 250g butter", 250.0, "gram", "butter"),
    ])
    def test_qualifier_is_consumed(self, line, value, unit, name):
        ingredient = parse_ingredient_line(line)
        terms = [t for rep in ingredient.representations for t in rep.terms]
        assert len(terms) == 1
        assert terms[0].value == pytest.approx(value)
        assert terms[0].unit == unit
        assert ingredient.name == name

    @pytest.mark.parametrize("line, value, unit, name", [
        ("1 heaped Tbsp butter", 1.0, "tablespoon", "butter"),
        ("2 rounded tsp salt", 2.0, "teaspoon", "salt"),
        ("1 scant cup sugar", 1.0, "cup", "sugar"),
    ])
    def test_qualifier_between_number_and_unit(self, line, value, unit, name):
        """
        Regression: a hedge sitting between the number and the unit hid the unit
        completely, so "1 heaped Tbsp butter" became a bare count of 1 with the
        tablespoon lost and "heaped Tbsp" stuck in the name.
        """
        ingredient = parse_ingredient_line(line)
        terms = [t for rep in ingredient.representations for t in rep.terms]
        assert len(terms) == 1
        assert terms[0].value == pytest.approx(value)
        assert terms[0].unit == unit
        assert terms[0].implicit_unit is False
        assert ingredient.name == name

    @pytest.mark.parametrize("line, name", [
        ("2 large lemons", "large lemons"),
        ("2 small potatoes", "small potatoes"),
        ("3 medium onions", "medium onions"),
    ])
    def test_size_adjectives_are_not_treated_as_hedges(self, line, name):
        """"large" describes the ingredient and must stay in its name."""
        assert parse_ingredient_line(line).name == name

    def test_stranded_punctuation_is_trimmed_from_the_name(self):
        line = "Custard Powder (N.B. 1 TB = 2 Dessertspoons!):"
        assert parse_ingredient_line(line).name == "Custard Powder"

    def test_qualifier_in_front_of_a_range(self):
        """The hardest real case in the corpus: hedge + word-range + vulgar fraction."""
        ingredient = parse_ingredient_line("About 1 to 1½ cups (100-150 g) fresh bread crumbs")
        primary = ingredient.representations[0].terms[0]
        assert primary.value_min == pytest.approx(1.0)
        assert primary.value_max == pytest.approx(1.5)
        assert primary.unit == "cup"
        assert ingredient.name == "fresh bread crumbs"


class TestGramBounds:
    def test_scalar_collapses_to_a_point(self):
        assert representation_gram_bounds(representation(grams(100.0)), "flour") == (100.0, 100.0)

    def test_range_keeps_its_width(self):
        bounds = representation_gram_bounds(representation(grams(150.0, 100.0, 200.0)), "flour")
        assert bounds == (pytest.approx(100.0), pytest.approx(200.0))

    def test_additive_terms_sum_their_intervals(self):
        bounds = representation_gram_bounds(
            representation(grams(100.0), grams(15.0, 10.0, 20.0)), "flour"
        )
        assert bounds == (pytest.approx(110.0), pytest.approx(120.0))

    def test_unconvertible_terms_return_none(self):
        """A count of something with no known piece weight forms no interval at all."""
        count = Measurement(value=2.0, unit="count", unit_class=UnitClass.PIECE, implicit_unit=True)
        assert representation_gram_bounds(representation(count), "sprigs of thyme") is None

    def test_a_count_of_a_known_item_does_form_an_interval(self):
        """
        Once a piece weight is known, counts become checkable against stated masses -
        but the interval must carry the uncertainty of the piece weight, since lemons
        are not all the same size.
        """
        count = Measurement(value=2.0, unit="count", unit_class=UnitClass.PIECE, implicit_unit=True)
        bounds = representation_gram_bounds(representation(count), "lemons")
        assert bounds is not None
        low, high = bounds
        assert low < high, "a count of a variable-sized item must not claim an exact mass"
        assert low == pytest.approx(116.0) and high == pytest.approx(240.0)

    def test_empty_representation_returns_none(self):
        assert representation_gram_bounds(representation(), "flour") is None


class TestIntervalDiscrepancy:
    def test_identical_points_agree(self):
        assert interval_discrepancy((100.0, 100.0), (100.0, 100.0)) == 0.0

    def test_overlapping_ranges_agree_completely(self):
        """4-6 cups vs 1-1.5 litres overlap, so there is nothing to report."""
        assert interval_discrepancy((960.0, 1440.0), (1000.0, 1500.0)) == 0.0

    def test_a_scalar_inside_a_range_agrees(self):
        assert interval_discrepancy((100.0, 200.0), (150.0, 150.0)) == 0.0

    def test_touching_intervals_agree(self):
        assert interval_discrepancy((100.0, 150.0), (150.0, 200.0)) == 0.0

    def test_disjoint_intervals_report_the_gap(self):
        # gap is 200 -> 250, i.e. 50, relative to the larger bound 300
        assert interval_discrepancy((100.0, 200.0), (250.0, 300.0)) == pytest.approx(50.0 / 300.0)

    def test_order_does_not_matter(self):
        a, b = (100.0, 200.0), (250.0, 300.0)
        assert interval_discrepancy(a, b) == interval_discrepancy(b, a)

    def test_scalar_disagreement_matches_relative_difference(self):
        """With zero-width intervals this reduces to the old relative-difference rule."""
        assert interval_discrepancy((200.0, 200.0), (100.0, 100.0)) == pytest.approx(0.5)

    def test_a_wide_range_absorbs_a_scalar_that_a_midpoint_would_have_flagged(self):
        """
        Regression guard for the whole point of interval comparison: midpoint of
        100-200 is 150, which differs from 195 by 30% and would have been reported,
        even though 195 is squarely inside the stated range.
        """
        assert interval_discrepancy((100.0, 200.0), (195.0, 195.0)) == 0.0


class TestPerUnitAlternatives:
    """"4 eggs (60g each)" states the size of one egg, not the total for four."""

    def test_each_marks_the_representation_as_per_unit(self):
        ingredient = parse_ingredient_line("4 large eggs (60g each)")
        assert ingredient.representations[1].per_unit is True

    def test_a_plain_bracket_is_not_per_unit(self):
        ingredient = parse_ingredient_line("1 cup (240ml) milk")
        assert ingredient.representations[1].per_unit is False

    @pytest.mark.parametrize("line", [
        "4 large eggs (60g each)",
        "3 large (60g) eggs",
        "4 yolks from large-ish (50-60g) eggs",
    ])
    def test_per_item_sizes_do_not_report_a_discrepancy(self, line):
        """
        Both the explicit "each" and the omitted-"each" forms must reconcile. Read as a
        total, 60g of four eggs is impossible; read per item it is exactly right.
        """
        from recipe_parser.models.schemas import BlockType
        from recipe_parser.models.schemas import IngredientItem
        from recipe_parser.models.schemas import ListBlock
        from recipe_parser.models.schemas import Recipe
        from recipe_parser.validation.diagnostics import Code
        from recipe_parser.validation.linter import lint_recipe_document

        block = ListBlock(section_type="ingredients", items=[
            IngredientItem(raw_line=line, parsed_ingredient=parse_ingredient_line(line))
        ])
        recipe = Recipe(title="t", blocks=[block])
        assert [d.code for d in lint_recipe_document(recipe)
                if d.code == Code.CONVERSION_DISCREPANCY] == []

    def test_an_impossible_mass_is_still_reported(self):
        """Reinterpretation must not become a way to explain away any number at all."""
        from recipe_parser.models.schemas import IngredientItem
        from recipe_parser.models.schemas import ListBlock
        from recipe_parser.models.schemas import Recipe
        from recipe_parser.validation.diagnostics import Code
        from recipe_parser.validation.linter import lint_recipe_document

        line = "4 large eggs (5000g)"
        block = ListBlock(section_type="ingredients", items=[
            IngredientItem(raw_line=line, parsed_ingredient=parse_ingredient_line(line))
        ])
        recipe = Recipe(title="t", blocks=[block])
        assert Code.CONVERSION_DISCREPANCY in [d.code for d in lint_recipe_document(recipe)]


class TestIntervalFormatting:
    def test_point_interval_renders_as_one_number(self):
        assert format_interval((100.0, 100.0)) == "100.0g"

    def test_range_interval_renders_both_ends(self):
        assert format_interval((100.0, 200.0)) == "100.0-200.0g"
