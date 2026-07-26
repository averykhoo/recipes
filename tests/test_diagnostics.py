"""Diagnostic-level tests: which code fires, at what severity, and when it must not.

Assertions here are on `Diagnostic.code` constants and `Diagnostic.severity` only.
Message wording is explicitly *not* tested - it is expected to change.
"""

import pytest

from conftest import by_code
from conftest import codes
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity


def only(diagnostics, code):
    """Asserts exactly one diagnostic with `code` was raised and returns it."""
    found = by_code(diagnostics, code)
    assert len(found) == 1, f"expected exactly one {code}, got {codes(diagnostics)}"
    return found[0]


# =====================================================================================
# Structural codes
# =====================================================================================

class TestMissingSections:

    def test_missing_ingredients_section(self, parse):
        _, diagnostics = parse("""
            # X

            ## Directions

            1. Boil the water.
            """)
        diagnostic = only(diagnostics, Code.MISSING_INGREDIENTS)
        assert diagnostic.code == "missing-ingredients-section"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "X"
        assert Code.MISSING_DIRECTIONS not in codes(diagnostics)

    def test_missing_directions_section(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup water
            """)
        diagnostic = only(diagnostics, Code.MISSING_DIRECTIONS)
        assert diagnostic.code == "missing-directions-section"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "X"
        assert Code.MISSING_INGREDIENTS not in codes(diagnostics)

    def test_both_missing_when_only_an_unrelated_h2_carries_the_lists(self, parse):
        _, diagnostics = parse("""
            # X

            ## Shopping list

            * 1 cup water

            ## Timings

            1. Twenty minutes.
            """)
        raised = codes(diagnostics)
        assert Code.MISSING_INGREDIENTS in raised
        assert Code.MISSING_DIRECTIONS in raised

    def test_neither_fires_for_a_complete_recipe(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        raised = codes(diagnostics)
        assert Code.MISSING_INGREDIENTS not in raised
        assert Code.MISSING_DIRECTIONS not in raised
        assert Code.NO_SECTION_HEADINGS not in raised

    def test_missing_section_codes_are_suppressed_when_there_are_no_headings_at_all(self, parse):
        """A headerless document gets `no-section-headings` instead, not both variants."""
        _, diagnostics = parse("""
            # X

            * 1 cup water

            1. Boil it.
            """)
        raised = codes(diagnostics)
        assert Code.NO_SECTION_HEADINGS in raised
        assert Code.MISSING_INGREDIENTS not in raised
        assert Code.MISSING_DIRECTIONS not in raised

    def test_missing_section_codes_need_a_list_to_fire(self, parse):
        """With headings but no lists there is nothing to have been misfiled."""
        _, diagnostics = parse("""
            # X

            ## Notes

            Just a paragraph.
            """)
        raised = codes(diagnostics)
        assert Code.MISSING_INGREDIENTS not in raised
        assert Code.MISSING_DIRECTIONS not in raised


class TestNoSectionHeadings:

    def test_severity_and_code(self, parse):
        _, diagnostics = parse("""
            # Headerless

            * 1 cup water

            1. Boil it.
            """)
        diagnostic = only(diagnostics, Code.NO_SECTION_HEADINGS)
        assert diagnostic.code == "no-section-headings"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "Headerless"

    def test_does_not_fire_when_the_document_has_no_content(self, parse):
        _, diagnostics = parse("# Just A Title\n", dedent=False)
        assert Code.NO_SECTION_HEADINGS not in codes(diagnostics)

    def test_section_inferred_is_info(self, parse):
        _, diagnostics = parse("""
            # Headerless

            * 1 cup water

            1. Boil it.
            """)
        inferred = by_code(diagnostics, Code.SECTION_INFERRED)
        assert len(inferred) == 2
        assert all(d.severity == Severity.INFO for d in inferred)
        assert all(d.code == "section-inferred" for d in inferred)


class TestComponentWithoutDirections:

    def test_fires_for_a_named_component_with_no_matching_directions(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients for the sauce

            * 1 cup water

            ## Directions

            1. Boil it.
            """)
        diagnostic = only(diagnostics, Code.COMPONENT_WITHOUT_DIRECTIONS)
        assert diagnostic.code == "component-without-directions"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "X"
        assert diagnostic.detail, "the diagnostic should carry supporting evidence"

    def test_does_not_fire_when_the_matching_directions_exist(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients for the sauce

            * 1 cup water

            ## Directions for the sauce

            1. Boil it.
            """)
        assert Code.COMPONENT_WITHOUT_DIRECTIONS not in codes(diagnostics)

    def test_component_matching_is_case_insensitive(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients for The Sauce

            * 1 cup water

            ## Directions for the sauce

            1. Boil it.
            """)
        assert Code.COMPONENT_WITHOUT_DIRECTIONS not in codes(diagnostics)

    def test_does_not_fire_for_the_main_component(self, parse):
        """A bare `## Ingredients` is component 'Main' and is exempt."""
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup water

            ## Notes

            No directions here at all.
            """)
        assert Code.COMPONENT_WITHOUT_DIRECTIONS not in codes(diagnostics)

    def test_does_not_fire_for_main_even_with_no_directions_section(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup water
            """)
        assert Code.COMPONENT_WITHOUT_DIRECTIONS not in codes(diagnostics)
        assert Code.MISSING_DIRECTIONS in codes(diagnostics)

    def test_fires_once_per_orphaned_component(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients for the sauce

            * 1 cup water

            ## Ingredients for the topping

            * 1 cup cream

            ## Directions for the sauce

            1. Boil it.
            """)
        found = by_code(diagnostics, Code.COMPONENT_WITHOUT_DIRECTIONS)
        assert len(found) == 1
        assert "topping" in found[0].message.lower()


# =====================================================================================
# Measurement sanity
# =====================================================================================

class TestConversionDiscrepancy:

    def _parse_ingredient(self, parse, line):
        return parse(f"""
            # X

            ## Ingredients

            * {line}

            ## Directions

            1. Boil it.
            """)

    @pytest.mark.parametrize("line", [
        "1 cup all-purpose flour (500g)",   # ~125g by density, stated as 500g
        "1 cup water (1000g)",              # 240g vs 1000g
        "100 g butter (1 kg)",              # 100g vs 1000g
    ])
    def test_fires_when_the_two_measurements_disagree(self, parse, line):
        _, diagnostics = self._parse_ingredient(parse, line)
        diagnostic = only(diagnostics, Code.CONVERSION_DISCREPANCY)
        assert diagnostic.code == "conversion-discrepancy"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "X"
        assert diagnostic.context is not None

    @pytest.mark.parametrize("line", [
        "1 cup water (240g)",         # exact
        "1 cup water (250g)",         # ~4%, inside the 10% tolerance
        "100 g butter (100 g)",       # identical
        "1 kg flour (1000g)",         # unit change only
    ])
    def test_does_not_fire_when_the_two_measurements_agree(self, parse, line):
        _, diagnostics = self._parse_ingredient(parse, line)
        assert Code.CONVERSION_DISCREPANCY not in codes(diagnostics)

    def test_does_not_fire_for_a_single_measurement(self, parse):
        _, diagnostics = self._parse_ingredient(parse, "1 cup all-purpose flour")
        assert Code.CONVERSION_DISCREPANCY not in codes(diagnostics)


class TestTemperatureDiscrepancy:

    def _parse_step(self, parse, step):
        return parse(f"""
            # X

            ## Ingredients

            * 1 cup water

            ## Directions

            1. {step}
            """)

    @pytest.mark.parametrize("step", [
        "Bake at 180°C (400°F) for 20 minutes.",   # 180C is 356F
        "Heat the oil to 200°C (300°F).",          # 200C is 392F
    ])
    def test_fires_for_a_mismatched_pair(self, parse, step):
        _, diagnostics = self._parse_step(parse, step)
        diagnostic = only(diagnostics, Code.TEMPERATURE_DISCREPANCY)
        assert diagnostic.code == "temperature-discrepancy"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.recipe == "X"
        assert diagnostic.context == step
        assert diagnostic.detail, "the diagnostic should show both conversions"

    @pytest.mark.parametrize("step", [
        "Bake at 180°C (356°F) for 20 minutes.",   # exact
        "Bake at 180°C (355°F) for 20 minutes.",   # within the 5C tolerance
        "Bake at 200°C (392°F) for 20 minutes.",
    ])
    def test_does_not_fire_for_a_matching_pair(self, parse, step):
        _, diagnostics = self._parse_step(parse, step)
        assert Code.TEMPERATURE_DISCREPANCY not in codes(diagnostics)

    def test_does_not_fire_for_a_single_temperature(self, parse):
        _, diagnostics = self._parse_step(parse, "Bake at 180°C for 20 minutes.")
        assert Code.TEMPERATURE_DISCREPANCY not in codes(diagnostics)

    def test_does_not_fire_for_a_same_scale_range(self, parse):
        """'180°C to 200°C' is a range, not a conversion, and must not be compared."""
        _, diagnostics = self._parse_step(parse, "Bake at 180°C to 200°C until golden.")
        assert Code.TEMPERATURE_DISCREPANCY not in codes(diagnostics)


# =====================================================================================
# Non-ASCII characters
# =====================================================================================

class TestNonAsciiCharacter:

    def _parse_text(self, parse, text):
        return parse(f"""
            # X

            {text}

            ## Ingredients

            * 1 cup water

            ## Directions

            1. Boil it.
            """)

    @pytest.mark.parametrize("text,char", [
        ("Grandma’s recipe.", "’"),   # right single quotation mark
        ("She said “hello”.", "“"),  # left double quotation mark
        ("A bullet • point.", "•"),
        ("An ellipsis…", "…"),
        ("A non-breaking space.", " "),
    ])
    def test_fires_for_a_disallowed_character(self, parse, text, char):
        _, diagnostics = self._parse_text(parse, text)
        found = by_code(diagnostics, Code.NON_ASCII_CHARACTER)

        assert len(found) >= 1
        diagnostic = found[0]
        assert diagnostic.code == "non-ascii-character"
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.line_number is not None and diagnostic.line_number >= 1
        assert char in diagnostic.context

    @pytest.mark.parametrize("text", [
        "Bake at 180°C.",                 # degree sign
        "Rest for 10–15 minutes.",        # en-dash
        "Use ½ a cup.",                   # vulgar one half
        "Use ¼ and ¾ of a cup.",     # vulgar quarters
        "Café style with jalapeño.", # whitelisted accents
        "Crème brûlée",         # e-grave and e-acute (u-circumflex checked below)
    ])
    def test_does_not_fire_for_whitelisted_characters(self, parse, text):
        _, diagnostics = self._parse_text(parse, text)
        offenders = by_code(diagnostics, Code.NON_ASCII_CHARACTER)
        # Only report characters that really are outside the whitelist.
        from recipe_parser.validation.characters import ALLOWED_UNICODE_CHARACTERS
        expected = [c for c in text if ord(c) > 127 and c not in ALLOWED_UNICODE_CHARACTERS]
        assert len(offenders) == len(set(expected)), (
            f"unexpected offenders for {text!r}: {[d.message for d in offenders]}"
        )

    def test_pure_ascii_document_is_clean(self, parse):
        _, diagnostics = self._parse_text(parse, "A perfectly plain sentence.")
        assert Code.NON_ASCII_CHARACTER not in codes(diagnostics)

    def test_the_same_character_is_reported_once_per_line(self, parse):
        _, diagnostics = self._parse_text(parse, "It’s Grandma’s recipe.")
        assert len(by_code(diagnostics, Code.NON_ASCII_CHARACTER)) == 1


# =====================================================================================
# Diagnostic model itself
# =====================================================================================

class TestDiagnosticModel:

    def test_every_emitted_diagnostic_has_a_known_code(self, parse):
        known = {v for k, v in vars(Code).items() if not k.startswith("_") and isinstance(v, str)}
        _, diagnostics = parse("""
            # X

            * 1 cup all-purpose flour (500g)

            1. Bake at 180°C (400°F).

            * Grandma’s note.
            """)
        assert diagnostics, "this snippet should be noisy"
        for diagnostic in diagnostics:
            assert diagnostic.code in known, diagnostic.code
            assert diagnostic.severity in tuple(Severity)
            assert diagnostic.message

    def test_render_returns_a_non_empty_multiline_block_with_details(self, parse):
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup all-purpose flour (500g)

            ## Directions

            1. Boil it.
            """)
        diagnostic = only(diagnostics, Code.CONVERSION_DISCREPANCY)
        assert diagnostic.detail, "conversion-discrepancy should carry detail lines"

        rendered = diagnostic.render()
        lines = rendered.splitlines()

        assert rendered.strip()
        assert len(lines) >= 2 + len(diagnostic.detail)
        assert diagnostic.code in lines[0]
        assert diagnostic.recipe in lines[0]
        # Every detail entry is rendered as its own indented tree line.
        assert sum(1 for line in lines if "├─" in line or "└─" in line) == len(diagnostic.detail)
        assert lines[-1].lstrip().startswith("└─")

    def test_render_handles_a_diagnostic_with_no_detail(self, parse):
        _, diagnostics = parse("""
            # X

            ## Directions

            1. Boil it.
            """)
        diagnostic = only(diagnostics, Code.MISSING_INGREDIENTS)
        assert diagnostic.detail == []

        rendered = diagnostic.render()
        assert rendered.strip()
        assert len(rendered.splitlines()) == 2

    def test_render_uses_the_custom_indent(self):
        diagnostic = Diagnostic(
            severity=Severity.INFO,
            code=Code.YIELD_INFERRED,
            message="anything",
            recipe="X",
            detail=["a", "b"],
        )
        rendered = diagnostic.render(indent=">>")
        assert all(line.startswith(">>") for line in rendered.splitlines())
        assert len(rendered.splitlines()) == 4

    def test_str_contains_severity_and_code(self):
        diagnostic = Diagnostic(
            severity=Severity.ERROR,
            code=Code.QUANTITY_UNPARSED,
            message="anything",
        )
        text = str(diagnostic)
        assert Severity.ERROR.value in text
        assert Code.QUANTITY_UNPARSED in text

    def test_diagnostics_are_deduplicated_by_the_orchestrator(self, parse):
        """The same finding on two identical lines collapses to one report."""
        _, diagnostics = parse("""
            # X

            ## Ingredients

            * 1 cup all-purpose flour (500g)
            * 1 cup all-purpose flour (500g)

            ## Directions

            1. Boil it.
            """)
        assert len(by_code(diagnostics, Code.CONVERSION_DISCREPANCY)) == 1
