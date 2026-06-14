# scripts/cleanup_unicode.py
"""
Utility script that processes all recipe Markdown files to normalize smart quotes,
curly apostrophes, unicode ellipses, list-item middle dots, and incorrect degree symbols
in-place, while leaving legitimate accented letters and visual diagrams intact.
"""

from pathlib import Path

# Target directories to normalize
RECIPE_DIRECTORIES = [
    Path("../recipes"),
    Path("../in-progress"),
    Path("../curated-untested"),
]

# Normalization mapping for undesirable non-ASCII characters
PUNCTUATION_REPLACEMENTS = {
    "\u00BA": "°",  # Masculine ordinal indicator (ºC) -> Correct degree symbol (°C)
    "\u201C": '"',  # Left curly double quote (“) -> Standard straight double quote
    "\u201D": '"',  # Right curly double quote (”) -> Standard straight double quote
    "\u2018": "'",  # Left curly single quote (‘) -> Standard straight single quote
    "\u2019": "'",  # Right curly single quote/apostrophe (’) -> Standard straight single quote
    "\u2026": "...",  # Unicode horizontal ellipsis (…) -> Three periods
    "·":      "-",  # Unicode middle dot (·) -> Hyphen (commonly used in bullet lists)
}


def clean_unicode_content(raw_text: str) -> tuple[str, int]:
    """
    Applies punctuation replacements to a raw text string, tracking the replacement count.
    """
    modified_text = raw_text
    total_replacements = 0

    for non_ascii_char, replacement in PUNCTUATION_REPLACEMENTS.items():
        occurrences = modified_text.count(non_ascii_char)
        if occurrences > 0:
            modified_text = modified_text.replace(non_ascii_char, replacement)
            total_replacements += occurrences

    return modified_text, total_replacements


def run_unicode_cleanup():
    print("🧹 Running Unicode Punctuation Normalizer...")
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
                # Read the file with explicit UTF-8 encoding
                with markdown_file.open("r", encoding="utf-8") as read_file:
                    raw_content = read_file.read()
            except Exception as read_error:
                print(f"  ⚠️ Read error in {markdown_file}: {read_error}")
                continue

            cleaned_content, change_count = clean_unicode_content(raw_content)

            if change_count > 0:
                try:
                    # Save changes back to the file using UTF-8 to preserve accents
                    with markdown_file.open("w", encoding="utf-8") as write_file:
                        write_file.write(cleaned_content)

                    relative_path = markdown_file.relative_to(directory.parent)
                    print(f"  ✅ Cleaned {change_count} characters in: {relative_path}")
                    modifications_made += change_count
                except Exception as write_error:
                    print(f"  ❌ Write error in {markdown_file}: {write_error}")

            files_processed += 1

    print("\n📊 --- Unicode Normalization Complete ---")
    print(f"Total recipe files evaluated : {files_processed}")
    print(f"Total characters normalized  : {modifications_made}")


if __name__ == "__main__":
    run_unicode_cleanup()