# recipe_parser/utils/sanitizer.py
"""
Utility module for stripping HTML and Markdown comments,
as well as cleaning trailing colons or extra spaces from titles.
"""

import re

# Matches standard HTML comments: <!-- comment -->
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# Matches Markdown link reference comments: [//]: # (comment)
RE_MARKDOWN_COMMENT = re.compile(r"^\[//\]:\s*#\s*\(.*?\)$")


def strip_html_and_markdown_comments(text_line: str) -> str:
    """
    Removes standard inline HTML comments and Markdown hack comments from a text string.
    """
    # Remove HTML comments
    text_line = RE_HTML_COMMENT.sub("", text_line)

    # Remove Markdown comment reference blocks if they appear on independent lines
    lines = text_line.splitlines()
    cleaned_lines = [line for line in lines if not RE_MARKDOWN_COMMENT.match(line.strip())]

    return "\n".join(cleaned_lines).strip()


def sanitize_header_text(header_title: str) -> str:
    """
    Normalizes header titles by removing trailing colons, comments, and extra spaces.
    """
    header_title = strip_html_and_markdown_comments(header_title)
    return header_title.rstrip(":").strip()
