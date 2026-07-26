"""Document-level parsing tests: structure, section routing, yields, and robustness.

These drive `process_recipe_document` end to end over markdown snippets written to
``tmp_path``. Assertions target *structure* - block sequence, `section_type`, item
types, diagnostic codes - never human-readable message wording, which is expected to
be reworded freely.
"""

import pytest

from conftest import by_code
from conftest import codes
from conftest import headings_of
from conftest import lists_of
from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import IngredientItem
from recipe_parser.rules.yields import extract_strict_yield
from recipe_parser.rules.yields import find_lax_yield_candidate
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Severity

WELL_FORMED = """
    # Chocolate Cake

    A rich, dark cake for birthdays.

    ## Ingredients

    * 2 cups all-purpose flour
    * 1 cup granulated sugar

    ## Directions

    1. Mix the dry goods.
    2. Bake until done.

    ## Notes

    Keeps for a week in a tin.
    """


# =====================================================================================
# Structure and routing
# =====================================================================================

class TestWellFormedStructure:
    """The happy path: one H1, a preamble, then the three canonical sections."""

    def test_single_recipe_with_expected_title(self, parse):
        doc, _ = parse(WELL_FORMED)
        assert len(doc.recipes) == 1
        assert doc.recipes[0].title == "Chocolate Cake"

    def test_block_sequence(self, parse):
        doc, _ = parse(WELL_FORMED)
        recipe = doc.recipes[0]

        # The H1 is consumed as the title and does not reappear as a block.
        assert [b.block_type for b in recipe.blocks] == [
            BlockType.TEXT,  # preamble paragraph
            BlockType.HEADING,  # ## Ingredients
            BlockType.LIST,
            BlockType.HEADING,  # ## Directions
            BlockType.LIST,
            BlockType.HEADING,  # ## Notes
            BlockType.TEXT,
        ]

    def test_heading_sections_and_components(self, parse):
        doc, _ = parse(WELL_FORMED)
        headings = headings_of(doc.recipes[0])

        assert [(h.text, h.section_type, h.component) for h in headings] == [
            ("Ingredients", "ingredients", "Main"),
            ("Directions", "directions", "Main"),
            ("Notes", "notes", None),
        ]

    def test_list_sections_and_item_types(self, parse):
        doc, _ = parse(WELL_FORMED)
        ingredients, directions = lists_of(doc.recipes[0])

        assert ingredients.section_type == "ingredients"
        assert ingredients.ordered is False
        assert ingredients.inferred_section is False
        assert all(isinstance(i, IngredientItem) for i in ingredients.items)
        assert [i.raw_line for i in ingredients.items] == [
            "2 cups all-purpose flour",
            "1 cup granulated sugar",
        ]

        assert directions.section_type == "directions"
        assert directions.ordered is True
        assert directions.inferred_section is False
        assert all(isinstance(i, str) for i in directions.items)
        assert directions.items == ["Mix the dry goods.", "Bake until done."]

    def test_well_formed_recipe_is_diagnostic_clean(self, parse):
        _, diagnostics = parse(WELL_FORMED)
        assert codes(diagnostics) == []


@pytest.mark.parametrize("heading", ["Directions", "Instructions", "Method"])
def test_directions_heading_synonyms(parse, heading):
    doc, _ = parse(f"""
        # X

        ## Ingredients

        * 1 cup water

        ## {heading}

        1. Boil it.
        """)
    recipe = doc.recipes[0]

    steps = [h for h in headings_of(recipe) if h.text == heading][0]
    assert steps.section_type == "directions"
    assert steps.component == "Main"

    directions_list = [b for b in lists_of(recipe) if b.section_type == "directions"]
    assert len(directions_list) == 1
    assert directions_list[0].items == ["Boil it."]


@pytest.mark.parametrize("raw_heading,expected", [
    ("## Ingredients:", "Ingredients"),
    ("## Directions:", "Directions"),
    ("## Ingredients for the sauce:", "Ingredients for the sauce"),
    ("## Notes:", "Notes"),
])
def test_trailing_colons_are_stripped_from_headings(parse, raw_heading, expected):
    doc, _ = parse(f"# X\n\n{raw_heading}\n\n* 1 cup water\n")
    heading = headings_of(doc.recipes[0])[0]
    assert heading.text == expected


def test_trailing_colon_heading_still_routes_to_its_section(parse):
    doc, _ = parse("""
        # X

        ## Ingredients:

        * 1 cup water

        ## Method:

        1. Boil it.
        """)
    recipe = doc.recipes[0]
    assert [h.section_type for h in headings_of(recipe)] == ["ingredients", "directions"]
    assert [b.section_type for b in lists_of(recipe)] == ["ingredients", "directions"]


class TestComponents:
    """`## Ingredients for X` names a sub-component; a bare heading is the Main one."""

    def test_named_component_on_heading_and_list(self, parse):
        doc, _ = parse("""
            # X

            ## Ingredients for the dough

            * 2 cups flour

            ## Directions for the dough

            1. Knead it.
            """)
        recipe = doc.recipes[0]

        assert [(h.section_type, h.component) for h in headings_of(recipe)] == [
            ("ingredients", "the dough"),
            ("directions", "the dough"),
        ]
        assert [(b.section_type, b.component) for b in lists_of(recipe)] == [
            ("ingredients", "the dough"),
            ("directions", "the dough"),
        ]

    def test_bare_heading_gets_main_component(self, parse):
        doc, _ = parse("""
            # X

            ## Ingredients

            * 2 cups flour

            ## Directions

            1. Knead it.
            """)
        recipe = doc.recipes[0]
        assert {h.component for h in headings_of(recipe)} == {"Main"}
        assert {b.component for b in lists_of(recipe)} == {"Main"}

    def test_multiple_components_stay_separate(self, parse):
        doc, _ = parse("""
            # X

            ## Ingredients for the dough

            * 2 cups flour

            ## Directions for the dough

            1. Knead.

            ## Ingredients for the filling

            * 1 cup jam

            ## Directions for the filling

            1. Spread.
            """)
        recipe = doc.recipes[0]
        assert [b.component for b in lists_of(recipe)] == [
            "the dough", "the dough", "the filling", "the filling",
        ]


class TestH3Inheritance:
    """Regression guard: an H3 inherits the enclosing H2's section.

    Before the fix, an ingredients list nested under an `### For the sauce`
    sub-heading was silently reclassified as notes, so its items were kept as bare
    strings and every ingredient-level check skipped it.
    """

    SNIPPET = """
        # X

        ## Ingredients

        ### For the sauce

        * 2 tablespoons soy sauce
        * 1 clove garlic

        ### For the garnish

        * 1 bunch spring onions

        ## Directions

        1. Cook it.
        """

    def test_h3_heading_inherits_ingredients_section(self, parse):
        doc, _ = parse(self.SNIPPET)
        sub_headings = [h for h in headings_of(doc.recipes[0]) if h.level == 3]

        assert [h.text for h in sub_headings] == ["For the sauce", "For the garnish"]
        assert all(h.section_type == "ingredients" for h in sub_headings)
        assert all(h.component == "Main" for h in sub_headings)

    def test_list_under_h3_is_parsed_as_ingredients(self, parse):
        doc, _ = parse(self.SNIPPET)
        ingredient_lists = [b for b in lists_of(doc.recipes[0]) if not b.ordered]

        assert len(ingredient_lists) == 2
        for block in ingredient_lists:
            assert block.section_type == "ingredients"
            assert block.section_type != "notes"
            assert block.items, "sub-heading list lost its items"
            assert all(isinstance(i, IngredientItem) for i in block.items)
            assert all(i.parsed_ingredient is not None for i in block.items)

    def test_h3_inherits_named_component(self, parse):
        doc, _ = parse("""
            # X

            ## Ingredients for the sauce

            ### The aromatics

            * 1 clove garlic

            ## Directions for the sauce

            1. Cook it.
            """)
        recipe = doc.recipes[0]
        h3 = [h for h in headings_of(recipe) if h.level == 3][0]
        assert h3.section_type == "ingredients"
        assert h3.component == "the sauce"

        ingredients = [b for b in lists_of(recipe) if b.section_type == "ingredients"][0]
        assert ingredients.component == "the sauce"

    def test_h3_before_any_h2_does_not_claim_ingredients(self, parse):
        """An H3 with no enclosing H2 has nothing to inherit; it must not guess."""
        doc, diagnostics = parse("""
            # X

            ### Random sub heading

            * 1 cup flour

            ## Directions

            1. Cook it.
            """)
        recipe = doc.recipes[0]

        h3 = [h for h in headings_of(recipe) if h.level == 3][0]
        assert h3.section_type == "notes"
        assert h3.section_type != "ingredients"
        assert h3.component is None

        orphan_list = lists_of(recipe)[0]
        assert orphan_list.section_type == "notes"
        assert orphan_list.section_type != "ingredients"
        assert all(isinstance(i, str) for i in orphan_list.items)

        # ... and the document is correctly reported as having no ingredients section.
        assert Code.MISSING_INGREDIENTS in codes(diagnostics)


class TestPreambleLists:
    """Regression guard: a bullet list above the first `## ` is front matter, not food."""

    SNIPPET = """
        # X

        * yields 4 servings
        * from grandma

        ## Ingredients

        * 1 cup water

        ## Directions

        1. Cook it.
        """

    def test_preamble_list_section_type(self, parse):
        doc, _ = parse(self.SNIPPET)
        first_list = lists_of(doc.recipes[0])[0]

        assert first_list.section_type == "preamble"
        assert first_list.section_type != "ingredients"
        assert first_list.inferred_section is False

    def test_preamble_list_items_are_not_ingredients(self, parse):
        doc, _ = parse(self.SNIPPET)
        first_list = lists_of(doc.recipes[0])[0]

        assert all(isinstance(i, str) for i in first_list.items)
        assert not any(isinstance(i, IngredientItem) for i in first_list.items)
        assert first_list.items == ["yields 4 servings", "from grandma"]

    def test_real_ingredients_still_route_correctly(self, parse):
        doc, diagnostics = parse(self.SNIPPET)
        ingredient_lists = [b for b in lists_of(doc.recipes[0]) if b.section_type == "ingredients"]

        assert len(ingredient_lists) == 1
        assert [i.raw_line for i in ingredient_lists[0].items] == ["1 cup water"]
        assert Code.MISSING_INGREDIENTS not in codes(diagnostics)


class TestMultiRecipeSplitting:
    """`---` splits a file into sibling recipes only when an H1 follows it."""

    def test_hr_before_h1_splits(self, parse):
        doc, _ = parse("""
            # First Recipe

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.

            ---

            # Second Recipe

            ## Ingredients

            * 1 cup milk

            ## Directions

            1. Warm.
            """)
        assert [r.title for r in doc.recipes] == ["First Recipe", "Second Recipe"]
        for recipe in doc.recipes:
            assert [b.section_type for b in lists_of(recipe)] == ["ingredients", "directions"]

    def test_three_way_split(self, parse):
        doc, _ = parse("""
            # One

            Alpha.

            ---

            # Two

            Beta.

            ---

            # Three

            Gamma.
            """)
        assert [r.title for r in doc.recipes] == ["One", "Two", "Three"]

    def test_hr_not_followed_by_h1_does_not_split(self, parse):
        doc, _ = parse("""
            # Only Recipe

            ## Ingredients

            * 1 cup water

            ---

            ## Directions

            1. Boil.
            """)
        assert len(doc.recipes) == 1
        assert doc.recipes[0].title == "Only Recipe"
        assert [b.section_type for b in lists_of(doc.recipes[0])] == ["ingredients", "directions"]

    def test_hr_followed_by_h2_does_not_split(self, parse):
        doc, _ = parse("""
            # Only Recipe

            Intro.

            ---

            ## Notes

            Trailing thoughts.
            """)
        assert len(doc.recipes) == 1


def test_heading_inside_fenced_code_block_is_not_a_title(parse):
    """A `# ...` line inside a fence is code. The corpus has a recipe relying on this."""
    doc, _ = parse("""
        # Real Title

        ```
        # not a title
        ## not a section either
        ```

        ## Ingredients

        * 1 cup water

        ## Directions

        1. Cook it.
        """)

    assert len(doc.recipes) == 1
    assert doc.recipes[0].title == "Real Title"

    heading_texts = [h.text for h in headings_of(doc.recipes[0])]
    assert "not a title" not in heading_texts
    assert "not a section either" not in heading_texts
    assert heading_texts == ["Ingredients", "Directions"]


def test_hr_and_h1_inside_fenced_code_block_do_not_split(parse):
    doc, _ = parse("""
        # Real Title

        ```
        ---
        # decoy recipe
        ```

        ## Ingredients

        * 1 cup water
        """)
    assert [r.title for r in doc.recipes] == ["Real Title"]


# =====================================================================================
# Headerless fallback
# =====================================================================================

HEADERLESS = """
    # Headerless Recipe

    * 1 cup flour
    * 1 cup water

    1. Combine them.
    2. Bake.

    * Best eaten warm.
    * Freezes badly.
    """


class TestHeaderlessFallback:
    """With no `##` headings the only signal is list style."""

    def test_sections_inferred_from_list_style(self, parse):
        doc, _ = parse(HEADERLESS)
        first, second, third = lists_of(doc.recipes[0])

        assert (first.ordered, first.section_type) == (False, "ingredients")
        assert (second.ordered, second.section_type) == (True, "directions")
        # A bullet list *after* directions is commentary, not more ingredients.
        assert (third.ordered, third.section_type) == (False, "notes")
        assert third.section_type != "ingredients"

    def test_first_bullet_list_holds_ingredient_items(self, parse):
        doc, _ = parse(HEADERLESS)
        first = lists_of(doc.recipes[0])[0]
        assert all(isinstance(i, IngredientItem) for i in first.items)
        assert [i.raw_line for i in first.items] == ["1 cup flour", "1 cup water"]

    def test_trailing_bullet_list_holds_plain_strings(self, parse):
        doc, _ = parse(HEADERLESS)
        third = lists_of(doc.recipes[0])[2]
        assert all(isinstance(i, str) for i in third.items)
        assert third.items == ["Best eaten warm.", "Freezes badly."]

    def test_every_block_is_flagged_as_inferred(self, parse):
        doc, _ = parse(HEADERLESS)
        assert all(b.inferred_section is True for b in lists_of(doc.recipes[0]))

    def test_no_section_headings_diagnostic_is_raised(self, parse):
        _, diagnostics = parse(HEADERLESS)
        found = by_code(diagnostics, Code.NO_SECTION_HEADINGS)
        assert len(found) == 1
        assert found[0].severity == Severity.WARNING
        assert found[0].recipe == "Headerless Recipe"

    def test_section_inferred_info_raised_per_list(self, parse):
        _, diagnostics = parse(HEADERLESS)
        inferred = by_code(diagnostics, Code.SECTION_INFERRED)
        assert len(inferred) == 3
        assert all(d.severity == Severity.INFO for d in inferred)

    def test_headed_document_never_flags_inferred_sections(self, parse):
        _, diagnostics = parse(WELL_FORMED)
        assert Code.NO_SECTION_HEADINGS not in codes(diagnostics)
        assert Code.SECTION_INFERRED not in codes(diagnostics)


# =====================================================================================
# Yields
#
# Coverage is split deliberately: the extraction *rules* are tested directly against
# parsed blocks, and the hand-off into `Recipe.yield_val` is tested separately, because
# that hand-off was silently broken for the entire corpus until the alias fix.
# =====================================================================================

def _preamble_blocks(recipe):
    """The blocks the orchestrator considers preamble: everything before the first H2."""
    preamble = []
    for block in recipe.blocks:
        if block.block_type == BlockType.HEADING and block.level == 2:
            break
        preamble.append(block)
    return preamble


SERVES_FOUR = """
    # Yield Recipe

    Serves 4

    ## Ingredients

    * 1 cup water

    ## Directions

    1. Boil.
    """


class TestStrictYield:
    """A yield line in the preamble is read directly, with nothing reported."""

    @pytest.mark.parametrize("line,expected", [
        ("Serves 4", "Serves 4"),
        ("Yields 12 cookies", "Yields 12 cookies"),
        ("Makes 16 meatballs", "Makes 16 meatballs"),
        ("Serves 4-6", "Serves 4-6"),
    ])
    def test_preamble_yield_is_extracted_from_parsed_blocks(self, parse, line, expected):
        doc, _ = parse(f"""
            # Y

            {line}

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.
            """)
        recipe = doc.recipes[0]
        assert extract_strict_yield(_preamble_blocks(recipe), doc.metadata) == expected

    @pytest.mark.parametrize("line", ["Serves 4", "Yields 12 cookies"])
    def test_preamble_yield_raises_no_diagnostic(self, parse, line):
        _, diagnostics = parse(f"""
            # Y

            {line}

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.
            """)
        assert Code.YIELD_INFERRED not in codes(diagnostics)
        assert codes(diagnostics) == []

    def test_preamble_yield_reaches_the_model(self, parse):
        """
        Regression: `yield_val` is aliased to "yield", and without populate_by_name
        Pydantic v2 silently discarded the orchestrator's keyword, leaving every
        recipe in the corpus with no yield at all.
        """
        doc, _ = parse(SERVES_FOUR)
        assert doc.recipes[0].yield_val == "Serves 4"

    def test_frontmatter_yield_reaches_the_model(self, parse):
        doc, _ = parse("""
            ---
            yield: 6 servings
            ---

            # Y

            ## Ingredients

            * 1 cup water
            """)
        assert doc.recipes[0].yield_val == "6 servings"

    def test_frontmatter_yield_is_preserved_in_metadata(self, parse):
        doc, _ = parse("""
            ---
            yield: 6 servings
            ---

            # Y

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.
            """)
        assert doc.metadata["yield"] == "6 servings"
        assert extract_strict_yield([], doc.metadata) == "6 servings"


class TestLaxYield:
    """A yield-looking line further down is used, but flagged."""

    LATE_YIELD = """
        # Late Yield

        ## Ingredients

        * 1 cup water

        ## Directions

        1. Boil.

        ## Notes

        Makes 24 cookies
        """

    def test_yield_inferred_info_diagnostic(self, parse):
        _, diagnostics = parse(self.LATE_YIELD)
        found = by_code(diagnostics, Code.YIELD_INFERRED)

        assert len(found) == 1
        assert found[0].severity == Severity.INFO
        assert found[0].code == Code.YIELD_INFERRED
        assert found[0].recipe == "Late Yield"
        assert found[0].context == "Makes 24 cookies"

    def test_lax_candidate_found_on_parsed_blocks(self, parse):
        doc, _ = parse(self.LATE_YIELD)
        assert find_lax_yield_candidate(doc.recipes[0].blocks) == "Makes 24 cookies"


class TestServeIsNotAYield:
    """`Serve immediately` is an instruction, not a portion count."""

    @pytest.mark.parametrize("line", [
        "Serve immediately",
        "Serve with rice",
        "Serve hot",
        "Serve alongside a green salad",
        "To serve, spoon over noodles",
    ])
    def test_serving_suggestion_is_not_mistaken_for_a_yield(self, parse, line):
        doc, diagnostics = parse(f"""
            # No Yield

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.

            ## Notes

            {line}
            """)
        recipe = doc.recipes[0]

        assert Code.YIELD_INFERRED not in codes(diagnostics)
        assert find_lax_yield_candidate(recipe.blocks) is None
        assert extract_strict_yield(_preamble_blocks(recipe), doc.metadata) is None

    def test_serving_suggestion_in_preamble_is_not_a_yield(self, parse):
        doc, diagnostics = parse("""
            # No Yield

            Serve immediately.

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.
            """)
        recipe = doc.recipes[0]
        assert extract_strict_yield(_preamble_blocks(recipe), doc.metadata) is None
        assert Code.YIELD_INFERRED not in codes(diagnostics)


# =====================================================================================
# Malformed / adversarial input - none of this may raise
# =====================================================================================

LONG_INGREDIENT = "1 cup " + ("verylongingredientname " * 250)

MALFORMED_CASES = [
    ("empty_file", ""),
    ("whitespace_only", "   \n\n\t\n     \n"),
    ("title_only", "# Just A Title\n"),
    ("no_h1", "## Ingredients\n\n* 1 cup water\n\n## Directions\n\n1. Boil.\n"),
    ("h1_only_hash", "#\n\n* 1 cup water\n"),
    ("unclosed_emphasis", "# X\n\nThis is *unclosed and **this too.\n\n## Ingredients\n\n* 1 cup *water\n"),
    ("unclosed_code_fence", "# X\n\n```\nsome code\n## Ingredients\n\n* 1 cup water\n"),
    ("unclosed_inline_code", "# X\n\nA `backtick that never closes.\n\n## Ingredients\n\n* 1 cup water\n"),
    ("unbalanced_brackets", "# X\n\n## Ingredients\n\n* 1 cup [water](\n* [broken\n\n## Directions\n\n1. See [here](\n"),
    ("empty_heading", "# X\n\n##\n\n## Ingredients\n\n* 1 cup water\n\n##\n"),
    ("duplicated_headings",
     "# X\n\n## Ingredients\n\n* 1 cup water\n\n## Ingredients\n\n* 2 cups flour\n\n"
     "## Directions\n\n1. Boil.\n\n## Directions\n\n1. Again.\n"),
    ("ingredients_with_no_list", "# X\n\n## Ingredients\n\n## Directions\n\n1. Boil.\n"),
    ("empty_list_item", "# X\n\n## Ingredients\n\n*\n* 1 cup water\n*\n"),
    ("link_only_list_item", "# X\n\n## Ingredients\n\n* [just a link](http://example.com)\n"),
    ("deeply_nested_list",
     "# X\n\n## Ingredients\n\n* one\n  * two\n    * three\n      * four\n        * five\n"),
    ("ragged_table",
     "# X\n\n## Ingredients\n\n| Item | Amount | Note |\n| --- | --- | --- |\n"
     "| flour | 1 cup |\n| sugar | 1 cup | fine |\n"),
    ("table_with_no_rows", "# X\n\n## Ingredients\n\n| Item | Amount |\n| --- | --- |\n"),
    ("very_long_ingredient", f"# X\n\n## Ingredients\n\n* {LONG_INGREDIENT}\n\n## Directions\n\n1. Boil.\n"),
    ("crlf_line_endings", "# X\r\n\r\n## Ingredients\r\n\r\n* 1 cup water\r\n\r\n## Directions\r\n\r\n1. Boil.\r\n"),
    ("frontmatter_only", "---\ntitle: Something\nyield: 4 servings\n---\n"),
    ("frontmatter_with_no_body", "---\ntitle: Something\n---\n\n\n"),
    ("hr_only", "---\n\n---\n\n---\n"),
    ("nothing_but_a_list", "* 1 cup water\n* 2 eggs\n"),
    ("heading_levels_skipped", "# X\n\n###### Deep\n\n* 1 cup water\n"),
    ("blockquote_only", "# X\n\n> A quoted thought.\n"),
]

BOM_DOCUMENT = "﻿# X\n\n## Ingredients\n\n* 1 cup water\n\n## Directions\n\n1. Boil.\n".encode("utf-8")


@pytest.mark.parametrize("case_id,content", MALFORMED_CASES, ids=[c[0] for c in MALFORMED_CASES])
def test_malformed_input_does_not_crash(parse, case_id, content):
    """The parser is deliberately lenient: it reports, it never refuses."""
    doc, diagnostics = parse(content, dedent=False, newline="")

    assert doc is not None
    assert isinstance(doc.recipes, list)
    assert isinstance(diagnostics, list)
    for recipe in doc.recipes:
        assert isinstance(recipe.title, str)
        assert isinstance(recipe.blocks, list)
    for diagnostic in diagnostics:
        assert isinstance(diagnostic.code, str) and diagnostic.code
        assert diagnostic.severity in tuple(Severity)


def test_bom_document_does_not_crash(parse):
    doc, diagnostics = parse(BOM_DOCUMENT)
    assert doc is not None
    assert isinstance(diagnostics, list)


class TestMalformedSpecificBehaviour:
    """Targeted assertions where the behaviour on bad input is well defined."""

    @pytest.mark.parametrize("content", ["", "   \n\n\t\n   \n"])
    def test_empty_document_yields_no_recipes(self, parse, content):
        doc, diagnostics = parse(content, dedent=False)
        assert doc.recipes == []
        assert diagnostics == []

    def test_title_only_document_has_a_recipe_with_no_blocks(self, parse):
        doc, diagnostics = parse("# Just A Title\n", dedent=False)
        assert len(doc.recipes) == 1
        assert doc.recipes[0].title == "Just A Title"
        assert doc.recipes[0].blocks == []
        # Nothing to complain about: there is no content to be missing sections from.
        assert codes(diagnostics) == []

    def test_empty_h1_falls_back_to_a_positional_title(self, parse):
        """A bare "#" is not a usable title, so the positional fallback must still apply."""
        doc, _ = parse("#\n\n* 1 cup water\n", dedent=False)
        assert len(doc.recipes) == 1
        assert doc.recipes[0].title == "Recipe 1"
        assert lists_of(doc.recipes[0])[0].section_type == "ingredients"

    def test_document_with_no_h1_gets_a_positional_title(self, parse):
        doc, _ = parse("""
            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil.
            """)
        assert len(doc.recipes) == 1
        assert doc.recipes[0].title == "Recipe 1"
        assert [b.section_type for b in lists_of(doc.recipes[0])] == ["ingredients", "directions"]

    def test_unclosed_emphasis_keeps_the_text_verbatim(self, parse):
        doc, _ = parse("# X\n\n## Ingredients\n\n* 1 cup *water\n", dedent=False)
        ingredients = lists_of(doc.recipes[0])[0]
        assert ingredients.items[0].raw_line == "1 cup *water"

    def test_unclosed_code_fence_swallows_the_rest_without_crashing(self, parse):
        doc, diagnostics = parse("# X\n\n```\ncode\n## Ingredients\n\n* 1 cup water\n", dedent=False)
        recipe = doc.recipes[0]
        assert recipe.title == "X"
        # Everything after the opening fence is code, so no sections survive.
        assert recipe.blocks == []
        assert codes(diagnostics) == []

    def test_unbalanced_brackets_survive_as_literal_text(self, parse):
        doc, _ = parse("# X\n\n## Ingredients\n\n* 1 cup [water](\n* [broken\n", dedent=False)
        ingredients = lists_of(doc.recipes[0])[0]
        assert [i.raw_line for i in ingredients.items] == ["1 cup [water](", "[broken"]

    def test_empty_heading_becomes_an_empty_notes_heading(self, parse):
        doc, _ = parse("# X\n\n##\n\n## Ingredients\n\n* 1 cup water\n", dedent=False)
        headings = headings_of(doc.recipes[0])
        assert headings[0].text == ""
        # An unrecognised H2 closes any open section and is treated as commentary.
        assert headings[0].section_type == "notes"
        assert headings[0].component is None

    def test_duplicated_headings_both_route_to_their_section(self, parse):
        doc, _ = parse("""
            # X

            ## Ingredients

            * 1 cup water

            ## Ingredients

            * 2 cups flour

            ## Directions

            1. Boil.

            ## Directions

            1. Again.
            """)
        recipe = doc.recipes[0]
        assert [b.section_type for b in lists_of(recipe)] == [
            "ingredients", "ingredients", "directions", "directions",
        ]

    def test_ingredients_heading_with_no_list_produces_no_list_block(self, parse):
        doc, diagnostics = parse("""
            # X

            ## Ingredients

            ## Directions

            1. Boil.
            """)
        recipe = doc.recipes[0]
        ingredient_lists = [b for b in lists_of(recipe) if b.section_type == "ingredients"]
        assert ingredient_lists == []
        # The heading exists, so "missing ingredients section" must not fire.
        assert Code.MISSING_INGREDIENTS not in codes(diagnostics)

    def test_empty_list_items_are_dropped(self, parse):
        doc, _ = parse("# X\n\n## Ingredients\n\n*\n* 1 cup water\n*\n", dedent=False)
        ingredients = lists_of(doc.recipes[0])[0]
        assert [i.raw_line for i in ingredients.items] == ["1 cup water"]

    def test_link_only_list_item_is_kept(self, parse):
        doc, _ = parse("# X\n\n## Ingredients\n\n* [just a link](http://example.com)\n", dedent=False)
        ingredients = lists_of(doc.recipes[0])[0]
        assert len(ingredients.items) == 1
        assert "just a link" in ingredients.items[0].raw_line

    def test_deeply_nested_list_is_flattened(self, parse):
        doc, _ = parse(
            "# X\n\n## Ingredients\n\n* one\n  * two\n    * three\n      * four\n        * five\n",
            dedent=False,
        )
        ingredients = lists_of(doc.recipes[0])[0]
        assert [i.raw_line for i in ingredients.items] == ["one", "two", "three", "four", "five"]

    def test_siblings_after_a_nested_sublist_survive(self, parse):
        """
        Regression: the token walker stopped at the first list-close of the matching
        kind, which is the *inner* list's close. Everything after the first nested
        sublist was dropped, and the remainder resurfaced as stray empty list blocks.
        A pure descent (one -> two -> three) hid this, because there was nothing after
        the nesting to lose.
        """
        doc, _ = parse(
            "# X\n\n## Ingredients\n\n"
            "* first\n"
            "    * nested under first\n"
            "* second\n"
            "* third\n"
            "    * nested under third\n"
            "* fourth\n",
            dedent=False,
        )
        lists = lists_of(doc.recipes[0])
        assert len(lists) == 1, "the list must not be split into fragments"
        assert [i.raw_line for i in lists[0].items] == [
            "first", "nested under first", "second",
            "third", "nested under third", "fourth",
        ]

    def test_nesting_does_not_emit_empty_list_blocks(self, parse):
        doc, _ = parse(
            "# X\n\n## Ingredients\n\n* a\n    * a1\n    * a2\n* b\n\n## Directions\n\n1. go\n",
            dedent=False,
        )
        assert all(block.items for block in lists_of(doc.recipes[0])), \
            "every emitted list block should hold at least one item"

    def test_ragged_table_row_is_padded_to_the_header_width(self, parse):
        doc, _ = parse(
            "# X\n\n## Ingredients\n\n| Item | Amount | Note |\n| --- | --- | --- |\n"
            "| flour | 1 cup |\n| sugar | 1 cup | fine |\n",
            dedent=False,
        )
        tables = [b for b in doc.recipes[0].blocks if b.block_type == BlockType.TABLE]
        assert len(tables) == 1
        table = tables[0]

        assert table.headers == ["Item", "Amount", "Note"]
        assert len(table.rows) == 2
        assert all(len(row) == len(table.headers) for row in table.rows)
        assert table.rows[0][:2] == ["flour", "1 cup"]
        assert table.rows[1] == ["sugar", "1 cup", "fine"]

    def test_very_long_ingredient_line_is_preserved(self, parse):
        doc, _ = parse(
            f"# X\n\n## Ingredients\n\n* {LONG_INGREDIENT}\n\n## Directions\n\n1. Boil.\n",
            dedent=False,
        )
        ingredients = lists_of(doc.recipes[0])[0]
        assert len(ingredients.items) == 1
        assert len(ingredients.items[0].raw_line) > 3000

    def test_crlf_line_endings_parse_identically_to_lf(self, parse):
        crlf_doc, _ = parse(
            "# X\r\n\r\n## Ingredients\r\n\r\n* 1 cup water\r\n\r\n## Directions\r\n\r\n1. Boil.\r\n",
            dedent=False, newline="",
        )
        lf_doc, _ = parse(
            "# X\n\n## Ingredients\n\n* 1 cup water\n\n## Directions\n\n1. Boil.\n",
            dedent=False, newline="",
        )
        assert crlf_doc.recipes[0].title == lf_doc.recipes[0].title == "X"
        assert [b.section_type for b in lists_of(crlf_doc.recipes[0])] == \
               [b.section_type for b in lists_of(lf_doc.recipes[0])]
        assert lists_of(crlf_doc.recipes[0])[0].items[0].raw_line == "1 cup water"

    def test_frontmatter_only_document_has_metadata_and_no_recipes(self, parse):
        doc, diagnostics = parse("---\ntitle: Something\nyield: 4 servings\n---\n", dedent=False)
        assert doc.recipes == []
        assert doc.metadata == {"title": "Something", "yield": "4 servings"}
        assert diagnostics == []

    def test_bom_does_not_hide_the_title(self, parse):
        """
        Regression: a UTF-8 BOM sits in front of the first "#", so markdown-it read
        '\\ufeff# X' as a paragraph and the document lost its title entirely.
        """
        doc, diagnostics = parse(BOM_DOCUMENT)
        assert doc.recipes[0].title == "X"
        assert Code.NON_ASCII_CHARACTER not in codes(diagnostics)

    def test_bom_document_still_parses_its_sections(self, parse):
        doc, _ = parse(BOM_DOCUMENT)
        recipe = doc.recipes[0]
        assert [b.section_type for b in lists_of(recipe)] == ["ingredients", "directions"]
