# recipe_parser/validation/characters.py
"""
Validation module for identifying non-ASCII characters inside recipe files,
supporting a configurable whitelist of allowed Unicode characters.
"""

from typing import List

# Whitelist of allowed non-ASCII Unicode characters.
# This list can be modified by the author to suppress warnings for legitimate characters.
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
}


def audit_non_ascii_characters(content_string: str) -> List[str]:
    """
    Scans the raw document content and identifies any non-ASCII characters
    that are not explicitly defined in the allowed whitelist.
    Returns a list of warning messages specifying the exact character, its
    official Unicode name, and the line context in which it appears.
    To avoid redundant outputs, each unique unlisted character is reported
    only once per line.
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
