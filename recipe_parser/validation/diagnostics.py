# recipe_parser/validation/diagnostics.py
"""
Structured diagnostic records emitted by the validation passes.

The parser is deliberately lenient: it never refuses a document, it reports what it
could not make sense of. That only works if the reporting is precise, so every finding
carries a severity, a stable machine-readable code, the recipe it came from, and -
where one exists - the exact source line that triggered it.
"""

from enum import Enum
from typing import List
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class Severity(str, Enum):
    """How much the reader should care."""
    ERROR = "error"  # the parser could not understand something it should have
    WARNING = "warning"  # very likely an authoring mistake
    INFO = "info"  # worth knowing, not necessarily wrong


# Stable diagnostic codes. Grouped by the pass that raises them.
class Code:
    # --- structure ---
    NO_SECTION_HEADINGS = "no-section-headings"
    MISSING_INGREDIENTS = "missing-ingredients-section"
    MISSING_DIRECTIONS = "missing-directions-section"
    SECTION_INFERRED = "section-inferred"
    COMPONENT_WITHOUT_DIRECTIONS = "component-without-directions"

    # --- ingredient lines ---
    QUANTITY_UNPARSED = "quantity-unparsed"
    NAME_EMPTY = "ingredient-name-empty"
    IMPLICIT_COUNT = "implicit-count-unit"
    DIMENSION_NOT_QUANTITY = "dimension-not-quantity"

    # --- measurement sanity ---
    CONVERSION_DISCREPANCY = "conversion-discrepancy"
    TEMPERATURE_DISCREPANCY = "temperature-discrepancy"
    INVALID_UNIT_CLASS = "invalid-unit-class"
    INVALID_NESTING = "invalid-nesting"

    # --- metadata ---
    YIELD_INFERRED = "yield-inferred"
    NON_ASCII_CHARACTER = "non-ascii-character"


SEVERITY_ICONS = {
    Severity.ERROR: "!!",
    Severity.WARNING: "!",
    Severity.INFO: "i",
}


class Diagnostic(BaseModel):
    """A single finding against a recipe document."""
    severity: Severity = Field(description="How much the reader should care.")
    code: str = Field(description="Stable machine-readable identifier for this kind of finding.")
    message: str = Field(description="Human-readable description of the problem.")
    recipe: Optional[str] = Field(default=None, description="Title of the recipe the finding belongs to.")
    line_number: Optional[int] = Field(default=None, description="1-based source line, when known.")
    context: Optional[str] = Field(default=None, description="The offending source text, verbatim.")
    detail: List[str] = Field(
        default_factory=list,
        description="Supporting evidence lines, rendered as an indented tree under the message."
    )

    def render(self, indent: str = "       ") -> str:
        """Renders this diagnostic as an indented, multi-line block for terminal output."""
        icon = SEVERITY_ICONS.get(self.severity, "?")
        head = f"{indent}[{icon}] {self.severity.value.upper():7s} {self.code}"
        if self.recipe:
            head += f"  ({self.recipe})"

        lines = [head, f"{indent}     {self.message}"]

        if self.context is not None:
            location = f"line {self.line_number}" if self.line_number else "source"
            lines.append(f"{indent}     {location}: {self.context.strip()!r}")

        for detail_index, detail_line in enumerate(self.detail):
            connector = "└─" if detail_index == len(self.detail) - 1 else "├─"
            lines.append(f"{indent}     {connector} {detail_line}")

        return "\n".join(lines)

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.code}: {self.message}"


def find_line_number(haystack_lines: List[str], needle: str) -> Optional[int]:
    """
    Best-effort lookup of the 1-based source line that produced a piece of text.
    Returns None rather than guessing when the text cannot be located unambiguously.
    """
    probe = needle.strip()
    if not probe:
        return None
    for line_index, line in enumerate(haystack_lines, start=1):
        if probe in line:
            return line_index
    return None
