# recipe_parser/validation/consistency.py
"""
Validation module that executes structural audits on recipe structures,
warning the author when sub-components are inconsistent.
"""

from typing import List

from recipe_parser.models.schemas import Recipe


def audit_component_consistency(recipe: Recipe) -> List[str]:
    """
    Verifies that sub-components match across sections.
    If a component lists ingredients (such as "the glaze"), it registers a warning
    if no directions exist for preparing "the glaze".
    """
    warnings = []

    ingredient_components = {
        comp.component.lower().strip()
        for comp in recipe.ingredients
        if comp.component is not None
    }

    direction_components = {
        comp.component.lower().strip()
        for comp in recipe.directions
        if comp.component is not None
    }

    # Locate components with ingredients but no corresponding instructions
    for component in ingredient_components:
        if component not in direction_components:
            warnings.append(
                f"Component '{component}' has defined ingredients, "
                f"but is missing a matching directions section (e.g. '## Directions for {component}')."
            )

    return warnings
