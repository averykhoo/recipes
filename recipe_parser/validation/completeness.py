# recipe_parser/validation/completeness.py
"""
Audits how much of a recipe the parser actually understood.

The other validation passes check whether the *content* is self-consistent. This one
checks whether the *parse* succeeded, which is otherwise invisible: an ingredient line
whose quantity fails to parse produces no error, it just silently carries no
measurement. These diagnostics make that loss visible.
"""

import re
from typing import List
from typing import Optional

from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import Recipe
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity
from recipe_parser.validation.diagnostics import find_line_number

# A line that opens with a digit or a vulgar fraction is asserting a quantity.
RE_STARTS_WITH_QUANTITY = re.compile(r"^\s*[~(\[]?\s*[\d¼-¾⅐-⅞]")

# A leading number that sizes the ingredient rather than counting it: "9-inch pie shell",
# "0.5-1 inch ginger", "6cm piece". These carry no amount and that is fine.
RE_DIMENSIONAL = re.compile(
    r"^\s*~?\s*[\d./\-–—\s]+\s*"
    r"(?:inch|inches|in|cm|mm|centimet(?:er|re)s?|millimet(?:er|re)s?|foot|feet|percent|%)\b",
    re.IGNORECASE
)


def audit_parse_completeness(recipe: Recipe, source_lines: Optional[List[str]] = None) -> List[Diagnostic]:
    """
    Reports structure that is missing and ingredient lines the parser could not fully read.
    """
    diagnostics: List[Diagnostic] = []
    source_lines = source_lines or []

    heading_blocks = [b for b in recipe.blocks if b.block_type == BlockType.HEADING]
    list_blocks = [b for b in recipe.blocks if b.block_type == BlockType.LIST]

    has_section_headings = any(b.level == 2 for b in heading_blocks)
    has_ingredients = any(b.section_type == "ingredients" for b in heading_blocks)
    has_directions = any(b.section_type == "directions" for b in heading_blocks)

    has_any_content = bool(list_blocks) or any(b.block_type == BlockType.TEXT for b in recipe.blocks)

    # --- structural completeness ---------------------------------------------------
    if not has_section_headings and has_any_content:
        diagnostics.append(Diagnostic(
            severity=Severity.WARNING,
            code=Code.NO_SECTION_HEADINGS,
            recipe=recipe.title,
            message=(
                "Recipe has no '## Ingredients' or '## Directions' headings, so every section "
                "below was guessed from list style alone. Add explicit headings to make the "
                "structure unambiguous."
            ),
        ))
    else:
        if not has_ingredients and list_blocks:
            diagnostics.append(Diagnostic(
                severity=Severity.WARNING,
                code=Code.MISSING_INGREDIENTS,
                recipe=recipe.title,
                message="No '## Ingredients' section found.",
            ))
        if not has_directions and list_blocks:
            diagnostics.append(Diagnostic(
                severity=Severity.WARNING,
                code=Code.MISSING_DIRECTIONS,
                recipe=recipe.title,
                message="No '## Directions' section found.",
            ))

    for block in list_blocks:
        if block.inferred_section:
            diagnostics.append(Diagnostic(
                severity=Severity.INFO,
                code=Code.SECTION_INFERRED,
                recipe=recipe.title,
                message=(
                    f"A {'numbered' if block.ordered else 'bulleted'} list of {len(block.items)} "
                    f"item(s) was assigned to '{block.section_type}' by inference rather than "
                    f"from a heading."
                ),
            ))

    # --- per-ingredient-line parse quality -----------------------------------------
    for block in list_blocks:
        if block.section_type != "ingredients":
            continue

        for item in block.items:
            raw_line = getattr(item, "raw_line", None)
            if raw_line is None:
                continue

            line_number = find_line_number(source_lines, raw_line)
            ingredient = item.parsed_ingredient

            if ingredient is None:
                diagnostics.append(Diagnostic(
                    severity=Severity.ERROR,
                    code=Code.QUANTITY_UNPARSED,
                    recipe=recipe.title,
                    line_number=line_number,
                    context=raw_line,
                    message="Ingredient line could not be parsed at all.",
                ))
                continue

            terms = [term for rep in ingredient.representations for term in rep.terms]

            if not terms and RE_STARTS_WITH_QUANTITY.match(raw_line):
                # A leading number that measures a *dimension* ("0.5-1 inch ginger") is
                # not a failure to parse an amount - there is no amount to parse.
                is_dimension = RE_DIMENSIONAL.match(raw_line) is not None
                diagnostics.append(Diagnostic(
                    severity=Severity.INFO if is_dimension else Severity.ERROR,
                    code=Code.DIMENSION_NOT_QUANTITY if is_dimension else Code.QUANTITY_UNPARSED,
                    recipe=recipe.title,
                    line_number=line_number,
                    context=raw_line,
                    message=(
                        "Leading number describes a size, not an amount, so this ingredient "
                        "carries no measurement."
                        if is_dimension else
                        "Line begins with a number but no quantity could be extracted, "
                        "so this ingredient carries no measurement."
                    ),
                    detail=[f"parsed name: {ingredient.name!r}"],
                ))

            if not ingredient.name.strip():
                diagnostics.append(Diagnostic(
                    severity=Severity.WARNING,
                    code=Code.NAME_EMPTY,
                    recipe=recipe.title,
                    line_number=line_number,
                    context=raw_line,
                    message=(
                        "Ingredient resolved to an empty name. This usually means the line is a "
                        "continuation of the one above and should be merged into it."
                    ),
                ))

            for term in terms:
                if term.implicit_unit:
                    diagnostics.append(Diagnostic(
                        severity=Severity.INFO,
                        code=Code.IMPLICIT_COUNT,
                        recipe=recipe.title,
                        line_number=line_number,
                        context=raw_line,
                        message=(
                            f"No unit was written; read as a count of {term.value:g} whole "
                            f"{ingredient.name or 'item'}."
                        ),
                    ))

    return diagnostics
