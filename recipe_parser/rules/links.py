# recipe_parser/rules/links.py
"""
Rule processor for wrapping bare web links in angle brackets and
rewriting local Markdown link extensions to target HTML outputs.
"""

import re

# Identifies web links that are not already enclosed inside brackets or parentheses
RE_BARE_WEB_URL = re.compile(
    r'(?<![<"\'`=])(?<!]\()(https?://[^\s<>"\'`]+[^\s<>"\'`.,;:!?)]+)',
    re.IGNORECASE,
)

# Matches Markdown link structures pointing to internal .md documents
RE_LOCAL_MD_LINK = re.compile(
    r"(?P<link_text>\[(?:\\\[|\\\]|[^\]])*\])\((?P<path>[^)#\s]+\.md)(?P<anchor>[\s#][^)]*)?\)",
    re.IGNORECASE,
)


def wrap_bare_urls_in_markdown(markdown_content: str) -> str:
    """
    Locates bare web links inside Markdown texts and encloses them inside <...> brackets.
    """
    return RE_BARE_WEB_URL.sub(r"<\1>", markdown_content)


def rewrite_markdown_links_to_html(markdown_content: str) -> str:
    """
    Locates local Markdown link targets pointing to .md files and replaces
    their extension with .html to match Jekyll site outputs.
    """

    def link_replacement(match) -> str:
        text = match.group("link_text")
        path = match.group("path")
        anchor = match.group("anchor") or ""

        # Replace the extension
        html_path = re.sub(r"\.md$", ".html", path, flags=re.IGNORECASE)
        return f"{text}({html_path}{anchor})"

    return RE_LOCAL_MD_LINK.sub(link_replacement, markdown_content)
