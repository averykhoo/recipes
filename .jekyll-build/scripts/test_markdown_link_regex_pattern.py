from jekyll_prebuild import RE_MARKDOWN_LINK_MD
from jekyll_prebuild import RE_MARKDOWN_LINK_SUB

test_cases = [
    # --- POSITIVE CASES (SHOULD CHANGE) ---
    ("Simple link", "[link](file.md)", "[link](file.html)"),
    ("Simple link with path", "[link](path/to/file.md)", "[link](path/to/file.html)"),
    ("Case variation .MD", "[link](file.MD)", "[link](file.html)"),
    ("Case variation .mD", "[link](file.mD)", "[link](file.html)"),
    ("Link with anchor", "[link](file.md#anchor)", "[link](file.html#anchor)"),
    ("Link with title (double quotes)", '[link](file.md "My Title")', '[link](file.html "My Title")'),
    ("Link with title (single quotes)", "[link](file.md 'My Title')", "[link](file.html 'My Title')"),
    ("Link with anchor and title", '[link](file.md#anchor "My Title")', '[link](file.html#anchor "My Title")'),
    ("Multiple links on one line", "See [a](a.md) and [b](b.md).", "See [a](a.html) and [b](b.html)."),
    ("Link with .md in anchor", "[link](a.md#b.md)", "[link](a.html#b.md)"),
    ("Link with underscore in name", "[my_link](my_file.md)", "[my_link](my_file.html)"),
    ("Link with hyphen in name", "[my-link](my-file.md)", "[my-link](my-file.html)"),
    ("Multiple links on one line", "See [a](a.md) and [b](b.md).", "See [a](a.html) and [b](b.html)."),

    # --- Angle Bracket Positive Cases (Should Change) ---
    ("Angle bracket link", "[link](<file.md>)", "[link](<file.html>)"),
    ("Angle bracket with path", "[link](<path/to/file.md>)", "[link](<path/to/file.html>)"),
    ("Angle bracket with anchor", "[link](<file.md#anchor>)", "[link](<file.html#anchor>)"),
    ("Angle bracket with anchor and title", '[link](<file.md#anchor "title">)', '[link](<file.html#anchor "title">)'),
    ("Link with .md in anchor", "[link](a.md#b.md)", "[link](a.html#b.md)"),

    # --- Standard Negative Cases (Should NOT Change) ---
    ("Image link", "![img](image.md)", "![img](image.md)"),
    ("Image link with path", "![img](path/to/image.md)", "![img](path/to/image.md)"),
    ("Plain text, not a link", "This is a file (e.g., file.md).", "This is a file (e.g., file.md)."),
    ("Link to a non-md file", "[link](file.html)", "[link](file.html)"),
    ("Link to an anchor with .md in it", "[link](#anchor.md)", "[link](#anchor.md)"),
    ("Link where .md is in the title", "[link](file.html 'title.md')", "[link](file.html 'title.md')"),
    ("Link where .md is not at the end", "[link](file.mdf)", "[link](file.mdf)"),
    ("Reference-style link definition", "[reflink]: my-file.md", "[reflink]: my-file.md"),
    ("URL with .md in it", "Go to https://example.com/file.md/page", "Go to https://example.com/file.md/page"),
    ("Link with no path, just anchor", "[link](#anchor)", "[link](#anchor)"),

    # --- NEW & WEIRD STRESS TESTS ---

    # Malformed & Tricky Links (Should NOT Change)
    ("Malformed link (no closing paren)", "[link](file.md", "[link](file.md"),
    ("Malformed link (space in path)", "[link](my file.md)", "[link](my file.md)"),
    ("Escaped brackets in link text", "[a\\]b](file.md)", "[a\\]b](file.html)"),  # This one should change
    ("Inline code with just the URL part", "Use `(file.md)` to refer to it.", "Use `(file.md)` to refer to it."),
    ("Just an image link", "![alt text](image.md)", "![alt text](image.md)"),
    ("Text immediately after image link", "![alt text](image.md)nochange", "![alt text](image.md)nochange"),

    # links cannot contain links, so the outer link is bogus
    ("Link inside a (broken) link's text", "[[inner](inner.md)](outer.md)", "[[inner](inner.html)](outer.md)"),

    # Should change both
    ("Link where .md is part of the title attribute", '[link](file.txt "title with file.md")',
     '[link](file.txt "title with file.md")'),

    # Spacing variations (Should Change)
    ("No space between link parts", "[text](file.md)", "[text](file.html)"),
    ("Space inside URL before .md", "[link](my file.md)", "[link](my file.md)"),
    # This is invalid Markdown, should not change
    ("Link with excessive space in title", '[link](file.md      "My Title"    )',
     '[link](file.html      "My Title"    )'),

    # Complex paths (Should Change)
    ("Relative path", "[link](../relative/path.md)", "[link](../relative/path.html)"),
    ("Path with dots", "[link](version.1.2.md)", "[link](version.1.2.html)"),

    # Very tricky negatives (Should NOT change)
    ("URL in plain text", "http://example.com/page.md", "http://example.com/page.md"),
    ("Email context", "<info@example.md>", "<info@example.md>"),  # This is not a markdown link
    ("HTML link", '<a href="file.md">link</a>', '<a href="file.md">link</a>'),
    ("Image link immediately after text", "text![img](image.md)", "text![img](image.md)"),

    # currently failing
    ("Code block with markdown link", "```\n[link](code.md)\n```", "```\n[link](code.md)\n```"),
    ("Long code block with markdown link", "``````\n[link](code.md)\n``````", "``````\n[link](code.md)\n``````"),
    ("Inline code with link syntax", "`[link](code.md)`", "`[link](code.md)`"),
    ("Image inside another link's text", "[![inner](inner.jpg)](outer.md)", "[![inner](inner.jpg)](outer.html)"),
]

if __name__ == '__main__':

    print("--- Running Regex Test Suite ---\n")
    print(f'{RE_MARKDOWN_LINK_MD=!r}')
    print(f'{RE_MARKDOWN_LINK_SUB=}')

    failed = []

    for i, (desc, input_str, expected) in enumerate(test_cases):
        print(f"Test {i + 1}: {desc}")
        print(f"  Input:    '{input_str}'")

        # --- Test Your Regex ---
        your_result = RE_MARKDOWN_LINK_MD.sub(RE_MARKDOWN_LINK_SUB, input_str)
        your_pass = your_result == expected
        your_status = f"PASS" if your_pass else f"FAIL"
        print(f"  Your Regex Result: '{your_result}' [{your_status}]")

        if not your_pass:
            print(f"  Expected: '{expected}'")
            failed.append(i + 1)

        print("-" * 20)

    print(f'passed: {len(test_cases) - len(failed)}')
    print(f'failed: {failed}')
