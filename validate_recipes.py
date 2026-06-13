import json
import re
from pathlib import Path

import frontmatter

HAS_FRONTMATTER = True


def parse_frontmatter(content: str):
    metadata = {}
    remaining_content = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            remaining_content = parts[2].strip()
            # Simple line-by-line parser for metadata
            for line in parts[1].splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if ':' in line_stripped:
                    key, val = line_stripped.split(':', 1)
                    key = key.strip().lower()
                    val = val.strip().strip('"\'')
                    metadata[key] = val
    return metadata, remaining_content


def load_file(file_path):
    if HAS_FRONTMATTER:
        post = frontmatter.load(file_path)
        return post.metadata, post.content
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return parse_frontmatter(content)


# Core patterns
RE_YIELD_PATTERN = re.compile(r'\b(yields?|serves?|makes|pax|portions?|people)\b', re.IGNORECASE)
RE_ING_HEADER = re.compile(r'^ingredients(?:\s+for\s+(.+))?$', re.IGNORECASE)
RE_DIR_HEADER = re.compile(r'^(?:directions|instructions|method)(?:\s+for\s+(.+))?$', re.IGNORECASE)
RE_QTY_UNIT = re.compile(
    r'^((?:(?:\d+(?:\s*/\s*|\s*-\s*|\s+)?\d*(?:\.\d+)?)|one|two|three|four|five|six|seven|eight|nine|ten|~)?\s*'
    r'(?:tablespoon|teaspoon|tbsp|tsp|cup|gram|g|ml|pound|lb|oz|ounce|can|clove|slice|slab|head|bunch|piece|pkg|decilitre|dl|kg|kilogram|can\s+full|can\s+of)s?)\s+(?:of\s+)?(.+)$',
    re.IGNORECASE
)


def parse_ingredient_line(line: str) -> dict:
    line = line.strip()
    line = re.sub(r'^[\*\-+]\s+', '', line)  # Clean up bullets if present

    # Try with full quantity + unit first
    match = RE_QTY_UNIT.match(line)
    if match:
        qty_unit = match.group(1).strip()
        name = match.group(2).strip()

        qty_match = re.match(
            r'^(\d+(?:\s*/\s*|\s*-\s*)?\d*(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|~)?\s*(.*)$',
            qty_unit, re.IGNORECASE)
        if qty_match:
            qty = qty_match.group(1) or ""
            unit = qty_match.group(2) or ""
            return {
                "raw":      line,
                "quantity": qty.strip(),
                "unit":     unit.strip(),
                "name":     name
            }

    # Try with just a leading number (e.g., 2 eggs, 1/2 onion)
    num_match = re.match(
        r'^(\d+(?:\s*/\s*|\s*-\s*)?\d*(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|~)\s+(.+)$', line,
        re.IGNORECASE)
    if num_match:
        return {
            "raw":      line,
            "quantity": num_match.group(1).strip(),
            "unit":     "",
            "name":     num_match.group(2).strip()
        }

    return {
        "raw":      line,
        "quantity": "",
        "unit":     "",
        "name":     line
    }


def split_recipes(content: str):
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    lines = content.splitlines()
    recipe_blocks = []
    current_block_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for thematic break
        if re.match(r'^(?:---|\*\*\*)\s*$', stripped):
            is_split_point = False
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    j += 1
                    continue
                if next_stripped.startswith('# '):
                    is_split_point = True
                break

            if is_split_point:
                recipe_blocks.append('\n'.join(current_block_lines))
                current_block_lines = []
                i = j  # Skip thematic break and blank lines
                continue

        current_block_lines.append(line)
        i += 1

    if current_block_lines:
        recipe_blocks.append('\n'.join(current_block_lines))

    return [r.strip() for r in recipe_blocks if r.strip()]


def parse_block_to_logical_nodes(text: str):
    lines = text.splitlines()
    blocks = []

    current_type = None  # 'list_item_ul', 'list_item_ol', 'paragraph', 'blockquote'
    current_lines = []
    current_indent = 0
    current_meta = {}

    def flush():
        nonlocal current_type, current_lines, current_indent, current_meta
        if not current_type:
            return
        combined_text = " ".join(current_lines)
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        blocks.append({
            "type": current_type,
            "text": combined_text,
            "meta": current_meta
        })
        current_type = None
        current_lines = []
        current_indent = 0
        current_meta = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue

        # Check for Headings
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if heading_match:
            flush()
            blocks.append({
                "type": "heading",
                "text": heading_match.group(2).strip(),
                "meta": {"level": len(heading_match.group(1))}
            })
            continue

        # Check for Blockquote
        if line.lstrip().startswith('>'):
            content = line.lstrip().lstrip('>').strip()
            if current_type == 'blockquote':
                current_lines.append(content)
            else:
                flush()
                current_type = 'blockquote'
                current_lines = [content]
            continue

        # Check for Unordered List Item
        ul_match = re.match(r'^(\s*)[\*\-+]\s+(.+)$', line)
        if ul_match:
            flush()
            indent = len(ul_match.group(1))
            content = ul_match.group(2).strip()
            current_type = 'list_item_ul'
            current_lines = [content]
            current_indent = indent
            continue

        # Check for Ordered List Item
        ol_match = re.match(r'^(\s*)(\d+)\.\s+(.+)$', line)
        if ol_match:
            flush()
            indent = len(ol_match.group(1))
            start_num = int(ol_match.group(2))
            content = ol_match.group(3).strip()
            current_type = 'list_item_ol'
            current_lines = [content]
            current_indent = indent
            current_meta = {"start": start_num}
            continue

        # Check for List continuation
        if current_type in ('list_item_ul', 'list_item_ol'):
            leading_spaces = len(line) - len(line.lstrip())
            if leading_spaces >= current_indent + 1:
                current_lines.append(stripped)
                continue
            else:
                flush()

        # Fallback to Paragraph
        if current_type == 'paragraph':
            current_lines.append(stripped)
        else:
            flush()
            current_type = 'paragraph'
            current_lines = [stripped]

    flush()
    return blocks


def assemble_recipe(blocks, block_idx, metadata):
    title = None
    yield_val = None
    warnings = []

    ingredients_map = {}  # component -> list of items
    directions_map = {}  # component -> list of steps
    notes = []

    # Pre-scan for ingredients or directions headers
    has_ingredients_header = False
    has_directions_header = False
    for b in blocks:
        if b['type'] == 'heading' and b['meta'].get('level') == 2:
            text = b['text']
            if RE_ING_HEADER.match(text):
                has_ingredients_header = True
            elif RE_DIR_HEADER.match(text):
                has_directions_header = True

    has_headers = has_ingredients_header or has_directions_header

    # Extract Title
    for b in blocks:
        if b['type'] == 'heading' and b['meta'].get('level') == 1:
            title = b['text']
            break

    if not title:
        if block_idx == 0 and 'title' in metadata:
            title = metadata['title']
            warnings.append("Missing H1 Title ('# Title') at start of block (using frontmatter title).")
        else:
            title = f"Recipe {block_idx + 1}"
            warnings.append("Missing H1 Title ('# Title') at the start of this block.")

    # Extract Yield from frontmatter
    for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
        if key in metadata and metadata[key]:
            yield_val = str(metadata[key]).strip()
            break

    # Fallback to search block text for yield (strictly before H2 sections)
    if not yield_val:
        for b in blocks:
            if b['type'] == 'heading' and b['meta'].get('level') == 2:
                break
            if b['type'] in ('paragraph', 'list_item_ul', 'list_item_ol'):
                text = b['text']
                for line in text.splitlines():
                    if RE_YIELD_PATTERN.search(line):
                        if re.match(r'^(?:\d+\.\s*)?serve\b', line, re.IGNORECASE) and not re.search(
                                r'\b(yields?|serves?|makes)\s+\d+', line, re.IGNORECASE):
                            continue
                        yield_val = line.strip()
                        break
                if yield_val:
                    break

    if not yield_val:
        warnings.append(
            "No serving or yield metadata detected near the block header (e.g., 'yields ...' or 'serves ...').")

    # Standard warnings for missing headers
    if not has_ingredients_header:
        warnings.append("Missing '## Ingredients' header.")
    if not has_directions_header:
        warnings.append("Missing '## Directions' or '## Instructions' header.")

    # State-based section classification
    current_section = None
    current_component = "Main"

    for b in blocks:
        if b['type'] == 'heading':
            level = b['meta'].get('level')
            text = b['text']
            if level == 1:
                continue
            elif level == 2:
                ing_m = RE_ING_HEADER.match(text)
                dir_m = RE_DIR_HEADER.match(text)
                if ing_m:
                    current_section = "ingredients"
                    current_component = ing_m.group(1) or "Main"
                elif dir_m:
                    current_section = "directions"
                    current_component = dir_m.group(1) or "Main"
                elif any(x in text.lower() for x in
                         ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                    current_section = "notes"
                    current_component = "Main"
                else:
                    current_section = None
                    current_component = "Main"
            else:
                # Heading 3 or deeper
                if current_section == "notes":
                    notes.append(text)
            continue

        if b['type'] == 'blockquote':
            notes.append(b['text'])
            continue

        if b['type'] in ('list_item_ul', 'list_item_ol'):
            is_ordered = (b['type'] == 'list_item_ol')
            text = b['text']

            if current_section is None or not has_headers:
                if is_ordered:
                    current_section_node = "directions"
                else:
                    if not has_headers:
                        current_section_node = "ingredients"
                    else:
                        current_section_node = None
            else:
                current_section_node = current_section

            if current_section_node == "ingredients":
                ingredients_map.setdefault(current_component, []).append(parse_ingredient_line(text))
            elif current_section_node == "directions":
                directions_map.setdefault(current_component, []).append(text)
            elif current_section_node == "notes":
                notes.append(text)

        elif b['type'] == 'paragraph':
            text = b['text']
            if current_section == "notes":
                notes.append(text)
            elif current_section == "directions" and has_headers:
                directions_map.setdefault(current_component, []).append(text)

    # Format maps into lists
    formatted_ingredients = []
    for comp, items in ingredients_map.items():
        if items:
            formatted_ingredients.append({"component": comp, "items": items})

    formatted_directions = []
    for comp, steps in directions_map.items():
        if steps:
            formatted_directions.append({"component": comp, "steps": steps})

    return {
        "title":       title,
        "yield":       yield_val,
        "ingredients": formatted_ingredients,
        "directions":  formatted_directions,
        "notes":       notes,
        "warnings":    warnings
    }


RECIPE_DIRS = [
    Path('recipes'),
    Path('in-progress'),
    Path('curated-untested'),
]
OUTPUT_DIR = Path('temp_parsed')


def process_file_tree():
    print("🚀 Running AST-Based Recipe Parser & Validator (Universal Checking Enabled)...")

    total_files = 0
    flagged_files = 0
    total_recipe_blocks = 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for recipe_dir in RECIPE_DIRS:
        if not recipe_dir.exists():
            continue

        print(f"\n📂 Directory: {recipe_dir}/")

        for md_file in recipe_dir.glob('**/*.[mM][dD]'):
            if md_file.name == 'index.md':
                continue

            total_files += 1
            rel_path = md_file.relative_to(recipe_dir.parent) if recipe_dir.parent else md_file

            try:
                metadata, raw_content = load_file(md_file)
            except Exception as e:
                print(f"  📄 File: {rel_path} - Read Error: {e}")
                continue

            # Split recipes
            blocks_text = split_recipes(raw_content)
            recipes_data = []

            for idx, text in enumerate(blocks_text):
                nodes = parse_block_to_logical_nodes(text)
                recipe_parsed = assemble_recipe(nodes, idx, metadata)
                recipes_data.append(recipe_parsed)

            total_recipe_blocks += len(recipes_data)
            has_warnings = any(r['warnings'] for r in recipes_data)

            if has_warnings:
                flagged_files += 1
                print(f"  📄 File: {rel_path} ({len(recipes_data)} block(s) detected)")
                for idx, r in enumerate(recipes_data):
                    prefix = f"    🥞 [{r['title']}] (Block #{idx + 1})" if len(
                        recipes_data) > 1 else f"    🥞 [{r['title']}]"
                    print(prefix)
                    for warning in r['warnings']:
                        print(f"       └─ ⚠️  {warning}")

            # Write structured outputs to JSON
            out_file_path = OUTPUT_DIR / recipe_dir.name / md_file.relative_to(recipe_dir).with_suffix('.json')
            out_file_path.parent.mkdir(parents=True, exist_ok=True)

            export_data = {
                "source_file": str(rel_path),
                "metadata":    metadata,
                "recipes":     [
                    {
                        "title":       r["title"],
                        "yield":       r["yield"],
                        "ingredients": r["ingredients"],
                        "directions":  r["directions"],
                        "notes":       r["notes"]
                    }
                    for r in recipes_data
                ]
            }

            with open(out_file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

    print("\n📊 --- Audit & Parse Summary ---")
    print(f"Directories scanned    : {len([d for d in RECIPE_DIRS if d.exists()])}")
    print(f"Files analyzed         : {total_files}")
    print(f"Total recipe blocks    : {total_recipe_blocks}")
    print(f"Files flagged/warning  : {flagged_files} ({(flagged_files / max(1, total_files) * 100):.1f}%)")
    print(f"Files fully conforming : {total_files - flagged_files}")
    print(f"📁 Structured outputs successfully exported to standard path: '{OUTPUT_DIR}/'")


if __name__ == '__main__':
    process_file_tree()
