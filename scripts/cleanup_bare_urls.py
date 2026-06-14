# scripts/cleanup_bare_urls.py
"""
Utility script that processes all recipe Markdown files to enclose
bare web URLs inside <...> brackets directly in the source files.
"""

from pathlib import Path
import frontmatter
from recipe_parser.rules.links import wrap_bare_urls_in_markdown

# Target directories to clean up
RECIPE_DIRECTORIES = [
    Path("../recipes"),
    Path("../in-progress"),
    Path("../curated-untested"),
]


def run_url_cleanup():
    print("🧹 Running Bare URL Normalizer...")
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

            # Enclose bare URLs inside angle brackets
            cleaned_content = wrap_bare_urls_in_markdown(recipe_post.content)

            if cleaned_content != recipe_post.content:
                if recipe_post.metadata:
                    recipe_post.content = cleaned_content
                    # Write the updated content back to the source file
                    with markdown_file.open("wb") as write_file:
                        frontmatter.dump(recipe_post, write_file, encoding="utf-8")
                else:
                    with markdown_file.open("w", encoding='utf-8') as write_file:
                        write_file.write(cleaned_content)

                relative_path = markdown_file.relative_to(directory.parent)
                print(f"  ✅ Wrapped URLs in: {relative_path}")
                modifications_made += 1

            files_processed += 1

    print("\n📊 --- URL Normalization Complete ---")
    print(f"Total recipe files evaluated : {files_processed}")
    print(f"Total files updated          : {modifications_made}")


if __name__ == "__main__":
    run_url_cleanup()