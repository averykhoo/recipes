# recipe_parser/core/orchestrator.py
"""
The core orchestrator of the recipe parser package, coordinating
frontmatter reading, sub-recipe splitting, block-level AST analysis,
and structured serialization.
"""

import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
import frontmatter
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from recipe_parser.models.schemas import (
    Recipe,
    RecipeDocument,
    IngredientsComponent,
    DirectionsComponent,
)
from recipe_parser.rules.ingredients import parse_ingredient_line
from recipe_parser.rules.directions import extract_flat_steps_recursively
from recipe_parser.rules.links import wrap_bare_urls_in_markdown, rewrite_markdown_links_to_html
from recipe_parser.utils.sanitizer import sanitize_header_text
from recipe_parser.validation.consistency import audit_component_consistency


class RecipeBlock:
    """
    A helper structure representing the block-level elements
    of a single parsed recipe.
    """
    def __init__(self):
        self.title: Optional[str] = None
        self.yield_val: Optional[str] = None
        self.ingredients: Dict[Optional[str], List[str]] = {}
        self.directions: Dict[Optional[str], List[str]] = {}
        self.notes: List[str] = []


def split_sub_recipes(tokens: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Splits the Markdown token array at thematic breaks only when they are
    immediately followed by a Level 1 Heading (# Title).
    """
    blocks = []
    current_block = []

    for index, token in enumerate(tokens):
        if token.get("type") == "ThematicBreak":
            # Peek ahead to verify if the next block represents a Level 1 Heading
            next_is_heading_1 = False
            for peek_index in range(index + 1, len(tokens)):
                peek_token = tokens[peek_index]
                if peek_token.get("type") == "Heading":
                    if peek_token.get("level") == 1:
                        next_is_heading_1 = True
                    break
                if peek_token.get("type") != "ThematicBreak":
                    break

            if next_is_heading_1:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
                continue

        current_block.append(token)

    if current_block:
        blocks.append(current_block)

    return blocks


def parse_structural_elements(block_tokens: List[Dict[str, Any]]) -> RecipeBlock:
    """
    Evaluates layout and compiles list tokens into raw structural groups.
    If the document has no headers, it evaluates each line inside list blocks
    independently to support plain lists and interleaved ingredients/directions.
    """
    recipe_block = RecipeBlock()
    current_section = None
    current_component = None

    # Establish a tracking scan to check if standard section headers are defined
    has_ingredients_header = False
    has_directions_header = False

    for token in block_tokens:
        if token["type"] == "Heading" and token["level"] == 2:
            clean_title = sanitize_header_text(token["text"])
            if clean_title.lower().startswith("ingredients"):
                has_ingredients_header = True
            elif clean_title.lower().startswith(("directions", "instructions", "method")):
                has_directions_header = True

    has_headers = has_ingredients_header or has_directions_header

    for token in block_tokens:
        if token["type"] == "ThematicBreak":
            # Reset active section boundaries on thematic breaks inside a block
            current_section = None
            current_component = None
            continue

        if token["type"] == "Heading":
            if token["level"] == 1:
                recipe_block.title = sanitize_header_text(token["text"])
            elif token["level"] == 2:
                clean_title = sanitize_header_text(token["text"])
                title_lower = clean_title.lower()

                # Check for sub-component definitions (for example: "Ingredients for the dough")
                if title_lower.startswith("ingredients"):
                    current_section = "ingredients"
                    # Perform a case-insensitive regular expression split to isolate the component name
                    split_parts = re.split(r"\s+for\s+", clean_title, maxsplit=1, flags=re.IGNORECASE)
                    if len(split_parts) > 1:
                        current_component = split_parts[1].strip()
                    else:
                        current_component = None  # Resets to standard main component
                elif title_lower.startswith(("directions", "instructions", "method")):
                    current_section = "directions"
                    # Perform a case-insensitive regular expression split to isolate the component name
                    split_parts = re.split(r"\s+for\s+", clean_title, maxsplit=1, flags=re.IGNORECASE)
                    if len(split_parts) > 1:
                        current_component = split_parts[1].strip()
                    else:
                        current_component = None
                elif any(note_keyword in title_lower for note_keyword in
                         ("note", "comment", "science", "todo", "editor")):
                    current_section = "notes"
                    current_component = None
                else:
                    current_section = None
                    current_component = None
            continue

        if token["type"] == "Quote":
            recipe_block.notes.append(token["text"])
            continue

        if token["type"] == "Paragraph":
            text_run = token["text"].strip()
            # Ignore lines starting with "Serve" when scanning for yield keywords
            if "yield" in text_run.lower() or "serves" in text_run.lower():
                if not text_run.lower().startswith("serve"):
                    recipe_block.yield_val = text_run
            elif current_section == "notes" or current_section is None:
                recipe_block.notes.append(text_run)
            continue

        if token["type"] == "List":
            # Use recursive walk to prevent nested list flattening errors
            parser_engine = MarkdownIt()
            parsed_ast = parser_engine.parse(token["raw_text"])
            tree_root = SyntaxTreeNode(parsed_ast)
            steps_unrolled = extract_flat_steps_recursively(tree_root)

            if not has_headers:
                # Fallback layout: Route lines individually to support plain or interleaved lists
                for item in steps_unrolled:
                    stripped_item = item.strip()
                    # Check if the line is ordered (for example: starts with "1." or "2)")
                    is_ordered = bool(re.match(r"^\d+[\.\)]", stripped_item))
                    if is_ordered:
                        recipe_block.directions.setdefault(None, []).append(item)
                    else:
                        recipe_block.ingredients.setdefault(None, []).append(item)
            else:
                # Headered layout: Route all items to the currently active section
                current_section_node = current_section
                if current_section_node == "ingredients":
                    recipe_block.ingredients.setdefault(current_component, []).extend(steps_unrolled)
                elif current_section_node == "directions":
                    recipe_block.directions.setdefault(current_component, []).extend(steps_unrolled)
                elif current_section_node == "notes":
                    recipe_block.notes.extend(steps_unrolled)

    return recipe_block


def assemble_token_array(content_string: str) -> List[Dict[str, Any]]:
    """
    Traverses raw files using markdown-it-py and builds a simplified token dictionary list.
    Contains robust defensive boundaries to prevent list indexing crashes.
    """
    md_parser = MarkdownIt()
    markdown_tokens = md_parser.parse(content_string)
    simplified_tokens = []

    index = 0
    while index < len(markdown_tokens):
        token = markdown_tokens[index]

        if token.type == "hr":
            simplified_tokens.append({"type": "ThematicBreak"})
            index += 1

        elif token.type == "heading_open":
            level = int(token.tag[1:]) if token.tag and len(token.tag) > 1 else 2
            index += 1
            inline_contents = []
            while index < len(markdown_tokens) and markdown_tokens[index].type != "heading_close":
                if markdown_tokens[index].type == "inline":
                    inline_contents.append(markdown_tokens[index].content)
                index += 1
            simplified_tokens.append({
                "type":  "Heading",
                "level": level,
                "text":  "".join(inline_contents)
            })
            if index < len(markdown_tokens):
                index += 1

        elif token.type == "paragraph_open":
            index += 1
            inline_contents = []
            while index < len(markdown_tokens) and markdown_tokens[index].type != "paragraph_close":
                if markdown_tokens[index].type == "inline":
                    inline_contents.append(markdown_tokens[index].content)
                index += 1
            simplified_tokens.append({
                "type": "Paragraph",
                "text": "".join(inline_contents)
            })
            if index < len(markdown_tokens):
                index += 1

        elif token.type in ("bullet_list_open", "ordered_list_open"):
            is_ordered = (token.type == "ordered_list_open")
            # Safe extraction of token map lines with defaults
            list_start = token.map[0] if (token.map and len(token.map) > 0) else 0
            list_close_type = "bullet_list_close" if not is_ordered else "ordered_list_close"
            list_end = token.map[1] if (token.map and len(token.map) > 1) else len(content_string.splitlines())

            while index < len(markdown_tokens) and markdown_tokens[index].type != list_close_type:
                if markdown_tokens[index].map and len(markdown_tokens[index].map) > 1:
                    list_end = markdown_tokens[index].map[1]
                index += 1

            raw_lines = content_string.splitlines()[list_start:list_end]
            simplified_tokens.append({
                "type":     "List",
                "ordered":  is_ordered,
                "raw_text": "\n".join(raw_lines)
            })
            if index < len(markdown_tokens):
                index += 1

        elif token.type == "blockquote_open":
            index += 1
            quote_contents = []
            while index < len(markdown_tokens) and markdown_tokens[index].type != "blockquote_close":
                if markdown_tokens[index].type == "inline":
                    quote_contents.append(markdown_tokens[index].content)
                index += 1
            simplified_tokens.append({
                "type": "Quote",
                "text": " ".join(quote_contents)
            })
            if index < len(markdown_tokens):
                index += 1
        else:
            index += 1

    return simplified_tokens


def process_recipe_document(file_path: Path) -> Tuple[RecipeDocument, List[str]]:
    """
    Parses a single Markdown document, running layout, normalization,
    and semantic tokenization rules.
    """
    file_post = frontmatter.load(file_path)
    warnings = []

    # Process text-level rules (bare URLs and local link extensions)
    updated_content = wrap_bare_urls_in_markdown(file_post.content)
    updated_content = rewrite_markdown_links_to_html(updated_content)

    tokens = assemble_token_array(updated_content)
    recipe_blocks = split_sub_recipes(tokens)

    compiled_recipes = []
    for index, block_tokens in enumerate(recipe_blocks):
        parsed_block = parse_structural_elements(block_tokens)

        # Resolve H1 title falls
        if not parsed_block.title:
            if index == 0 and "title" in file_post.metadata:
                parsed_block.title = file_post.metadata["title"]
                warnings.append("Missing H1 Title ('# Title') at start of file block (using frontmatter instead).")
            else:
                parsed_block.title = f"Recipe {index + 1}"
                warnings.append("Missing H1 Title ('# Title') in this recipe block.")

        # Resolve yield parameters
        if not parsed_block.yield_val:
            for yield_key in ("yield", "yields", "serves", "servings", "portions", "pax"):
                if yield_key in file_post.metadata:
                    parsed_block.yield_val = str(file_post.metadata[yield_key])
                    break
            if not parsed_block.yield_val:
                warnings.append(f"[{parsed_block.title}] Missing serving or yield metadata.")

        # Bind ingredients and step components
        structured_ingredients = []
        for component_name, items in parsed_block.ingredients.items():
            parsed_items = []
            for raw_item in items:
                ingredient = parse_ingredient_line(raw_item)
                if ingredient:
                    parsed_items.append(ingredient)
            structured_ingredients.append(
                IngredientsComponent(component=component_name, items=parsed_items)
            )

        structured_directions = []
        for component_name, steps in parsed_block.directions.items():
            structured_directions.append(
                DirectionsComponent(component=component_name, steps=steps)
            )

        recipe_model = Recipe(
            title=parsed_block.title,
            yield_val=parsed_block.yield_val,
            ingredients=structured_ingredients,
            directions=structured_directions,
            notes=parsed_block.notes
        )

        # Run read-only component consistency validations
        consistency_warnings = audit_component_consistency(recipe_model)
        for warning in consistency_warnings:
            warnings.append(f"[{recipe_model.title}] {warning}")

        compiled_recipes.append(recipe_model)

    doc = RecipeDocument(
        source_file=str(file_path),
        metadata=file_post.metadata,
        recipes=compiled_recipes
    )

    return doc, warnings