# recipe_parser/rules/directions.py
"""
Rule processor for parsing steps recursively and scanning step strings
for inline cooking durations (seconds) and temperatures.
"""

import re
from typing import List
from typing import Tuple

from markdown_it.tree import SyntaxTreeNode

from recipe_parser.utils.sanitizer import strip_html_and_markdown_comments

# A list item that says nothing but "optional:" is a group header rather than an item of
# its own: the nested list underneath it holds the ingredients that are optional.
RE_OPTIONAL_GROUP_HEADER = re.compile(r"^optional\s*:?\s*$", re.IGNORECASE)

# Matches temperatures (Celsius or Fahrenheit)
RE_TEMP = re.compile(r"\b(?P<val>\d+)\s*(?:°|deg|degrees)?\s*(?P<scale>[CF])\b", re.IGNORECASE)

# Matches durations: minutes, seconds, or hours
RE_DURATION = re.compile(
    r"\b(?P<val>\d+)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE
)


def scan_inline_metadata(step_text: str) -> Tuple[List[str], List[int]]:
    """
    Parses step strings and extracts structured lists of temperatures and
    durations (normalized to standard integer seconds).
    """
    temps = []
    durations = []

    # 1. Scan for temperatures
    for match in RE_TEMP.finditer(step_text):
        val = match.group("val")
        scale = match.group("scale").upper()
        temps.append(f"{val}°{scale}")

    # 2. Scan for durations
    for match in RE_DURATION.finditer(step_text):
        val = int(match.group("val"))
        unit = match.group("unit").lower()

        seconds = val
        if unit.startswith("min"):
            seconds = val * 60
        elif unit.startswith("hour") or unit.startswith("hr"):
            seconds = val * 3600

        durations.append(seconds)

    return temps, durations


def extract_flat_steps_recursively(node: SyntaxTreeNode) -> List[str]:
    """
    Traverses markdown-it nodes to cleanly unroll nested lists.
    """
    return [text for text, _ in extract_flagged_steps_recursively(node, group_headers_are_items=True)]


def extract_flagged_steps_recursively(
        node: SyntaxTreeNode,
        inherited_optional: bool = False,
        group_headers_are_items: bool = False,
) -> List[Tuple[str, bool]]:
    """
    Unrolls nested lists into (text, is_optional) pairs.

    A bare "optional:" item introduces its nested sub-list rather than naming anything, so
    its children inherit the marker and the header itself yields no item. Callers that
    want the raw text of every line back - directions, where "optional:" is prose like any
    other step - pass `group_headers_are_items` to keep the header in the output.
    """
    steps: List[Tuple[str, bool]] = []

    if node.type == "list_item":
        text_content_runs = []
        for child in node.children:
            if child.type not in ("bullet_list", "ordered_list"):
                if child.type == "paragraph":
                    for grandchild in getattr(child, "children", []):
                        if grandchild.type == "inline" and grandchild.content:
                            text_content_runs.append(grandchild.content)
                elif child.type == "inline" and child.content:
                    text_content_runs.append(child.content)

        item_text = " ".join(text_content_runs).strip()
        cleaned_text = strip_html_and_markdown_comments(item_text)

        has_sub_list = any(child.type in ("bullet_list", "ordered_list") for child in node.children)
        heads_an_optional_group = (
                not group_headers_are_items
                and has_sub_list
                and bool(RE_OPTIONAL_GROUP_HEADER.match(cleaned_text.strip()))
        )

        if cleaned_text and not heads_an_optional_group:
            steps.append((cleaned_text, inherited_optional))

        child_optional = inherited_optional or heads_an_optional_group
        for child in node.children:
            if child.type in ("bullet_list", "ordered_list"):
                steps.extend(extract_flagged_steps_recursively(
                    child, child_optional, group_headers_are_items))

        return steps

    for child in node.children:
        steps.extend(extract_flagged_steps_recursively(
            child, inherited_optional, group_headers_are_items))

    return steps
