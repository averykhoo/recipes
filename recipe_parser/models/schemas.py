# recipe_parser/models/schemas.py
"""
Defines the Pydantic schemas representing recipe metadata, GFM blocks,
hierarchical sections, and multi-layered metric measurements.
"""

from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic import Field


class UnitClass(str, Enum):
    """Enumeration of unit physical types for strict validation checking."""
    VOLUME = "volume"
    WEIGHT = "weight"
    PIECE = "piece"
    DURATION = "duration"
    TEMPERATURE = "temperature"


class Measurement(BaseModel):
    """Represents a single parsed metric value, unit, and class."""
    value: float = Field(description="Normalized mid-point float representation of the quantity.")
    unit: str = Field(description="Canonical full proper English name of the unit, e.g. 'tablespoon'.")
    unit_class: UnitClass = Field(description="Semantic class used to categorize the unit type.")
    nested_capacity: Optional["Measurement"] = Field(
        default=None,
        description="Optional capacity inside a container unit (strictly allowed for PIECE units)."
    )


class QuantityRepresentation(BaseModel):
    """Represents a single additive representation (e.g., '0.5 cup + 1 teaspoon')."""
    raw_text: str = Field(description="Original unparsed string run of this specific representation.")
    terms: List[Measurement] = Field(
        default_factory=list,
        description="Additive list of measurements making up this representation."
    )


class Ingredient(BaseModel):
    """Represents a fully structured, multi-quantity ingredient element."""
    raw: str = Field(description="The original unparsed ingredient line for loss-free round-tripping.")
    representations: List[QuantityRepresentation] = Field(
        default_factory=list,
        description="Alternative representations (e.g. volumetric primary or mass-based secondary conversions)."
    )
    name: str = Field(description="The stripped canonical name of the ingredient.")
    modifier: Optional[str] = Field(default=None, description="Preparation instructions like chopped or sliced.")
    optional: bool = Field(default=False, description="True if explicitly marked as optional.")


class BlockType(str, Enum):
    """Enumeration of physical Markdown block-level elements."""
    HEADING = "heading"
    TEXT = "text"
    LIST = "list"
    TABLE = "table"


class BaseBlock(BaseModel):
    """Abstract parent schema for all flat sibling blocks."""
    block_type: BlockType

    def to_markdown(self) -> str:
        """Returns the loss-free Markdown serialization of this block."""
        raise NotImplementedError


class HeadingBlock(BaseBlock):
    """Represents standard Markdown headings from H2 to H6."""
    block_type: BlockType = BlockType.HEADING
    level: int = Field(description="Header level from 2 (##) to 6 (######).")
    text: str = Field(description="Sanitized header title text.")
    section_type: Optional[str] = Field(
        default=None,
        description="Semantic context boundary: 'ingredients', 'directions', or 'notes'."
    )
    component: Optional[str] = Field(
        default=None,
        description="Optional component boundary text (e.g., 'the dough')."
    )

    def to_markdown(self) -> str:
        return f"\n{'#' * self.level} {self.text}\n"


class TextBlock(BaseBlock):
    """Represents standard narrative paragraphs and blockquotes."""
    block_type: BlockType = BlockType.TEXT
    text: str = Field(description="Raw Markdown text run of the block.")
    is_quote: bool = Field(default=False, description="True if formatted as a blockquote (>).")

    def to_markdown(self) -> str:
        if self.is_quote:
            return f"\n> {self.text}\n"
        return f"\n{self.text}\n"


class IngredientItem(BaseModel):
    """Represents an item within an ingredients list."""
    raw_line: str = Field(description="Raw original line text.")
    parsed_ingredient: Optional[Ingredient] = Field(default=None, description="Structured parsed ingredient model.")


class ListBlock(BaseBlock):
    """Represents an ordered or unordered list of items."""
    block_type: BlockType = BlockType.LIST
    ordered: bool = Field(default=False, description="True if formatted as an ordered (numbered) list.")
    items: List[Union[IngredientItem, str]] = Field(
        default_factory=list,
        description="List items. Holds IngredientItems if ingredients list, else raw step strings."
    )
    extracted_temps: Dict[int, List[str]] = Field(
        default_factory=dict,
        description="Maps list item index to list of parsed inline temperatures."
    )
    extracted_durations: Dict[int, List[int]] = Field(
        default_factory=dict,
        description="Maps list item index to list of parsed inline durations (seconds)."
    )

    def to_markdown(self) -> str:
        lines = []
        for idx, item in enumerate(self.items):
            if self.ordered:
                lines.append(f"{idx + 1}. {item}")
            else:
                if isinstance(item, IngredientItem):
                    lines.append(f"* {item.raw_line}")
                else:
                    lines.append(f"* {item}")
        return "\n" + "\n".join(lines) + "\n"


class TableBlock(BaseBlock):
    """Represents standard GFM table grids."""
    block_type: BlockType = BlockType.TABLE
    headers: List[str] = Field(default_factory=list, description="List of column header text runs.")
    rows: List[List[str]] = Field(default_factory=list, description="Two-dimensional list representing row values.")

    def to_markdown(self) -> str:
        lines = []
        lines.append("| " + " | ".join(self.headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(self.headers)) + " |")
        for row in self.rows:
            lines.append("| " + " | ".join(row) + " |")
        return "\n" + "\n".join(lines) + "\n"


class Recipe(BaseModel):
    """Represents a single recipe, structured as a flat DOM block sequence."""
    title: str = Field(description="Title of the recipe (H1 text).")
    yield_val: Optional[str] = Field(default=None, alias="yield", description="Parsed portion size or yield string.")
    blocks: List[Union[HeadingBlock, TextBlock, ListBlock, TableBlock]] = Field(
        default_factory=list,
        description="Sequence of sibling blocks representing the full document DOM."
    )

    def to_markdown(self) -> str:
        lines = [f"# {self.title}\n"]
        if self.yield_val:
            lines.append(f"{self.yield_val}\n")
        for block in self.blocks:
            lines.append(block.to_markdown())
        return "".join(lines)


class RecipeDocument(BaseModel):
    """Represents an entire source Markdown file document."""
    source_file: str = Field(description="Relative filepath of the source document.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Original YAML frontmatter metadata.")
    recipes: List[Recipe] = Field(default_factory=list, description="List of recipes parsed from this file.")
