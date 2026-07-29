"""Source-coverage tests: does every content-bearing source line reach the parsed model?

The audit answers one question per source line - "did anything resembling this survive?"
- so these tests are written the same way: write a document, parse it, and assert which
lines the audit says were lost. Assertions are on `Diagnostic.code`, `Diagnostic.severity`
and line numbers only; message wording is expected to change.
"""

import textwrap

import pytest

from conftest import by_code
from conftest import codes
from recipe_parser.validation.coverage import audit_source_coverage
from recipe_parser.validation.coverage import find_dropped_source_lines
from recipe_parser.validation.coverage import normalize
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Severity


@pytest.fixture
def coverage(parse, write_recipe):
    """Parses a snippet and runs the source-coverage audit over it, as the pipeline does.

    Returns ``(diagnostics, dropped_lines)`` where ``dropped_lines`` is the raw
    ``(line_number, text)`` list, which is easier to assert against precisely.
    """

    def _coverage(content, *, dedent=True):
        text = textwrap.dedent(content) if dedent else content
        path = write_recipe(text, dedent=False)
        from recipe_parser.core.orchestrator import process_recipe_document
        document, _ = process_recipe_document(path)
        source = path.read_text(encoding="utf-8-sig")
        return audit_source_coverage(document.recipes, source), find_dropped_source_lines(
            document.recipes, source
        )

    return _coverage


COMPLETE_RECIPE = """\
# Boiled Water

Serves 2

## Ingredients

* 1 cup water
* 1 teaspoon salt

## Directions

1. Put the water in a pan.
2. Bring it to a boil.
"""


# =====================================================================================
# It fires on real loss
# =====================================================================================

class TestDroppedContentIsReported:

    def test_a_fenced_code_block_is_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

            ## Notes

            ```python
            pressure = moles * constant * temperature / volume
            print(f"the bottle reaches {pressure} pascals")
            ```
            """)
        found = by_code(diagnostics, Code.SOURCE_CONTENT_DROPPED)
        assert found, f"expected the code block to be reported, got {codes(diagnostics)}"

        diagnostic = found[0]
        assert diagnostic.code == "source-content-dropped"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.line_number is not None

        lost = {number for number, _ in dropped}
        # Both fence markers and both statements inside them. An exact count, because a
        # `>=` bound also passes if the audit gives up and reports the whole document.
        assert len(lost) == 4
        assert any("pascals" in text for _, text in dropped)

    def test_a_blockquote_nested_in_a_numbered_step_is_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

               > PLEASE do not skip this, the filling will spill out otherwise.

            2. Serve.
            """)
        assert Code.SOURCE_CONTENT_DROPPED in codes(diagnostics)
        assert any("spill out" in text for _, text in dropped)

    def test_the_finding_quotes_the_dropped_text_and_its_line(self, coverage):
        diagnostics, _ = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

            ```
            a wholly unrepresented fenced paragraph about tungsten filaments
            ```
            """)
        diagnostic = by_code(diagnostics, Code.SOURCE_CONTENT_DROPPED)[0]
        quoted = diagnostic.context + " " + " ".join(diagnostic.detail)
        assert "tungsten" in quoted
        assert diagnostic.line_number >= 1
        # render() puts the line number and the text in front of the reader.
        rendered = diagnostic.render()
        assert f"line {diagnostic.line_number}" in rendered
        assert "tungsten" in rendered

    def test_neighbouring_dropped_lines_collapse_into_one_finding(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

            ```
            alpha kryptonite manifold
            beta kryptonite manifold
            gamma kryptonite manifold
            ```
            """)
        found = by_code(diagnostics, Code.SOURCE_CONTENT_DROPPED)
        assert len(found) == 1, "a single lost block should not produce one finding per line"
        # Both fence markers and all three statements: the delimiters are themselves
        # evidence that a block the parser has no home for was discarded.
        assert len(dropped) == 5
        assert found[0].detail, "the trailing lines of the run belong on the same finding"


# =====================================================================================
# It stays silent on intentional drops and on clean documents
# =====================================================================================

class TestIntentionalDropsAreSilent:

    def test_a_markdown_comment_is_not_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            [//]: # (todo: check this against the original source)

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics), dropped

    def test_several_markdown_comments_between_steps_are_not_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            [//]: # (step 1)

            1. Boil it.

            [//]: # (step 2)

            2. Serve it.
            """)
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics), dropped

    def test_an_html_comment_is_not_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            <!-- an authoring note nobody should see -->

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics), dropped

    def test_thematic_breaks_and_table_rules_are_not_reported(self, coverage):
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

            ## Notes

            | vessel | volume |
            |--------|--------|
            | pan    | 2 cups |

            ---
            """)
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics), dropped

    def test_a_fully_round_tripping_document_is_silent(self, coverage):
        diagnostics, dropped = coverage(COMPLETE_RECIPE)
        assert dropped == []
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)

    def test_headings_sub_headings_and_prose_all_survive(self, coverage):
        diagnostics, dropped = coverage("""\
            # White Kimchi

            adapted from a book

            ## Ingredients

            ### Cabbage

            * 1 napa cabbage
            * 0.5 cup salt

            ### Pickling liquid

            * 4-8 garlic cloves
            * 1 tablespoon salt mixed in 2 cups water to form a brine

            ## Directions

            1. Sprinkle salt evenly between the cabbage leaves.
            2. Rinse and drain.

            ## Notes

            The brine should taste of the sea, not of a salt lick.
            """)
        assert dropped == [], dropped
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)

    def test_a_ten_plus_step_ordered_list_is_silent(self, coverage):
        """Ordered-list markers must be stripped, or every step reads as missing."""
        steps = "\n".join(f"{n}. Stir the pot for {n} minutes." for n in range(1, 13))
        diagnostics, dropped = coverage(
            "# X\n\n## Ingredients\n\n* 1 cup water\n\n## Directions\n\n" + steps + "\n",
            dedent=False,
        )
        assert dropped == [], dropped
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)

    def test_a_bare_url_rewritten_into_an_autolink_is_silent(self, coverage):
        """The parser wraps bare URLs in angle brackets; that is not data loss."""
        diagnostics, dropped = coverage("""\
            # X

            https://www.seriouseats.com/a-brief-guide-to-roux

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        assert dropped == [], dropped
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)

    def test_a_local_md_link_survives_verbatim(self, coverage):
        """
        Local `.md` targets reach the model unchanged and must not be reported.

        The parser used to rewrite them to `.html` for the published site, and this
        audit used to normalize the two spellings together. Both are gone: the site
        build does its own rewriting, and treating `.md` and `.html` as equal here
        would blind this pass to the rewrite ever leaking back into the model.
        """
        diagnostics, dropped = coverage("""\
            # X

            ## Ingredients

            * [bolognese](ragu-alla-bolognese.md)
            * [mornay](../bechamel.md) using parmesan

            ## Directions

            1. Acquire [tzatziki](tzatziki.md) and layer it.
            """)
        assert dropped == [], dropped
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)

    def test_a_table_row_of_short_cells_is_silent(self, coverage):
        """
        A row is stored as its bare cells, so the pipes must come off the source too.

        Every cell here is too short to tokenize, so the row falls through to the
        literal-character test. If the separators survive into that comparison the row
        can never match, because nothing on the model side ever contains a pipe - and
        a perfectly-parsed sizing table reports itself as lost.
        """
        diagnostics, dropped = coverage("""\
            # X

            | recipe scale | square pan | round pan |
            |--------------|------------|-----------|
            | 1x           | 4"         | 4.5"      |
            | 3x           | 7"         | 8"        |
            | 5x           | 9"         | 10"       |

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        assert dropped == [], dropped
        assert Code.SOURCE_CONTENT_DROPPED not in codes(diagnostics)


# =====================================================================================
# Normalization, which is where the false positives come from
# =====================================================================================

class TestNormalization:

    @pytest.mark.parametrize("left,right", [
        ("<https://example.com/x>", "https://example.com/x"),   # autolink wrapping
        ("**bold** text", "bold text"),                          # emphasis
        ("`code` text", "code text"),                            # inline code ticks
        ("A   ragged    line", "a ragged line"),                 # case and whitespace
    ])
    def test_equivalent_fragments_normalize_alike(self, left, right):
        assert normalize(left) == normalize(right)

    def test_distinct_fragments_do_not_normalize_alike(self):
        assert normalize("add the salt") != normalize("add the sugar")


class TestAuditShape:

    def test_no_recipes_and_no_source_produce_nothing(self):
        assert audit_source_coverage([], "") == []

    def test_an_empty_document_produces_nothing(self, coverage):
        diagnostics, dropped = coverage("", dedent=False)
        assert diagnostics == []
        assert dropped == []

    def test_the_recipe_title_is_attached_when_the_file_holds_one_recipe(self, coverage):
        diagnostics, _ = coverage("""\
            # Fizzy Fruit

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.

            ```
            a lost incantation concerning zirconium
            ```
            """)
        diagnostic = by_code(diagnostics, Code.SOURCE_CONTENT_DROPPED)[0]
        assert diagnostic.recipe == "Fizzy Fruit"

    def test_the_code_is_registered_on_the_code_registry(self):
        known = {v for k, v in vars(Code).items() if not k.startswith("_") and isinstance(v, str)}
        assert Code.SOURCE_CONTENT_DROPPED in known
