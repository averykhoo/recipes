# recipe_parser/rules/links.py
"""
Rule processor for wrapping bare web links in angle brackets and
rewriting local Markdown link extensions to target HTML outputs.
"""

import re

# Identifies standard Markdown links or images to protect them from double-processing
RE_MARKDOWN_LINK_OR_IMAGE = re.compile(
    r"!?\[(?:\\\[|\\\]|[^\]])*\]\((?:\\\(|\\\)|[^)])*\)",
    re.DOTALL
)

# Identifies bare web links that are not already enclosed inside brackets or parentheses
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
    protected_links = []

    # Extract and protect standard Markdown links or image blocks first
    def link_protection_callback(match) -> str:
        protected_links.append(match.group(0))
        return f"__LINK_PLACEHOLDER_{len(protected_links) - 1}__"

    protected_content = RE_MARKDOWN_LINK_OR_IMAGE.sub(link_protection_callback, markdown_content)

    # Enclose bare URLs inside angle brackets
    protected_content = RE_BARE_WEB_URL.sub(r"<\1>", protected_content)

    # Restore the original Markdown links and images
    def link_restoration_callback(match) -> str:
        link_index = int(match.group(1))
        return protected_links[link_index]

    restored_content = re.sub(r"__LINK_PLACEHOLDER_(\d+)__", link_restoration_callback, protected_content)
    return restored_content


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