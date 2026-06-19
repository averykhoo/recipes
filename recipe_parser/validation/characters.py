# recipe_parser/validation/characters.py
"""
Validation module for identifying non-ASCII characters inside recipe files,
supporting a configurable whitelist of allowed Unicode characters.
"""

from typing import List

import unicodedata

# Whitelist of allowed non-ASCII Unicode characters.
ALLOWED_UNICODE_CHARACTERS = {
    "°",  # The degree symbol (for temperatures like 180°C)
    "–",  # En-dash (common for ranges)
    "—",  # Em-dash
    "½",  # Vulgar fraction one half
    "¼",  # Vulgar fraction one quarter
    "¾",  # Vulgar fraction three quarters
    "⅓",  # Vulgar fraction one third
    "⅔",  # Vulgar fraction two thirds
    "【",  # Left black lenticular bracket (used for metric conversions)
    "】",  # Right black lenticular bracket (used for metric conversions)
    # Whitelisted legitimate accented foreign characters
    "ó", "é", "ê", "è", "ñ", "ö", "ü",
    # Whitelisted layout matrix markers
    "⋮", "˙", "̣", "⋅"
}


def audit_non_ascii_characters(content_string: str) -> List[str]:
    """
    Scans the raw document content and identifies any non-ASCII characters
    that are not explicitly defined in the allowed whitelist.
    """
    warnings = []
    lines = content_string.splitlines()

    for line_index, line in enumerate(lines, start=1):
        seen_characters_on_line = set()

        for character in line:
            # Check if the character is non-ASCII (Unicode value greater than 127)
            if ord(character) > 127:
                if character not in ALLOWED_UNICODE_CHARACTERS and character not in seen_characters_on_line:
                    seen_characters_on_line.add(character)
                    # Retrieve the official Unicode name of the character
                    character_name = unicodedata.name(character, "UNKNOWN CHARACTER")
                    warnings.append(
                        f"Line {line_index}: Found non-ASCII character '{character}' "
                        f"({character_name}, Unicode: U+{ord(character):04X}) "
                        f"in line: \"{line.strip()}\""
                    )

    return warnings
