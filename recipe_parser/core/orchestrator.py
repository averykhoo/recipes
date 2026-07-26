# recipe_parser/core/orchestrator.py
"""
The core orchestrator of the recipe parser package, coordinating
tokenization, sub-recipe splits, and semantic DOM AST block construction.
"""

import logging
import re
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import frontmatter
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from recipe_parser.models.schemas import BlockType
from recipe_parser.models.schemas import HeadingBlock
from recipe_parser.models.schemas import IngredientItem
from recipe_parser.models.schemas import ListBlock
from recipe_parser.models.schemas import Recipe
from recipe_parser.models.schemas import RecipeDocument
from recipe_parser.models.schemas import TableBlock
from recipe_parser.models.schemas import TextBlock
from recipe_parser.rules.directions import extract_flat_steps_recursively
from recipe_parser.rules.directions import scan_inline_metadata
from recipe_parser.rules.ingredients import parse_ingredient_line
from recipe_parser.rules.links import rewrite_markdown_links_to_html
from recipe_parser.rules.links import wrap_bare_urls_in_markdown
from recipe_parser.rules.yields import extract_strict_yield
from recipe_parser.rules.yields import find_lax_yield_candidate
from recipe_parser.utils.sanitizer import sanitize_header_text
from recipe_parser.validation.characters import audit_non_ascii_characters
from recipe_parser.validation.completeness import audit_parse_completeness
from recipe_parser.validation.consistency import audit_component_consistency
from recipe_parser.validation.diagnostics import Code
from recipe_parser.validation.diagnostics import Diagnostic
from recipe_parser.validation.diagnostics import Severity
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
            list_end = token.map[1] if (token.map and len(token.map) > 1) else len(content_string.splitlines())

            # Walk to the close that matches THIS open, counting nesting depth. Scanning
            # for the first close of the same kind ends the outer list at the first nested
            # sub-list instead, truncating it and leaving the remaining items to surface
            # as stray empty lists.
            depth = 0
            while index < len(markdown_tokens):
                current = markdown_tokens[index]
                if current.type in ("bullet_list_open", "ordered_list_open"):
                    depth += 1
                elif current.type in ("bullet_list_close", "ordered_list_close"):
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1

            raw_lines = content_string.splitlines()[list_start:list_end]
            simplified_tokens.append({
                "type":     "List",
                "ordered":  is_ordered,
                "raw_text": "\n".join(raw_lines)
            })

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
    seen_ordered_list = False

    for token in block_tokens:
        # --- Heading Nodes ---
        if token["type"] == "Heading":
            # Skip Recipe Title H1 in the sibling block sequence
            if token["level"] == 1:
                continue

            heading_text = sanitize_header_text(token["text"])

            ing_match = RE_ING_HEADER.match(heading_text)
            dir_match = RE_DIR_HEADER.match(heading_text)

            if ing_match:
                section_type = "ingredients"
                component = ing_match.group(1) or "Main"
            elif dir_match:
                section_type = "directions"
                component = dir_match.group(1) or "Main"
            elif token["level"] == 2:
                # An unrecognised H2 closes whatever section was open; everything that is
                # not ingredients or directions is treated as commentary.
                section_type = "notes"
                component = None
            else:
                # H3-H6 are sub-headings *within* the enclosing H2 and must inherit its
                # section, otherwise ingredient lists nested under an "### Onion gravy"
                # style sub-heading get silently reclassified as notes.
                section_type = current_section_type
                component = current_component
                if section_type == "preamble":
                    # An H3 before any H2 has no section to inherit.
                    section_type = "notes"
                    component = None

            current_section_type = section_type
            current_component = component

            blocks.append(HeadingBlock(
                level=token["level"],
                text=heading_text,
                section_type=section_type,
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

            # Semantic extraction based on active container state
            inferred = False
            if has_headers:
                resolved_section = current_section_type
                resolved_component = current_component
            else:
                # Headerless fallback. Without headings the only signal is list style:
                # unordered lists before the first ordered list are ingredients, an
                # ordered list is directions, and any unordered list *after* directions
                # have started is commentary rather than more ingredients.
                inferred = True
                resolved_component = None
                if token["ordered"]:
                    resolved_section = "directions"
                    seen_ordered_list = True
                elif seen_ordered_list:
                    resolved_section = "notes"
                else:
                    resolved_section = "ingredients"

            if resolved_section == "preamble":
                # A list before the first section heading is front-matter prose (yields,
                # sourcing, "makes 16 meatballs"), not an unlabelled ingredients list.
                resolved_section = "preamble"

            is_ingredients_list = (resolved_section == "ingredients")

            list_block = ListBlock(
                ordered=token["ordered"],
                section_type=resolved_section,
                component=resolved_component,
                inferred_section=inferred,
            )

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


def process_recipe_document(file_path: Path) -> Tuple[RecipeDocument, List[Diagnostic]]:
    """
    Parses a single Markdown document, running layout, normalization,
    and semantic tokenization rules.

    Returns the structured document alongside every diagnostic raised while reading it.
    """
    file_post = frontmatter.load(file_path)
    warnings: List[Diagnostic] = []

    # 1. Unicode character validation
    raw_text_content = ""
    try:
        # utf-8-sig transparently drops a byte-order mark. It is an encoding artifact
        # rather than authored content, so it should not be reported as a stray character.
        with file_path.open("r", encoding="utf-8-sig") as raw_file:
            raw_text_content = raw_file.read()
        character_warnings = audit_non_ascii_characters(raw_text_content)
        warnings.extend(character_warnings)
    except Exception:
        logging.exception("Error validating unicode")

    source_lines = raw_text_content.splitlines()

    # 2. Text preprocessing (URLs & local links)
    # A byte-order mark sits in front of the first "#" and stops markdown-it from seeing
    # a heading at all, which silently costs the document its title.
    updated_content = file_post.content.lstrip("﻿")
    updated_content = wrap_bare_urls_in_markdown(updated_content)
    updated_content = rewrite_markdown_links_to_html(updated_content)

    # 3. Assemble tokens and split blocks
    tokens = assemble_token_array(updated_content)
    recipe_runs = split_sub_recipes_into_raw_runs(tokens)

    compiled_recipes = []
    for index, run_tokens in enumerate(recipe_runs):
        title = f"Recipe {index + 1}"
        for token in run_tokens:
            if token["type"] == "Heading" and token["level"] == 1:
                # An empty "#" heading is not a usable title; keep the positional fallback.
                heading_title = sanitize_header_text(token["text"])
                if heading_title:
                    title = heading_title
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
                warnings.append(Diagnostic(
                    severity=Severity.INFO,
                    code=Code.YIELD_INFERRED,
                    recipe=title,
                    context=candidate_yield,
                    message=(
                        "No yield line was found in the preamble, so one was inferred from "
                        "further down the document."
                    ),
                    detail=[
                        "to make this explicit, move a line like 'Serves 4' directly under the title",
                    ],
                ))

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

        completeness_warnings = audit_parse_completeness(recipe_model, source_lines)
        warnings.extend(completeness_warnings)

        compiled_recipes.append(recipe_model)

    # Ensure warnings returned are unique and preserve order
    seen = set()
    unique_warnings = []
    for diagnostic in warnings:
        key = (diagnostic.code, diagnostic.recipe, diagnostic.message, diagnostic.context)
        if key in seen:
            continue
        seen.add(key)
        unique_warnings.append(diagnostic)

    doc = RecipeDocument(
        source_file=str(file_path),
        metadata=file_post.metadata,
        recipes=compiled_recipes
    )

    return doc, unique_warnings
