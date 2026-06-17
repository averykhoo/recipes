# recipe_parser/validation/consistency.py
"""
Validation module that executes structural audits on recipe structures,
warning the author when sub-components are inconsistent.
"""

from typing import List
from recipe_parser.models.schemas import Recipe, BlockType


def audit_component_consistency(recipe: Recipe) -> List[str]:
    """
    Verifies that sub-components match across sections in the flat block sequence.
    """
    warnings = []
    ingredient_components = set()
    direction_components = set()

    for block in recipe.blocks:
        if block.block_type == BlockType.HEADING:
            if block.section_type == "ingredients" and block.component:
                ingredient_components.add(block.component.lower().strip())
            elif block.section_type == "directions" and block.component:
                direction_components.add(block.component.lower().strip())

    # Locate components with ingredients but no corresponding instructions
    for component in ingredient_components:
        if component in ("main", "default"):
            continue
        if component not in direction_components:
            warnings.append(
                f"Component '{component}' has defined ingredients, "
                f"but is missing a matching directions section (e.g. '## Directions for {component}')."
            )

    return warnings