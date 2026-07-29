# recipe_parser/rules/links.py
"""
Rule processor for wrapping bare web links in angle brackets, plus the single
canonical Markdown link pattern the rest of the parser reads links with.
"""

import re

# --- The canonical Markdown link/image pattern --------------------------------
# One definition, used both to protect links from the bare-URL rewriter here and to split
# an ingredient's own words from its cross-reference target in rules/ingredients.py. There
# were previously two patterns for the same construct and they had drifted apart, so a
# link one of them could read was corrupted by the other.
#
# The link text stops at the first unescaped "]".
_LINK_TEXT = r"(?:\\.|[^\]\\])*"

# The destination allows one level of balanced parentheses, as CommonMark does. This
# corpus links to Wikipedia, and "https://en.wikipedia.org/wiki/Custard_(dessert)" ends in
# a ")" that belongs to the URL followed by a ")" that closes the link. A flat "[^)]*"
# stops at the first of the two and corrupts the target and the link text together.
# Spaces are deliberately allowed: local paths here contain them, as in
# "[docx](Chocolate Chip Cookies.docx)".
_LINK_TARGET = r"(?:\\.|\((?:\\.|[^()\\])*\)|[^()\\])*?"

# Identifies standard Markdown links or images, capturing their parts.
RE_MARKDOWN_LINK_OR_IMAGE = re.compile(
    rf"(?P<image>!)?\[(?P<text>{_LINK_TEXT})\]\(\s*(?P<target>{_LINK_TARGET})\s*\)",
    re.DOTALL,
)

# Identifies bare web links that are not already enclosed inside brackets or parentheses
RE_BARE_WEB_URL = re.compile(
    r'(?<![<"\'`=])(?<!]\()(https?://[^\s<>"\'`]+[^\s<>"\'`.,;:!?)]+)',
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

# NOTE: a `rewrite_markdown_links_to_html` helper used to live here, rewriting local ".md"
# link targets to ".html". It was called by nothing: it is a *rendering* transform, and
# running it before parsing made every stored raw_line quote a ".html" target that appears
# in no source file. The published site does its own rewriting in
# .jekyll-build/scripts/jekyll_prebuild.py (RE_MARKDOWN_LINK_MD), which is the only copy
# that actually runs. Keeping an unreachable second implementation of the same rewrite
# only invited the two to disagree, so it was deleted rather than left to rot.
