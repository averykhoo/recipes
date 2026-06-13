import re
from pathlib import Path
import frontmatter

# --- Configuration ---
RECIPE_DIRS = [
    Path('recipes'),
    Path('in-progress'),
    Path('curated-untested'),
]

# Section header and metadata regexes
RE_BLOCK_DELIMITER = re.compile(r'(?m)^---\s*$')
RE_YIELD_PATTERN = re.compile(r'\b(yields?|serves?|makes|pax|portions?|people)\b', re.IGNORECASE)
RE_BARE_URL = re.compile(r'(?<![<"\'`=])(?<!]\()(https?://[^\s<>"\'`]+[^\s<>"\'`.,;:!?)]+)', re.IGNORECASE)

# Ingredients regex definitions
RE_ING_UNQUALIFIED = re.compile(r'^##\s+ingredients\s*$', re.IGNORECASE)
RE_ING_QUALIFIED = re.compile(r'^##\s+ingredients\s+for\s+(.+)$', re.IGNORECASE)
RE_ING_GENERIC = re.compile(r'^##\s+ingredients\b', re.IGNORECASE)

# Directions/Instructions regex definitions
RE_DIR_UNQUALIFIED = re.compile(r'^##\s+(directions|instructions)\s*$', re.IGNORECASE)
RE_DIR_QUALIFIED = re.compile(r'^##\s+(directions|instructions)\s+for\s+(.+)$', re.IGNORECASE)
RE_DIR_GENERIC = re.compile(r'^##\s+(directions|instructions)\b', re.IGNORECASE)


def audit_recipe_block(block_text: str, block_index: int, total_blocks: int, file_metadata: dict, is_camera_ready: bool):
    """
    Audits a single recipe block/segment.
    """
    warnings = []
    lines = [line.strip() for line in block_text.splitlines()]
    non_empty_lines = [line for line in lines if line]

    if not non_empty_lines:
        return None, ["Empty recipe block detected."]

    # 1. Assert first non-empty line must be H1 (# Title)
    first_line = non_empty_lines[0]
    recipe_title = f"Recipe {block_index + 1}"

    if first_line.startswith('##'):
        warnings.append("Starts with an H2 (##) instead of an H1 (#) title (Wrong header level).")
        recipe_title = first_line.lstrip('#').strip()
    elif not first_line.startswith('# '):
        if block_index == 0 and 'title' in file_metadata:
            recipe_title = file_metadata['title']
            warnings.append("Missing H1 Title ('# Title') at start of block (using frontmatter title).")
        else:
            warnings.append("Missing H1 Title ('# Title') at the start of this block.")
    else:
        recipe_title = first_line.lstrip('#').strip()

    is_placeholder = len(non_empty_lines) < 5 or any("todo" in line.lower() for line in non_empty_lines[:3])
    if is_placeholder:
        return recipe_title, ["Placeholder / TODO block (skipped detailed section checks)."]

    # 2. Check for H1 duplication within a single block
    h1_count = sum(1 for line in lines if line.startswith('# ') and not line.startswith('##'))
    if h1_count > 1:
        warnings.append(
            f"Contains multiple H1 headings ({h1_count}) inside a single block. Ensure they are separated by '---' on a blank line.")

    # 3. Categorize Ingredients & Directions Headers
    ing_unqualified = []
    ing_qualified = []
    ing_generic = []

    dir_unqualified = []
    dir_qualified = []
    dir_generic = []

    for line in lines:
        # Match ingredients headers
        if RE_ING_UNQUALIFIED.match(line):
            ing_unqualified.append(line)
        elif RE_ING_QUALIFIED.match(line):
            ing_qualified.append(line)
        elif RE_ING_GENERIC.match(line):
            ing_generic.append(line)

        # Match directions headers
        if RE_DIR_UNQUALIFIED.match(line):
            dir_unqualified.append(line)
        elif RE_DIR_QUALIFIED.match(line):
            dir_qualified.append(line)
        elif RE_DIR_GENERIC.match(line):
            dir_generic.append(line)

    total_ing_count = len(ing_unqualified) + len(ing_qualified) + len(ing_generic)
    total_dir_count = len(dir_unqualified) + len(dir_qualified) + len(dir_generic)

    # 4. Enforce Ingredients Header Rules
    if total_ing_count == 0:
        warnings.append("Missing '## Ingredients' header.")
    elif total_ing_count == 1:
        # A single section can be unqualified OR qualified, but must not be malformed (e.g. using hyphens)
        if len(ing_generic) == 1:
            warnings.append(
                f"Malformed ingredients header: '{ing_generic[0]}'. Please use '## Ingredients' or '## Ingredients for [component]'.")
    else:
        # Multiple ingredients sections: ALL must be qualified with "for"
        if len(ing_unqualified) > 0 or len(ing_generic) > 0:
            warnings.append(
                f"Multiple ingredients sections detected ({total_ing_count}), but they are not fully standardized. When multiple sections exist, ALL of them must specify 'for [component]' (e.g., '## Ingredients for the dough').")

    # 5. Enforce Directions Header Rules
    if total_dir_count == 0:
        warnings.append("Missing '## Directions' or '## Instructions' header.")
    elif total_dir_count == 1:
        if len(dir_generic) == 1:
            warnings.append(
                f"Malformed directions header: '{dir_generic[0]}'. Please use '## Directions' or '## Directions for [component]'.")
    else:
        # Multiple directions sections: ALL must be qualified with "for"
        if len(dir_unqualified) > 0 or len(dir_generic) > 0:
            warnings.append(
                f"Multiple directions/instructions sections detected ({total_dir_count}), but they are not fully standardized. When multiple sections exist, ALL of them must specify 'for [component]' (e.g., '## Directions for the sauce').")

    # 6. Check list formats for ingredients and directions
    if total_ing_count > 0:
        in_ingredients = False
        bullet_count = 0
        for line in lines:
            if RE_ING_GENERIC.match(line):
                in_ingredients = True
                continue
            if in_ingredients and line.startswith('##'):
                in_ingredients = False  # Reset on next heading
            if in_ingredients and (line.startswith('* ') or line.startswith('- ')):
                bullet_count += 1
        if bullet_count == 0:
            warnings.append("Ingredients found, but none are bullet points ('* ' or '- ').")

    if total_dir_count > 0:
        in_directions = False
        step_count = 0
        is_numbered = False
        for line in lines:
            if RE_DIR_GENERIC.match(line):
                in_directions = True
                continue
            if in_directions and line.startswith('##'):
                in_directions = False  # Reset on next heading
            if in_directions:
                if re.match(r'^\d+\.\s+', line):
                    step_count += 1
                    is_numbered = True
                elif line.startswith('* ') or line.startswith('- '):
                    step_count += 1
        if step_count == 0:
            warnings.append("Directions found, but no step-by-step items detected.")
        elif not is_numbered:
            warnings.append("Directions are listed as bullet points. Numbered steps are recommended for parsing.")

    # 7. Check serving size / yield metadata presence
    has_yield = any(RE_YIELD_PATTERN.search(line) for line in lines[:15])
    if not has_yield and block_index == 0:
        has_yield = 'yield' in file_metadata or 'yields' in file_metadata

    if not has_yield:
        warnings.append(
            "No serving or yield metadata detected near the block header (e.g., 'yields ...' or 'serves ...').")

    # 8. Check for formatting errors (e.g., bare URLs)
    bare_urls = [RE_BARE_URL.search(line).group(0) for line in lines if RE_BARE_URL.search(line)]
    if bare_urls:
        warnings.append(
            f"Contains bare URL(s) not wrapped in angle brackets or Markdown links (e.g., '{bare_urls[0]}').")

    return recipe_title, warnings


def audit_file(file_path: Path):
    """
    Loads a file, splits it into blocks, merges non-H1 blocks to prevent false-positives,
    and audits each block independently.
    """
    try:
        post = frontmatter.load(file_path)
        content = post.content.strip()
        metadata = post.metadata
    except Exception as e:
        return None, [{"recipe_title": "File Level", "warnings": [f"YAML/Frontmatter Parse Error: {e}"]}]

    # Split the raw body by horizontal rule '---' lines
    raw_blocks = RE_BLOCK_DELIMITER.split(content)
    raw_blocks = [b.strip() for b in raw_blocks if b.strip()]

    # Re-merge blocks that don't start with H1 to handle inline divider lines
    blocks = []
    for b in raw_blocks:
        lines = [line.strip() for line in b.splitlines() if line.strip()]
        starts_with_h1 = False
        if lines:
            first_line = lines[0]
            if re.match(r'^#\s', first_line):
                starts_with_h1 = True

        if starts_with_h1 or not blocks:
            blocks.append(b)
        else:
            # Join non-H1 split sections back to the previous recipe block
            blocks[-1] = blocks[-1] + "\n\n---\n\n" + b

    # Determine if this file is in the camera-ready recipes directory
    is_camera_ready = "recipes" in file_path.parts and "in-progress" not in file_path.parts and "curated-untested" not in file_path.parts

    file_results = []

    for idx, block in enumerate(blocks):
        res = audit_recipe_block(block, idx, len(blocks), metadata, is_camera_ready)
        if res:
            title, warnings = res
            if warnings:
                file_results.append({
                    "recipe_title": title,
                    "block_index":  idx + 1,
                    "warnings":     warnings
                })

    return len(blocks), file_results


if __name__ == '__main__':
    print("🚀 Running Recipe Parser Audit (v3: Scoped Multi-Component Header Analysis)...")

    total_files = 0
    total_recipes = 0
    flagged_files = 0

    for recipe_dir in RECIPE_DIRS:
        if not recipe_dir.exists():
            continue

        print(f"\n📂 Directory: {recipe_dir}/")

        for md_file in recipe_dir.glob('**/*.[mM][dD]'):
            if md_file.name == 'index.md':
                continue

            total_files += 1
            recipe_count, results = audit_file(md_file)
            total_recipes += (recipe_count or 0)

            if results:
                flagged_files += 1
                rel_path = md_file.relative_to(recipe_dir.parent) if recipe_dir.parent else md_file
                print(f"  📄 File: {rel_path} ({recipe_count} recipe block(s) detected)")

                for idx, res in enumerate(results):
                    prefix = f"    🥞 [{res['recipe_title']}] (Block #{res['block_index']})" if recipe_count > 1 else f"    🥞 [{res['recipe_title']}]"
                    print(prefix)
                    for warning in res['warnings']:
                        print(f"       └─ ⚠️  {warning}")

    print("\n--- Audit Summary ---")
    print(f"Directories scanned    : {len([d for d in RECIPE_DIRS if d.exists()])}")
    print(f"Files analyzed         : {total_files}")
    print(f"Total recipe blocks    : {total_recipes}")
    print(f"Files needing standard : {flagged_files} ({(flagged_files / max(1, total_files) * 100):.1f}%)")
    print(f"Files fully conforming : {total_files - flagged_files}")