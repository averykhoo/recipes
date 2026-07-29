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
        "6cm pie tin",  # a dimension sizing an object
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


class TestMarkdownLinks:
    """A linked ingredient names itself in the link text; the target is a cross-reference.

    Regression: `[` opens an aside as far as the leading-parenthetical rule is concerned,
    so a line *starting* with a link had its link text read as an annotation and its URL
    left behind as the ingredient name. Six of the nine linked lines in the corpus were
    wrong; the three that were not are pinned here too.
    """

    @pytest.mark.parametrize("line, name", [
        # --- line-initial links: these were all corrupted -----------------------------
        ("[bolognese](ragu-alla-bolognese.md)", "bolognese"),
        ("[bechamel](../recipes/bechamel.md)", "bechamel"),
        ("[mornay](../bechamel.md) using parmesan", "mornay"),
        ("[Whipped cream for topping (optional)](chantilly-cream.md)", "Whipped cream for topping"),
        ("[Bird's Custard](https://en.wikipedia.org/wiki/Bird's_Custard) powder", "Bird's Custard powder"),
        # --- a leading quantity already shielded these; they must not regress ---------
        ("0.5 cup [piperade](./piperade-sauce.md), optionally blended", "piperade"),
        ("225g (1.6 cups) [self-raising flour](self-raising-flour.md), sifted", "self-raising flour"),
        ("3.5 cups [fresh cooked](#fresh-cooked-pumpkin-puree) or canned pumpkin (one 29-ounce can will do)",
         "fresh cooked or canned pumpkin"),
        ("2 [pie shells](./pie-crust.md), blind baked, 9-inch", "pie shells"),
    ])
    def test_link_text_becomes_the_name(self, line, name):
        assert parse_ingredient_line(line).name == name

    @pytest.mark.parametrize("line, target", [
        ("[bolognese](ragu-alla-bolognese.md)", "ragu-alla-bolognese.md"),
        ("[bechamel](../recipes/bechamel.md)", "../recipes/bechamel.md"),
        ("[mornay](../bechamel.md) using parmesan", "../bechamel.md"),
        ("[Whipped cream for topping (optional)](chantilly-cream.md)", "chantilly-cream.md"),
        ("[Bird's Custard](https://en.wikipedia.org/wiki/Bird's_Custard) powder",
         "https://en.wikipedia.org/wiki/Bird's_Custard"),
        ("0.5 cup [piperade](./piperade-sauce.md), optionally blended", "./piperade-sauce.md"),
        ("225g (1.6 cups) [self-raising flour](self-raising-flour.md), sifted", "self-raising-flour.md"),
        ("3.5 cups [fresh cooked](#fresh-cooked-pumpkin-puree) or canned pumpkin", "#fresh-cooked-pumpkin-puree"),
        ("2 [pie shells](./pie-crust.md), blind baked, 9-inch", "./pie-crust.md"),
    ])
    def test_link_target_is_kept(self, line, target):
        """The targets form the cross-reference graph between recipes; do not discard them."""
        assert parse_ingredient_line(line).link == target

    def test_no_link_leaves_the_field_empty(self):
        assert parse_ingredient_line("2 cups flour").link is None

    def test_a_linked_line_is_not_read_as_an_aside(self):
        assert parse_ingredient_line("[bolognese](ragu-alla-bolognese.md)").annotation is None

    def test_link_text_can_carry_the_optional_marker(self):
        ingredient = parse_ingredient_line("[Whipped cream for topping (optional)](chantilly-cream.md)")
        assert ingredient.optional is True

    def test_a_clause_after_the_link_is_a_modifier(self):
        """"using parmesan" says how the mornay is made; it is not part of its name."""
        assert parse_ingredient_line("[mornay](../bechamel.md) using parmesan").modifier == "using parmesan"

    def test_a_bare_noun_after_the_link_continues_the_name(self):
        """Unlike a clause, "powder" is simply the rest of what the ingredient is called."""
        ingredient = parse_ingredient_line("[Bird's Custard](https://example.com/custard) powder")
        assert ingredient.name == "Bird's Custard powder"
        assert ingredient.modifier is None

    def test_quantity_survives_a_linked_name(self):
        term = only_term("0.5 cup [piperade](./piperade-sauce.md), optionally blended")
        assert term.value == pytest.approx(0.5)
        assert term.unit == "cup"

    def test_link_target_containing_spaces(self):
        ingredient = parse_ingredient_line("[cookie notes](Chocolate Chip Cookies v9.docx)")
        assert ingredient.name == "cookie notes"
        assert ingredient.link == "Chocolate Chip Cookies v9.docx"

    def test_two_links_on_one_line_keep_the_first_target(self):
        ingredient = parse_ingredient_line("[ragu](ragu.md) and [bechamel](bechamel.md)")
        assert ingredient.name == "ragu and bechamel"
        assert ingredient.link == "ragu.md"

    @pytest.mark.parametrize("line", [
        "[whipped cream](chantilly-cream.md) with sugar (optional)",
        "[mornay](../bechamel.md) using parmesan, optional",
        "[cream](x.md) topped with nuts - optional",
    ])
    def test_a_clause_after_the_link_does_not_swallow_the_optional_marker(self, line):
        """
        Taking the clause truncates the line back to the link, and the marker used to
        travel with the discarded tail. The result was a *required* ingredient the recipe
        never wrote - the parser inventing an obligation out of an option.
        """
        assert parse_ingredient_line(line).optional is True

    def test_an_optional_marker_without_a_clause_still_works(self):
        """The no-clause path was already correct and must stay that way."""
        ingredient = parse_ingredient_line("[whipped cream](x.md) (optional)")
        assert ingredient.optional is True
        assert ingredient.name == "whipped cream"

    def test_the_clause_is_not_lost_to_a_comma_in_the_link_text(self):
        """
        A comma inside the link text produces a modifier of its own, and the clause after
        the link exists nowhere else once the line is truncated. Keeping only one of the
        two deleted "with sugar" without trace.
        """
        ingredient = parse_ingredient_line("[cream, whipped](x.md) with sugar")
        assert ingredient.name == "cream"
        assert ingredient.modifier == "whipped, with sugar"

    def test_a_parenthesised_url_is_not_truncated(self):
        """
        Wikipedia targets contain balanced parentheses. Stopping at the first ")" cut the
        URL short *and* left the survivor glued to the ingredient's name.
        """
        ingredient = parse_ingredient_line("[custard](https://en.wikipedia.org/wiki/Custard_(dessert))")
        assert ingredient.name == "custard"
        assert ingredient.link == "https://en.wikipedia.org/wiki/Custard_(dessert)"

    def test_the_parser_and_the_bare_url_rewriter_share_one_link_pattern(self):
        """Two spellings of the same construct drifted apart once; keep them identical."""
        from recipe_parser.rules.ingredients import RE_MARKDOWN_LINK
        from recipe_parser.rules.links import RE_MARKDOWN_LINK_OR_IMAGE
        assert RE_MARKDOWN_LINK is RE_MARKDOWN_LINK_OR_IMAGE


class TestLengthUnits:
    """Some ingredients are portioned by length, and some numbers only state a size."""

    @pytest.mark.parametrize("line, name, value, unit", [
        ("0.5-1 inch ginger", "ginger", 0.75, "inch"),
        ("1 inch ginger", "ginger", 1.0, "inch"),
        ("2 inches lemongrass", "lemongrass", 2.0, "inch"),
        ("3 cm ginger", "ginger", 3.0, "centimeter"),
        ("5 mm ginger", "ginger", 5.0, "millimeter"),
    ])
    def test_a_length_can_be_the_amount(self, line, name, value, unit):
        ingredient = parse_ingredient_line(line)
        term = only_term(line)
        assert ingredient.name == name
        assert term.value == pytest.approx(value)
        assert term.unit == unit
        assert term.unit_class == UnitClass.LENGTH

    def test_a_length_range_keeps_both_ends(self):
        term = only_term("0.5-1 inch ginger")
        assert term.value == pytest.approx(0.75)
        assert term.value_min == pytest.approx(0.5)
        assert term.value_max == pytest.approx(1.0)

    @pytest.mark.parametrize("line", [
        "9-inch pie shells",  # hyphenated: a compound adjective sizing the shells
        "10-inch nonstick skillet",
        "8 inches below tongs",  # positional, not an amount of anything
        "1 inch thick slices",  # describes the cut
        "2 inch pieces",  # sizes a countable piece
        "2 inches",  # a length with nothing after it measures nothing
    ])
    def test_a_length_that_only_states_a_size_is_not_an_amount(self, line):
        assert terms_of(line) == []

    @pytest.mark.parametrize("line, name", [
        # Hyphenated, so the whole compound survives untouched.
        ("9-inch pie shells", "9-inch pie shells"),
        ("10-inch nonstick skillet", "10-inch nonstick skillet"),
        # Space-separated, so the leading number is stripped even though no amount was
        # read, and the unit word is left stranded at the front of the name.
        ("8 inches below tongs", "inches below tongs"),
        ("2 inches", "inches"),
        ("1 inch thick slices", "inch thick slices"),
        ("2 inch pieces", "inch pieces"),
        ("6 inch tortillas", "inch tortillas"),
    ])
    def test_a_size_word_stays_in_the_text_it_describes(self, line, name):
        """
        Records what the name stripper actually does, which is not what it should do.

        A length word survives in the name whenever the line carried no length amount -
        that part is intended. The leading *number* does not: the no-length stripper
        removes it anyway, so "8 inches below tongs" loses its 8 and keeps its "inches".
        Only the hyphenated forms escape, and only because the dangling-hyphen check puts
        the whole compound back. Every space-separated line here is mildly mutilated, and
        the cases are listed so that a fix shows up as a failure rather than passing
        unnoticed.
        """
        assert parse_ingredient_line(line).name == name

    @pytest.mark.parametrize("line, name, value, unit", [
        # BUG 4: an allowlist decides which foods are portioned by length, so a length
        # reaches its ingredient through an intervening portion noun as well.
        ("1 inch piece of ginger", "ginger", 1.0, "inch"),
        ("2 inch piece ginger", "ginger", 2.0, "inch"),
        ("6cm piece of ginger", "ginger", 6.0, "centimeter"),
        ("4 inch piece of lemongrass", "lemongrass", 4.0, "inch"),
        ("2 inch cinnamon stick", "cinnamon stick", 2.0, "inch"),
        ("5 cm galangal", "galangal", 5.0, "centimeter"),
    ])
    def test_a_portion_noun_does_not_hide_the_length(self, line, name, value, unit):
        """""1 inch piece of ginger" is the commonest spelling and must not strand "inch"."""
        ingredient = parse_ingredient_line(line)
        term = only_term(line)
        assert ingredient.name == name
        assert term.value == pytest.approx(value)
        assert term.unit == unit
        assert term.unit_class == UnitClass.LENGTH

    @pytest.mark.parametrize("line", [
        "6 inch tortillas",  # the tortillas are six inches across, not six inches of them
        '24" pizza base',
        "1cm dice",  # a cut shape
        "2 cm flour",  # a typo for "2 c flour"; must not parse confidently as a length
        "500 mm milk",  # a typo for "500 ml"
        "9 inch pie shell",
        "12 inch skillet",
    ])
    def test_a_length_on_a_food_nobody_measures_by_length_is_a_size(self, line):
        """
        The dominant English reading of "N inch X" is how big X is, so an allowlist of
        foods genuinely portioned by length is the only route to an amount. Without it
        every size, and every "cm for c" / "mm for ml" typo, became a confident length.
        """
        assert terms_of(line) == []

    def test_the_allowlist_is_consulted_past_a_shape_word(self):
        """A geometric word still wins: this describes the cut, not how much ginger."""
        assert terms_of("1 inch thick slices of ginger") == []

    def test_a_hyphenated_weight_is_still_an_amount(self):
        """Only lengths are barred from crossing a hyphen: "6-pound pumpkin" still counts."""
        term = only_term("6-pound cheese pumpkin, halved")
        assert term.unit == "pound"

    def test_the_preposition_in_is_not_a_length_unit(self):
        """"in" is far more often the preposition; reading it as inches would be a disaster."""
        assert parse_ingredient_line("2 cups flour in a bowl").name == "flour in a bowl"


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
