# recipe_parser/rules/directions.py
"""
Rule processor for parsing and recursively unrolling step lists
into clean, flat direction sequences.
"""

from typing import List

from markdown_it.tree import SyntaxTreeNode

from recipe_parser.utils.sanitizer import strip_html_and_markdown_comments


def extract_flat_steps_recursively(node: SyntaxTreeNode) -> List[str]:
    """
    Recursively walks markdown-it-py syntax tree nodes.
    This guarantees that nested instruction lists are unrolled sequentially
    without concatenating list boundaries together with newline characters.
    """
    steps = []

    if node.type == "list_item":
        # Process inline content for the current item, skipping nested list blocks
        text_content_runs = []
        for child in node.children:
            if child.type not in ("bullet_list", "ordered_list"):
                if child.type == "paragraph":
                    # Traverse nested paragraph children to find the true inline node contents
                    for grandchild in getattr(child, "children", []):
                        if grandchild.type == "inline" and grandchild.content:
                            text_content_runs.append(grandchild.content)
                elif child.type == "inline" and child.content:
                    text_content_runs.append(child.content)

        item_text = " ".join(text_content_runs).strip()
        cleaned_text = strip_html_and_markdown_comments(item_text)
        if cleaned_text:
            steps.append(cleaned_text)

        # Process any sub-lists nested under this list item
        for child in node.children:
            if child.type in ("bullet_list", "ordered_list"):
                steps.extend(extract_flat_steps_recursively(child))

        return steps

    # Traverse nested block containers
    for child in node.children:
        steps.extend(extract_flat_steps_recursively(child))

    return steps
