# recipe_parser/rules/yields.py
"""
Rule processor for parsing strict yield metadata and identifying lax candidate
serving lines across the parsed flat-block AST sequence.
"""

import re
from typing import Any
from typing import List
from typing import Optional

RE_STRICT_YIELD_START = re.compile(r"^(?:yields?|serves?|makes|portions?|pax|servings?)\b", re.IGNORECASE)
RE_LAX_YIELD_KEYWORDS = re.compile(
    r"\b(yields?|serves?|serving?s?|makes?|pax|portions?|people|quantit(?:y|ies)|qty|pieces?|squares?|slices?|loaves|cookies?|biscuits?|buns?|puffs?|muffins?)\b",
    re.IGNORECASE
)
RE_HAS_NUMBER = re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten)\b", re.IGNORECASE)
EXCLUDE_PREFIXES = ("serve immediately", "serve with", "serve hot", "serve cold", "serve alongside", "serve over",
                    "to serve", "toss to combine")


def extract_strict_yield(preamble_blocks: List[Any], metadata: dict[str, Any]) -> Optional[str]:
    """
    Checks frontmatter, then scans the preamble blocks strictly.
    """
    for yield_key in ("yield", "yields", "serves", "servings", "portions", "pax"):
        if yield_key in metadata:
            return str(metadata[yield_key]).strip()

    for block in preamble_blocks:
        if block.block_type == "text":
            for line in block.text.splitlines():
                line_stripped = line.strip().strip("*+-").strip()
                if RE_STRICT_YIELD_START.match(line_stripped):
                    if len(line_stripped.split()) <= 8 and RE_HAS_NUMBER.search(line_stripped):
                        return line_stripped
    return None


def find_lax_yield_candidate(all_blocks: List[Any]) -> Optional[str]:
    """
    Scans notes and narrative segments using the broad whitelist.
    """
    for block in all_blocks:
        if block.block_type == "text":
            for line in block.text.splitlines():
                line_stripped = line.strip().strip("*+-").strip()
                lower_line = line_stripped.lower()

                if lower_line.startswith(EXCLUDE_PREFIXES):
                    continue
                if lower_line.startswith("serve") and not RE_HAS_NUMBER.search(line_stripped):
                    continue

                words = line_stripped.split()
                if len(words) <= 8 and RE_HAS_NUMBER.search(line_stripped):
                    if RE_LAX_YIELD_KEYWORDS.search(line_stripped):
                        return line_stripped
    return None
