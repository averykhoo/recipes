# recipe_parser/core/orchestrator.py
"""
The core orchestrator of the recipe parser package, coordinating
tokenization, sub-recipe splits, and semantic DOM AST block construction.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import frontmatter
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from recipe_parser.models.schemas import (
    BlockType, HeadingBlock, TextBlock, ListBlock, TableBlock,
    IngredientItem, Recipe, RecipeDocument
)
from recipe_parser.rules.directions import extract_flat_steps_recursively, scan_inline_metadata
from recipe_parser.rules.ingredients import parse_ingredient_line
from recipe_parser.rules.links import rewrite_markdown_links_to_html, wrap_bare_urls_in_markdown
from recipe_parser.rules.yields import extract_strict_yield, find_lax_yield_candidate
from recipe_parser.utils.sanitizer import sanitize_header_text
from recipe_parser.validation.characters import audit_non_ascii_characters
from recipe_parser.validation.consistency import audit_component_consistency
from recipe_parser.validation.linter import lint_recipe_document

# Standard regular expressions for sections
RE_ING_HEADER = re.compile(r'^ingredients(?:\s+for\s+(.+))?$', re.IGNORECASE)
RE_DIR_HEADER = re.compile(r'^(?:directions|instructions|method)(?:\s+for\s+(.+))?$', re.IGNORECASE)


def assemble_token_array(content_string: str) -> List[Dict[str, Any]]:
    """
    Traverses raw files using markdown-it-py and builds a simplified token dictionary list.
    Saves tables as structured dict tokens.
    """
    md_parser = MarkdownIt("gfm-like").enable("table")
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

        elif token.type == "table_open":
            table_tokens = []
            while index < len(markdown_tokens) and markdown_tokens[index].type != "table_close":
                table_tokens.append(markdown_tokens[index])
                index += 1
            if index < len(markdown_tokens):
                table_tokens.append(markdown_tokens[index])
                index += 1

            headers = []
            rows = []
            current_row = []
            is_header = False

            for t in table_tokens:
                if t.type == "thead_open":
                    is_header = True
                elif t.type == "thead_close":
                    is_header = False
                elif t.type == "tr_close":
                    if is_header:
                        headers = current_row
                    else:
                        rows.append(current_row)
                    current_row = []
                elif t.type == "inline":
                    current_row.append(t.content)

            simplified_tokens.append({
                "type":    "Table",
                "headers": headers,
                "rows":    rows
            })

        else:
            index += 1

    return simplified_tokens


def split_sub_recipes_into_raw_runs(tokens: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Splits the token list into distinct runs per recipe.
    """
    blocks = []
    current_block = []

    for index, token in enumerate(tokens):
        if token.get("type") == "ThematicBreak":
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


def build_hierarchical_blocks(block_tokens: List[Dict[str, Any]]) -> List[Any]:
    """
    Assembles a raw token stream into a flat sequence of structured,
    typed sibling block-nodes.
    """
    blocks = []

    # 1. Detect if the document contains Level 2 section dividers
    has_headers = any(
        token["type"] == "Heading" and token["level"] == 2
        for token in block_tokens
    )

    current_section_type = "preamble"
    current_component = None

    for token in block_tokens:
        # --- Heading Nodes ---
        if token["type"] == "Heading":
            # Skip Recipe Title H1 in the sibling block sequence
            if token["level"] == 1:
                continue

            heading_text = sanitize_header_text(token["text"])
            heading_lower = heading_text.lower()

            # Map semantic routing boundaries on Level 2 sub-headings
            section_type = "notes"
            component = None

            if token["level"] == 2:
                ing_match = RE_ING_HEADER.match(heading_text)
                dir_match = RE_DIR_HEADER.match(heading_text)

                if ing_match:
                    section_type = "ingredients"
                    component = ing_match.group(1) or "Main"
                elif dir_match:
                    section_type = "directions"
                    component = dir_match.group(1) or "Main"
                elif any(x in heading_lower for x in ["note", "comment", "science", "todo", "editor"]):
                    section_type = "notes"

                current_section_type = section_type
                current_component = component

            # Headings (including H3-H6) are appended as independent structural nodes
            blocks.append(HeadingBlock(
                level=token["level"],
                text=heading_text,
                section_type=section_type if token["level"] == 2 else "notes",
                component=component
            ))

        # --- Text Nodes (Paragraphs & Quotes) ---
        elif token["type"] in ("Paragraph", "Quote"):
            is_quote = (token["type"] == "Quote")

            if current_section_type == "ingredients" and has_headers:
                blocks.append(TextBlock(text=token["text"], is_quote=is_quote))
            else:
                blocks.append(TextBlock(text=token["text"], is_quote=is_quote))

        # --- Table Nodes ---
        elif token["type"] == "Table":
            blocks.append(TableBlock(headers=token["headers"], rows=token["rows"]))

        # --- List Nodes (Core Ingredients or Directions lists) ---
        elif token["type"] == "List":
            parser_engine = MarkdownIt()
            parsed_ast = parser_engine.parse(token["raw_text"])
            tree_root = SyntaxTreeNode(parsed_ast)
            steps_unrolled = extract_flat_steps_recursively(tree_root)

            list_block = ListBlock(ordered=token["ordered"])

            # Semantic extraction based on active container state
            is_ingredients_list = False
            if has_headers:
                if current_section_type == "ingredients":
                    is_ingredients_list = True
            else:
                # Headerless Fallback state machine
                if not token["ordered"]:
                    is_ingredients_list = True

            if is_ingredients_list:
                for raw_item in steps_unrolled:
                    parsed_ing = parse_ingredient_line(raw_item)
                    list_block.items.append(IngredientItem(
                        raw_line=raw_item,
                        parsed_ingredient=parsed_ing
                    ))
            else:
                # Directions list: Extract steps and run inline metadata scanning
                for idx, raw_step in enumerate(steps_unrolled):
                    list_block.items.append(raw_step)
                    temps, durations = scan_inline_metadata(raw_step)
                    if temps:
                        list_block.extracted_temps[idx] = temps
                    if durations:
                        list_block.extracted_durations[idx] = durations

            blocks.append(list_block)

    return blocks


def process_recipe_document(file_path: Path) -> Tuple[RecipeDocument, List[str]]:
    """
    Parses a single Markdown document, running layout, normalization,
    and semantic tokenization rules.
    """
    file_post = frontmatter.load(file_path)
    warnings = []

    # 1. Unicode character validation
    try:
        with file_path.open("r", encoding="utf-8") as raw_file:
            raw_text_content = raw_file.read()
        character_warnings = audit_non_ascii_characters(raw_text_content)
        warnings.extend(character_warnings)
    except Exception:
        logging.exception("Error validating unicode")

    # 2. Text preprocessing (URLs & local links)
    updated_content = wrap_bare_urls_in_markdown(file_post.content)
    updated_content = rewrite_markdown_links_to_html(updated_content)

    # 3. Assemble tokens and split blocks
    tokens = assemble_token_array(updated_content)
    recipe_runs = split_sub_recipes_into_raw_runs(tokens)

    compiled_recipes = []
    for index, run_tokens in enumerate(recipe_runs):
        title = f"Recipe {index + 1}"
        for token in run_tokens:
            if token["type"] == "Heading" and token["level"] == 1:
                title = sanitize_header_text(token["text"])
                break

        # Build flat DOM blocks
        sibling_blocks = build_hierarchical_blocks(run_tokens)

        # Extract strict yields from preamble
        preamble_blocks = []
        for block in sibling_blocks:
            if block.block_type == BlockType.HEADING and block.level == 2:
                break
            preamble_blocks.append(block)

        yield_val = extract_strict_yield(preamble_blocks, file_post.metadata)

        # 4. Fallback to lax scanning over preamble and notes blocks
        if not yield_val:
            candidate_yield = find_lax_yield_candidate(sibling_blocks)
            if candidate_yield:
                yield_val = candidate_yield
                warnings.append(
                    f"[{title}] Missing serving or yield metadata. "
                    f"Did you mean: \"{candidate_yield}\"?"
                )

        recipe_model = Recipe(
            title=title,
            yield_val=yield_val,
            blocks=sibling_blocks
        )

        # 5. Run Linter Audits (Conversions, Temperatures, Consistency, Unit checks)
        linter_warnings = lint_recipe_document(recipe_model)
        warnings.extend(linter_warnings)

        consistency_warnings = audit_component_consistency(recipe_model)
        warnings.extend(consistency_warnings)

        compiled_recipes.append(recipe_model)

    doc = RecipeDocument(
        source_file=str(file_path),
        metadata=file_post.metadata,
        recipes=compiled_recipes
    )

    return doc, warnings