# recipe_parser/rules/yields.py
"""
Rule processor for parsing strict yield metadata and identifying lax candidate
serving lines across both the preamble and body of recipe documents.
"""

import re
from typing import Any, Dict, List, Optional

# Matches lines starting strictly with standard serving keywords (excluding list bullets)
RE_STRICT_YIELD_START = re.compile(
    r"^(?:yields?|serves?|makes|portions?|pax|servings?)\b",
    re.IGNORECASE
)

# Broad whitelist matching singular/plural servings, counting nouns, or counts
RE_LAX_YIELD_KEYWORDS = re.compile(
    r"\b(yields?|serves?|serving?s?|makes?|pax|portions?|people|quantit(?:y|ies)|qty|pieces?|squares?|slices?|loaves|cookies?|biscuits?|buns?|puffs?|muffins?)\b",
    re.IGNORECASE
)

# Matches at least one digit or common written-out English number words
RE_HAS_NUMBER = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE
)

# Prefixes representing standard directional cooking steps to ignore during lax scans
EXCLUDE_PREFIXES = (
    "serve immediately", "serve with", "serve hot", "serve cold",
    "serve alongside", "serve over", "to serve", "toss to combine"
)


def extract_strict_yield(block_tokens: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Optional[str]:
    """
    Looks for a highly confident yield value. Checks YAML frontmatter first,
    then scans only the preamble blocks (tokens before the first level-2 subheading).
    """
    # 1. Evaluate YAML Frontmatter Metadata
    for yield_key in ("yield", "yields", "serves", "servings", "portions", "pax"):
        if yield_key in metadata:
            return str(metadata[yield_key]).strip()

    # 2. Slice block tokens to isolate the document preamble (pre-H2 blocks)
    preamble_tokens = []
    for token in block_tokens:
        if token.get("type") == "Heading" and token.get("level") == 2:
            break
        preamble_tokens.append(token)

    # 3. Scan the preamble for high-confidence matches
    for token in preamble_tokens:
        text_runs = []
        if token["type"] == "Paragraph":
            text_runs.append(token["text"])
        elif token["type"] == "List":
            text_runs.extend(token["raw_text"].splitlines())

        for text_run in text_runs:
            for line in text_run.splitlines():
                line_stripped = line.strip().strip("*+-").strip()

                # A strict match must begin with a yield keyword, have <= 8 words, and contain numeric values
                if RE_STRICT_YIELD_START.match(line_stripped):
                    if len(line_stripped.split()) <= 8 and RE_HAS_NUMBER.search(line_stripped):
                        return line_stripped

    return None


def find_lax_yield_candidate(block_tokens: List[Dict[str, Any]]) -> Optional[str]:
    """
    Scans all block tokens in the document (including below H2 headings, notes,
    and directions lists) using a broad whitelist. Ignores standard direction verbs.
    """
    for token in block_tokens:
        text_runs = []
        if token["type"] == "Paragraph":
            text_runs.append(token["text"])
        elif token["type"] == "List":
            text_runs.extend(token["raw_text"].splitlines())

        for text_run in text_runs:
            for line in text_run.splitlines():
                line_stripped = line.strip().strip("*+-").strip()
                lower_line = line_stripped.lower()

                # Skip obvious instructional action prefixes
                if lower_line.startswith(EXCLUDE_PREFIXES):
                    continue

                # Ignore standard instructional steps that don't specify quantities
                if lower_line.startswith("serve") and not RE_HAS_NUMBER.search(line_stripped):
                    continue

                # Apply length and numeric requirements
                words = line_stripped.split()
                if len(words) <= 8 and RE_HAS_NUMBER.search(line_stripped):
                    # Check against the broad noun and serving whitelist
                    if RE_LAX_YIELD_KEYWORDS.search(line_stripped):
                        return line_stripped

    return None