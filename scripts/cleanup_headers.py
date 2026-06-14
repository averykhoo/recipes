# scripts/cleanup_headers.py
"""
Utility script that searches all recipe Markdown files, identifies
section headers with trailing colons, and cleans them directly
within the source files.
"""

import re
from pathlib import Path
import frontmatter

# Target directories to clean up
RECIPE_DIRECTORIES = [
    Path("recipes"),
    Path("in-progress"),
    Path("curated-untested"),
]

# Matches headers ending in trailing colons
RE_HEADER_COLON = re.compile(r"^(?P<prefix>#{2,6}\s+)(?P<title>.+?)(?P<colon>:)\s*$")


def process_header_lines(markdown_body: str) -> tuple[str, int]:
    """
    Scans document bodies line-by-line and removes trailing colons from headers.
    """
    lines = markdown_body.splitlines()
    processed_lines = []
    modifications = 0

    for line in lines:
        header_match = RE_HEADER_COLON.match(line)
        if header_match:
            cleaned_header = f"{header_match.group('prefix')}{header_match.group('title').strip()}"
            processed_lines.append(cleaned_header)
            modifications += 1
        else:
            processed_lines.append(line)

    return "\n".join(processed_lines), modifications


def run_header_cleanup():
    print("🧹 Running Header Colon Normalizer...")
    files_processed = 0
    modifications_made = 0

    for directory in RECIPE_DIRECTORIES:
        if not directory.exists():
            continue

        print(f"\nScanning directory: {directory}/")
        for markdown_file in directory.glob("**/*.[mM][dD]"):
            if markdown_file.name == "index.md":
                continue

            try:
                recipe_post = frontmatter.load(markdown_file)
            except Exception as read_error:
                print(f"  ⚠️ Read error in {markdown_file}: {read_error}")
                continue

            cleaned_content, file_changes = process_header_lines(recipe_post.content)

            if file_changes > 0:
                recipe_post.content = cleaned_content
                # Update the file content
                with markdown_file.open("w", encoding="utf-8") as write_file:
                    frontmatter.dump(recipe_post, write_file)

                relative_path = markdown_file.relative_to(directory.parent)
                print(f"  ✅ Removed {file_changes} colon(s) from: {relative_path}")
                modifications_made += 1

            files_processed += 1

    print("\n📊 --- Header Normalization Complete ---")
    print(f"Total recipe files evaluated : {files_processed}")
    print(f"Total files updated          : {modifications_made}")


if __name__ == "__main__":
    run_header_cleanup()