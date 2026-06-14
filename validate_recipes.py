import json
import re
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import frontmatter
from markdown_it import MarkdownIt
from pydantic import BaseModel
from pydantic import Field

HAS_FRONTMATTER = True


# --- Pydantic Data Models ---

class Ingredient(BaseModel):
    raw: str
    quantity: str
    unit: str
    name: str


class IngredientsComponent(BaseModel):
    component: str = "Main"
    items: List[Ingredient] = Field(default_factory=list)


class DirectionsComponent(BaseModel):
    component: str = "Main"
    steps: List[str] = Field(default_factory=list)


class Recipe(BaseModel):
    title: str
    yield_val: Optional[str] = Field(default=None, alias="yield")
    ingredients: List[IngredientsComponent] = Field(default_factory=list)
    directions: List[DirectionsComponent] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    # Compatibility mapping for Pydantic V2
    model_config = {
        "populate_by_name": True,
        "by_alias":         True
    }


class RecipeDocument(BaseModel):
    source_file: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    recipes: List[Recipe] = Field(default_factory=list)


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    """Ensures compatibility with both Pydantic V1 and Pydantic V2."""
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    return model.dict(by_alias=True)


# --- Directories & Regexes ---

RECIPE_DIRS = [
    Path('recipes'),
    Path('in-progress'),
    Path('curated-untested'),
]
OUTPUT_DIR = Path('temp_parsed')

RE_YIELD_PATTERN = re.compile(r'\b(yields?|serves?|makes|pax|portions?|people)\b', re.IGNORECASE)
RE_ING_HEADER = re.compile(r'^ingredients(?:\s+for\s+(.+))?$', re.IGNORECASE)
RE_DIR_HEADER = re.compile(r'^(?:directions|instructions|method)(?:\s+for\s+(.+))?$', re.IGNORECASE)
RE_QTY_UNIT = re.compile(
    r'^((?:(?:\d+(?:\s*/\s*|\s*-\s*|\s+)?\d*(?:\.\d+)?)|one|two|three|four|five|six|seven|eight|nine|ten|~)?\s*'
    r'(?:tablespoon|teaspoon|tbsp|tsp|cup|gram|g|ml|pound|lb|oz|ounce|can|clove|slice|slab|head|bunch|piece|pkg|decilitre|dl|kg|kilogram|can\s+full|can\s+of)s?)\s+(?:of\s+)?(.+)$',
    re.IGNORECASE
)


# --- Utility Functions ---

def parse_frontmatter(content: str):
    """Clean fallback YAML header parser."""
    metadata = {}
    remaining_content = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            remaining_content = parts[2].strip()
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
    # if HAS_FRONTMATTER:
    post = frontmatter.load(file_path)
    return post.metadata, post.content


# else:
#    with open(file_path, 'r', encoding='utf-8') as f:
#        content = f.read()
#    return parse_frontmatter(content)


def parse_ingredient_line(line: str) -> dict:
    line = line.strip()
    line = re.sub(r'^[\*\-+]\s+', '', line)

    # Pattern 1: Match standard units
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

    # Pattern 2: Match simple count items (e.g. 2 eggs, 1/2 onion)
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


def parse_markdown_to_blocks(content_text: str) -> List[dict]:
    """Converts the markdown-it-py token stream into simplified logical layout blocks."""
    md = MarkdownIt()
    tokens = md.parse(content_text)
    blocks = []

    i = 0
    while i < len(tokens):
        t = tokens[i]

        if t.type == 'hr':
            blocks.append({"type": "ThematicBreak"})
            i += 1

        elif t.type == 'heading_open':
            level = int(t.tag[1:])
            i += 1
            text_parts = []
            while i < len(tokens) and tokens[i].type != 'heading_close':
                if tokens[i].type == 'inline':
                    text_parts.append(tokens[i].content)
                i += 1
            blocks.append({"type": "Heading", "level": level, "text": "".join(text_parts)})
            i += 1

        elif t.type == 'paragraph_open':
            i += 1
            text_parts = []
            while i < len(tokens) and tokens[i].type != 'paragraph_close':
                if tokens[i].type == 'inline':
                    text_parts.append(tokens[i].content)
                i += 1
            blocks.append({"type": "Paragraph", "text": "".join(text_parts)})
            i += 1

        elif t.type in ('bullet_list_open', 'ordered_list_open'):
            is_ordered = (t.type == 'ordered_list_open')
            items = []
            i += 1
            while i < len(tokens) and tokens[i].type not in ('bullet_list_close', 'ordered_list_close'):
                if tokens[i].type == 'list_item_open':
                    item_text_parts = []
                    i += 1
                    while i < len(tokens) and tokens[i].type != 'list_item_close':
                        if tokens[i].type == 'inline':
                            item_text_parts.append(tokens[i].content)
                        i += 1
                    items.append("\n".join(item_text_parts))
                i += 1
            blocks.append({"type": "List", "ordered": is_ordered, "items": items})
            i += 1

        elif t.type == 'blockquote_open':
            quote_parts = []
            i += 1
            while i < len(tokens) and tokens[i].type != 'blockquote_close':
                if tokens[i].type == 'inline':
                    quote_parts.append(tokens[i].content)
                i += 1
            blocks.append({"type": "Quote", "text": "\n".join(quote_parts)})
            i += 1

        else:
            i += 1

    return blocks


def split_recipe_blocks(blocks: List[dict]) -> List[List[dict]]:
    """Splits blocks into sub-recipes on ThematicBreaks directly followed by H1."""
    recipes = []
    current_block = []

    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b['type'] == 'ThematicBreak':
            next_is_h1 = False
            for j in range(i + 1, len(blocks)):
                next_b = blocks[j]
                if next_b['type'] == 'Heading':
                    if next_b['level'] == 1:
                        next_is_h1 = True
                    break
                if next_b['type'] != 'ThematicBreak':
                    break

            if next_is_h1:
                if current_block:
                    recipes.append(current_block)
                    current_block = []
                i += 1
                continue

        current_block.append(b)
        i += 1

    if current_block:
        recipes.append(current_block)

    return recipes


def assemble_recipe(blocks: List[dict], block_idx: int, metadata: dict) -> tuple:
    """Assembles segmented logical blocks into a Recipe dictionary with diagnostic reports."""
    title = None
    yield_val = None
    warnings = []

    ingredients_map = {}
    directions_map = {}
    notes = []

    # Pre-scan for ingredients or directions headers to determine fallback behavior
    has_ingredients_header = False
    has_directions_header = False
    for b in blocks:
        if b['type'] == 'Heading' and b['level'] == 2:
            if RE_ING_HEADER.match(b['text']):
                has_ingredients_header = True
            elif RE_DIR_HEADER.match(b['text']):
                has_directions_header = True

    has_headers = has_ingredients_header or has_directions_header

    # 1. Extract Title
    for b in blocks:
        if b['type'] == 'Heading' and b['level'] == 1:
            title = b['text'].strip()
            break

    if not title:
        if block_idx == 0 and 'title' in metadata:
            title = metadata['title']
            warnings.append("Missing H1 Title ('# Title') at start of block (using frontmatter title).")
        else:
            title = f"Recipe {block_idx + 1}"
            warnings.append("Missing H1 Title ('# Title') at the start of this block.")

    # 2. Extract Yield
    # Try frontmatter first
    for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
        if key in metadata and metadata[key]:
            yield_val = str(metadata[key]).strip()
            break

    # Fallback to scan introductory paragraphs strictly before Level 2 sections
    if not yield_val:
        for b in blocks:
            if b['type'] == 'Heading' and b['level'] == 2:
                break
            if b['type'] in ('Paragraph', 'List'):
                text = b.get('text', "") if b['type'] == 'Paragraph' else "\n".join(b.get('items', []))
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

    if not has_ingredients_header:
        warnings.append("Missing '## Ingredients' header.")
    if not has_directions_header:
        warnings.append("Missing '## Directions' or '## Instructions' header.")

    # 3. Categorize content components
    current_section = None
    current_component = "Main"

    for b in blocks:
        if b['type'] == 'Heading':
            if b['level'] == 1:
                continue
            elif b['level'] == 2:
                h_text = b['text'].strip()
                ing_m = RE_ING_HEADER.match(h_text)
                dir_m = RE_DIR_HEADER.match(h_text)

                if ing_m:
                    current_section = "ingredients"
                    current_component = ing_m.group(1) or "Main"
                elif dir_m:
                    current_section = "directions"
                    current_component = dir_m.group(1) or "Main"
                elif any(x in h_text.lower() for x in
                         ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                    current_section = "notes"
                    current_component = "Main"
                else:
                    current_section = None
                    current_component = "Main"
            else:
                # Heading 3+ under notes counts as a note
                if current_section == "notes":
                    notes.append(b['text'].strip())
            continue

        if b['type'] == 'Quote':
            notes.append(b['text'].strip())
            continue

        if b['type'] == 'List':
            is_ordered = b['ordered']

            if current_section is None or not has_headers:
                if is_ordered:
                    current_section_node = "directions"
                else:
                    # Ignore intro unordered lists (often sources/links) if headers exist below
                    if not has_headers:
                        current_section_node = "ingredients"
                    else:
                        current_section_node = None
            else:
                current_section_node = current_section

            for item_text in b['items']:
                item_text = item_text.strip()
                if current_section_node == "ingredients":
                    ingredients_map.setdefault(current_component, []).append(parse_ingredient_line(item_text))
                elif current_section_node == "directions":
                    directions_map.setdefault(current_component, []).append(item_text)
                elif current_section_node == "notes":
                    notes.append(item_text)

        elif b['type'] == 'Paragraph':
            p_text = b['text'].strip()
            if current_section == "notes":
                notes.append(p_text)
            elif current_section == "directions" and has_headers:
                # Some people write directions as standard paragraphs under ## Directions
                directions_map.setdefault(current_component, []).append(p_text)

    # 4. Bind to Pydantic Model
    valid_ingredients = []
    for comp, items in ingredients_map.items():
        if items:
            valid_ingredients.append(IngredientsComponent(component=comp, items=[Ingredient(**i) for i in items]))

    valid_directions = []
    for comp, steps in directions_map.items():
        if steps:
            valid_directions.append(DirectionsComponent(component=comp, steps=steps))

    recipe_model = Recipe(
        title=title,
        yield_val=yield_val,
        ingredients=valid_ingredients,
        directions=valid_directions,
        notes=notes
    )

    return recipe_model, warnings


# --- Document Processing Loop ---

def process_file_tree():
    print("🚀 Running AST-Based Recipe Parser & Validator (markdown-it-py Edition)...")

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

            # Flatten to our simplified dictionary block representation
            blocks = parse_markdown_to_blocks(raw_content)
            recipe_node_blocks = split_recipe_blocks(blocks)

            recipes_list = []
            file_has_warnings = False

            print_block_data = []

            for idx, block_nodes in enumerate(recipe_node_blocks):
                recipe_model, warnings = assemble_recipe(block_nodes, idx, metadata)
                recipes_list.append(recipe_model)

                if warnings:
                    file_has_warnings = True
                    prefix = f"    🥞 [{recipe_model.title}] (Block #{idx + 1})" if len(
                        recipe_node_blocks) > 1 else f"    🥞 [{recipe_model.title}]"
                    print_block_data.append((prefix, warnings))

            total_recipe_blocks += len(recipes_list)

            if file_has_warnings:
                flagged_files += 1
                print(f"  📄 File: {rel_path} ({len(recipe_node_blocks)} block(s) detected)")
                for prefix, warnings in print_block_data:
                    print(prefix)
                    for warning in warnings:
                        print(f"       └─ ⚠️  {warning}")

            # Format outputs through RecipeDocument model
            doc_model = RecipeDocument(
                source_file=str(rel_path),
                metadata=metadata,
                recipes=recipes_list
            )

            # Write structured outputs to JSON
            out_file_path = OUTPUT_DIR / recipe_dir.name / md_file.relative_to(recipe_dir).with_suffix('.json')
            out_file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(out_file_path, 'w', encoding='utf-8') as f:
                json.dump(model_to_dict(doc_model), f, indent=2, ensure_ascii=False)

    print("\n📊 --- Audit & Parse Summary ---")
    print(f"Directories scanned    : {len([d for d in RECIPE_DIRS if d.exists()])}")
    print(f"Files analyzed         : {total_files}")
    print(f"Total recipe blocks    : {total_recipe_blocks}")
    print(f"Files flagged/warning  : {flagged_files} ({(flagged_files / max(1, total_files) * 100):.1f}%)")
    print(f"Files fully conforming : {total_files - flagged_files}")
    print(f"📁 Structured outputs successfully exported to standard path: '{OUTPUT_DIR}/'")


if __name__ == '__main__':
    process_file_tree()
