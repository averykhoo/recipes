# scripts/cleanup_fractions.py
"""
Utility script that processes all recipe Markdown files to normalize ASCII and
Unicode vulgar fractions to decimals, strictly targeting ingredient lines.
"""

import re
import unicodedata
from pathlib import Path
import frontmatter

# --- Configuration ---
# These are the target directories containing your recipe Markdown files.
RECIPE_DIRECTORIES = [
    Path("../recipes"),
    Path("../in-progress"),
    Path("../curated-untested"),
]

# Regular expression to match mixed numbers with ASCII fractions (for example: "1 1/2", "2 3/4")
RE_MIXED_ASCII = re.compile(r"\b(?P<whole>\d+)\s+(?P<num>\d+)/(?P<den>\d+)\b")

# Regular expression to match standalone ASCII fractions (for example: "1/2", "3/4")
RE_SIMPLE_ASCII = re.compile(r"\b(?P<num>\d+)/(?P<den>\d+)\b")

# Regular expression to match Unicode vulgar fractions with space preservation
RE_VULGAR = re.compile(r"(?:(?P<whole>\d+)\s*)?(?P<vulgar>[\u00BC-\u00BE\u2150-\u215E])")

# Regular expression to identify web links and protect them from modification
RE_URL = re.compile(r"https?://[^\s]+")


# --- Float Normalization Helper ---

def format_decimal(value: float) -> str:
    """
    Formats a floating-point value to a clean decimal string.
    If the value is a whole number, it returns an integer string.
    """
    if value.is_integer():
        return str(int(value))

    # Check if rounding to two decimal places is highly precise (for example: 0.25, 0.50, 0.75)
    rounded_two_digits = round(value, 2)
    if abs(value - rounded_two_digits) < 1e-4:
        return f"{rounded_two_digits:.2f}".rstrip("0").rstrip(".")

    # Otherwise, fallback to three decimal places (for example: 0.333, 0.667)
    rounded_three_digits = round(value, 3)
    return f"{rounded_three_digits:.3f}".rstrip("0").rstrip(".")


# --- Regex Replacement Callbacks ---

def convert_mixed_ascii_match(match) -> str:
    whole = int(match.group("whole"))
    num = int(match.group("num"))
    den = int(match.group("den"))
    decimal_value = whole + (num / den)
    return format_decimal(decimal_value)


def convert_simple_ascii_match(match) -> str:
    num = int(match.group("num"))
    den = int(match.group("den"))
    decimal_value = num / den
    return format_decimal(decimal_value)


def convert_vulgar_match(match) -> str:
    whole_string = match.group("whole")
    whole = int(whole_string) if whole_string else 0
    vulgar_character = match.group("vulgar")
    fractional_value = unicodedata.numeric(vulgar_character)
    decimal_value = whole + fractional_value
    return format_decimal(decimal_value)


def normalize_fractions_in_string(text_line: str) -> str:
    """
    Normalizes fractions to decimals while protecting any URLs inside the string.
    """
    protected_urls = []

    # Temporarily extract and protect URLs to prevent matching date runs like 2022/12
    def url_protection_callback(match) -> str:
        protected_urls.append(match.group(0))
        return f"__URL_PLACEHOLDER_{len(protected_urls) - 1}__"

    protected_line = RE_URL.sub(url_protection_callback, text_line)

    # Convert mixed ASCII fractions (for example: 1 1/2 becomes 1.5)
    protected_line = RE_MIXED_ASCII.sub(convert_mixed_ascii_match, protected_line)

    # Convert simple ASCII fractions (for example: 1/2 becomes 0.5)
    protected_line = RE_SIMPLE_ASCII.sub(convert_simple_ascii_match, protected_line)

    # Convert Unicode vulgar fractions (for example: 1½ becomes 1.5, ½ becomes 0.5)
    protected_line = RE_VULGAR.sub(convert_vulgar_match, protected_line)

    # Restore the original URLs
    def url_restoration_callback(match) -> str:
        url_index = int(match.group(1))
        return protected_urls[url_index]

    restored_line = re.sub(r"__URL_PLACEHOLDER_(\d+)__", url_restoration_callback, protected_line)
    return restored_line


def is_candidate_ingredient_line(line: str) -> bool:
    """
    Determines if a line is an ingredient line starting with an unordered bullet point
    followed immediately by a digit or a Unicode vulgar fraction.
    """
    stripped_line = line.lstrip()

    # Must be an unordered list item
    if not stripped_line.startswith(("*", "-", "+")):
        return False

    # Isolate the text content after the list bullet
    content_after_bullet = stripped_line[1:].lstrip()
    if not content_after_bullet:
        return False

    # Check if the content begins with a digit or a Unicode vulgar fraction character
    first_character = content_after_bullet[0]
    is_digit = first_character.isdigit()
    is_vulgar_fraction = "\u00BC" <= first_character <= "\u00BE" or "\u2150" <= first_character <= "\u215E"

    return is_digit or is_vulgar_fraction


def process_markdown_content(markdown_body: str) -> tuple[str, int]:
    """
    Processes the Markdown text line-by-line, targeting only list items
    that represent parsed ingredients.
    """
    lines = markdown_body.splitlines()
    processed_lines = []
    modification_count = 0

    for line in lines:
        if is_candidate_ingredient_line(line):
            normalized_line = normalize_fractions_in_string(line)
            if normalized_line != line:
                modification_count += 1
                processed_lines.append(normalized_line)
            else:
                processed_lines.append(line)
        else:
            processed_lines.append(line)

    return "\n".join(processed_lines), modification_count


# --- Main Runner ---

def run_cleanup():
    print("🧹 Running Fraction-to-Decimal Normalizer...")
    files_processed = 0
    modifications_made = 0

    for directory in RECIPE_DIRECTORIES:
        if not directory.exists():
            continue

        print(f"\nProcessing directory: {directory}/")
        for markdown_file in directory.glob("**/*.[mM][dD]"):
            if markdown_file.name == "index.md":
                continue

            try:
                with markdown_file.open("r", encoding="utf-8") as read_file:
                    raw_content = read_file.read()
            except Exception as read_error:
                print(f"  ⚠️ Read error in file {markdown_file}: {read_error}")
                continue

            # Process the body content to find candidate list lines
            # If the file has frontmatter, parse with the frontmatter module, otherwise parse as plain text
            has_frontmatter = raw_content.startswith("---")

            if has_frontmatter:
                try:
                    recipe_post = frontmatter.loads(raw_content)
                except Exception as parse_error:
                    print(f"  ⚠️ Parse error in frontmatter of {markdown_file}: {parse_error}")
                    continue

                cleaned_content, changes_in_file = process_markdown_content(recipe_post.content)

                if changes_in_file > 0:
                    recipe_post.content = cleaned_content
                    # Write the updated content back to the source file
                    with markdown_file.open("wb") as write_file:
                        frontmatter.dump(recipe_post, write_file, encoding="utf-8")
            else:
                cleaned_content, changes_in_file = process_markdown_content(raw_content)

                if changes_in_file > 0:
                    with markdown_file.open("w", encoding="utf-8") as write_file:
                        write_file.write(cleaned_content)

            if changes_in_file > 0:
                relative_path = markdown_file.relative_to(directory.parent)
                print(f"  ✅ Updated: {relative_path} ({changes_in_file} change(s))")
                modifications_made += changes_in_file

            files_processed += 1

    print("\n📊 --- Normalization Audit Complete ---")
    print(f"Total recipe files evaluated : {files_processed}")
    print(f"Total quantities normalized   : {modifications_made}")


if __name__ == "__main__":
    run_cleanup()