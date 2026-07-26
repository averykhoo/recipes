# recipe_parser/validation/consistency.py
"""
Validation module that executes structural audits on recipe structures,
warning the author when sub-components are inconsistent.
"""

from typing import List

from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import Recipe
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity


def audit_component_consistency(recipe: Recipe) -> List[Diagnostic]:
    """
    Verifies that sub-components match across sections in the flat block sequence.
    """
    warnings: List[Diagnostic] = []
    ingredient_components = set()
    direction_components = set()

    for block in recipe.blocks:
        if block.block_type == BlockType.HEADING:
            if block.section_type == "ingredients" and block.component:
                ingredient_components.add(block.component.lower().strip())
            elif block.section_type == "directions" and block.component:
                direction_components.add(block.component.lower().strip())

    # Locate components with ingredients but no corresponding instructions
    for component in sorted(ingredient_components):
        if component in ("main", "default"):
            continue
        if component not in direction_components:
            detail = []
            if direction_components:
                named = sorted(c for c in direction_components if c not in ("main", "default"))
                detail.append(
                    f"directions sections present: {', '.join(named) if named else 'one unnamed section'}"
                )
            else:
                detail.append("this recipe has no directions sections at all")

            warnings.append(Diagnostic(
                severity=Severity.WARNING,
                code=Code.COMPONENT_WITHOUT_DIRECTIONS,
                recipe=recipe.title,
                message=(
                    f"Component '{component}' has defined ingredients, but is missing a matching "
                    f"directions section (e.g. '## Directions for {component}')."
                ),
                detail=detail,
            ))

    return warnings
