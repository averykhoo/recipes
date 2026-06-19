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
    steps = []

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
        if cleaned_text:
            steps.append(cleaned_text)

        for child in node.children:
            if child.type in ("bullet_list", "ordered_list"):
                steps.extend(extract_flat_steps_recursively(child))

        return steps

    for child in node.children:
        steps.extend(extract_flat_steps_recursively(child))

    return steps
