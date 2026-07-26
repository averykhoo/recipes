"""Shared helpers for the document-level parser tests.

Every test here drives the real entry point, `process_recipe_document`, against a
markdown file written into pytest's ``tmp_path``. Nothing is stubbed: if a snippet
parses here it parses in production.
"""

import textwrap
from pathlib import Path
from typing import Callable
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import pytest

from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import RecipeDocument
from recipe_parser.validation.diagnostics import Diagnostic

ParseResult = Tuple[RecipeDocument, List[Diagnostic]]


@pytest.fixture
def write_recipe(tmp_path: Path) -> Callable[..., Path]:
    """Returns a callable that drops a markdown snippet into tmp_path and returns its Path."""
    counter = {"n": 0}

    def _write(
            content: Union[str, bytes, None],
            name: Optional[str] = None,
            *,
            dedent: bool = True,
            newline: str = "\n",
    ) -> Path:
        counter["n"] += 1
        path = tmp_path / (name or f"recipe_{counter['n']}.md")

        if isinstance(content, bytes):
            path.write_bytes(content)
            return path

        text = "" if content is None else content
        if dedent:
            text = textwrap.dedent(text)
        with path.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
        return path

    return _write


@pytest.fixture
def parse(write_recipe) -> Callable[..., ParseResult]:
    """Writes a markdown snippet and parses it, returning ``(document, diagnostics)``."""
    from recipe_parser.core.orchestrator import process_recipe_document

    def _parse(content, name=None, **kwargs) -> ParseResult:
        path = write_recipe(content, name, **kwargs)
        return process_recipe_document(path)

    return _parse


# --- small query helpers, kept here so both test modules read the same way -------------

def codes(diagnostics: List[Diagnostic]) -> List[str]:
    """Diagnostic codes in emission order."""
    return [d.code for d in diagnostics]


def by_code(diagnostics: List[Diagnostic], code: str) -> List[Diagnostic]:
    """Every diagnostic carrying ``code``."""
    return [d for d in diagnostics if d.code == code]


def blocks_of(recipe, block_type: BlockType) -> list:
    """Blocks of one physical kind, in document order."""
    return [b for b in recipe.blocks if b.block_type == block_type]


def lists_of(recipe) -> list:
    """Every ListBlock in the recipe, in document order."""
    return blocks_of(recipe, BlockType.LIST)


def headings_of(recipe) -> list:
    """Every HeadingBlock in the recipe, in document order."""
    return blocks_of(recipe, BlockType.HEADING)


def block_shape(recipe) -> List[Tuple[str, Optional[str]]]:
    """A compact ``(block_type, section_type)`` signature of the whole block sequence."""
    shape = []
    for block in recipe.blocks:
        shape.append((block.block_type.value, getattr(block, "section_type", None)))
    return shape
