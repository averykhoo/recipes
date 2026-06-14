# recipe_parser/models/schemas.py
"""
Defines the structured Pydantic schemas representing recipe metadata,
components, ingredients, and directions steps.
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class Ingredient(BaseModel):
    """
    Represents a structured ingredient line, separating metrics
    and preparation details from the name.
    """
    raw: str = Field(description="The original unparsed ingredient string.")
    quantity: str = Field(default="", description="The normalized decimal or range string.")
    unit: str = Field(default="", description="The normalized canonical unit of measure.")
    name: str = Field(description="The primary name of the ingredient.")
    modifier: Optional[str] = Field(default=None, description="Preparation details like diced or sliced.")
    optional: bool = Field(default=False, description="True if marked as an optional ingredient.")


class IngredientsComponent(BaseModel):
    """
    Groups a list of ingredients belonging to a specific sub-component.
    """
    component: Optional[str] = Field(default=None, description="The name of the component, if specified.")
    items: List[Ingredient] = Field(default_factory=list, description="The list of ingredients under this component.")


class DirectionsComponent(BaseModel):
    """
    Groups a sequence of directions belonging to a specific sub-component.
    """
    component: Optional[str] = Field(default=None, description="The name of the component, if specified.")
    steps: List[str] = Field(default_factory=list, description="The sequence of instruction steps.")


class Recipe(BaseModel):
    """
    Represents a single recipe, containing components, notes, and metadata.
    """
    title: str = Field(description="The title of the recipe.")
    yield_val: Optional[str] = Field(default=None, alias="yield", description="The serving size or yield string.")
    ingredients: List[IngredientsComponent] = Field(default_factory=list, description="Grouped ingredient lists.")
    directions: List[DirectionsComponent] = Field(default_factory=list, description="Grouped step lists.")
    notes: List[str] = Field(default_factory=list, description="Global comments, tips, or troubleshooting notes.")

    # Maintain dual compatibility for Pydantic v1 and Pydantic v2
    model_config = {
        "populate_by_name": True,
        "by_alias":         True
    }


class RecipeDocument(BaseModel):
    """
    Represents an entire source document, mapping file metadata and recipes.
    """
    source_file: str = Field(description="The relative filepath of the Markdown source document.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="The original YAML frontmatter metadata.")
    recipes: List[Recipe] = Field(default_factory=list, description="The list of recipes parsed from this file.")
