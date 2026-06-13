"""
all this was pasted from the thinking bit while gemini was trying to write a recipe parser



User 2:53 PM
the parser should solve this by merging across splits when the --- split does not start with h1 (after optional empty newlines)
update the parser and make it more robust


this is before mistletoe, give me the full analyzer file after adding mistletoe

before you write code, describe the structure you expect to see and parse

always check every file regardless of whether it's amera ready or not, and
always attempt to parse yields and always warn

if theres anything else you think you can parse (ingredient lists, directions)
based on the todo or your own thoughts, just add it and we'll see how it goes

output a temp_parsed folder of whatever you can parse (structured format, either
json or yaml or whatever) and we'll see how it went and how far we have to go

for recipes with no headers, assume lists are ingredients, and numbered lists
are directions

lets try for a full parser this time

"""


# Define the regexes and parsing functions and run the test

import re
import json

class RawText:
    def __init__(self, content):
        self.content = content

class Heading:
    def __init__(self, level, children):
        self.level = level
        self.children = children

class Paragraph:
    def __init__(self, children):
        self.children = children

class ListItem:
    def __init__(self, children):
        self.children = children

class List:
    def __init__(self, children, start=None):
        self.children = children
        self.start = start

    @property
    def is_ordered(self):
        return self.start is not None

class ThematicBreak:
    pass

def render_inline(token) -> str:
    if hasattr(token, 'content'):
        return token.content
    if hasattr(token, 'children') and token.children:
        return "".join(render_inline(child) for child in token.children)
    return ""

def parse_markdown_to_ast(content_text: str):
    lines = content_text.splitlines()
    children = []
    current_list = None
    is_current_ordered = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_list:
                children.append(current_list)
                current_list = None
            continue

        if re.match(r'^(?:---|\*\*\*)\s*$', stripped):
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(ThematicBreak())
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(Heading(len(heading_match.group(1)), [RawText(heading_match.group(2))]))
            continue

        ul_match = re.match(r'^[\*\-+]\s+(.+)$', stripped)
        if ul_match:
            item_text = ul_match.group(1)
            if current_list is None or is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=None)
                is_current_ordered = False
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if ol_match:
            start_num = int(ol_match.group(1))
            item_text = ol_match.group(2)
            if current_list is None or not is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=start_num)
                is_current_ordered = True
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        if current_list:
            children.append(current_list)
            current_list = None

        if children and isinstance(children[-1], Paragraph):
            p_text = render_inline(children[-1]) + "\n" + stripped
            children[-1] = Paragraph([RawText(p_text)])
        else:
            children.append(Paragraph([RawText(stripped)]))

    if current_list:
        children.append(current_list)

    return children

RE_YIELD_PATTERN = re.compile(r'\b(yields?|serves?|makes|pax|portions?|people)\b', re.IGNORECASE)
RE_BARE_URL = re.compile(r'(?<![<"\'`=])(?<!]\()(https?://[^\s<>"\'`]+[^\s<>"\'`.,;:!?)]+)', re.IGNORECASE)

# Category regex matchers for ingredients and directions
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
    return {
        "raw":      line,
        "quantity": "",
        "unit":     "",
        "name":     line
    }

def parse_and_audit_blocks(content_text: str, metadata: dict) -> list:
    children = parse_markdown_to_ast(content_text)
    raw_blocks = []
    current_block = []

    for i, node in enumerate(children):
        if isinstance(node, ThematicBreak):
            next_heading = False
            for j in range(i + 1, len(children)):
                next_node = children[j]
                if isinstance(next_node, Heading):
                    if next_node.level == 1:
                        next_heading = True
                    break
                if not isinstance(next_node, ThematicBreak):
                    break
            if next_heading:
                if current_block:
                    raw_blocks.append(current_block)
                    current_block = []
                continue
        current_block.append(node)
    if current_block:
        raw_blocks.append(current_block)

    recipes = []

    for idx, block_nodes in enumerate(raw_blocks):
        warnings = []

        # 1. Title Extraction
        title = None
        for node in block_nodes:
            if isinstance(node, Heading) and node.level == 1:
                title = render_inline(node).strip()
                break
        if not title:
            if idx == 0 and 'title' in metadata:
                title = metadata['title']
                warnings.append("Missing H1 Title ('# Title') at start of block (using frontmatter title).")
            else:
                title = f"Recipe {idx + 1}"
                warnings.append("Missing H1 Title ('# Title') at the start of this block.")

        # 2. Yield Extraction
        yield_val = None
        for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
            if key in metadata and metadata[key]:
                yield_val = str(metadata[key]).strip()
                break

        if not yield_val:
            for node in block_nodes[:15]:
                if isinstance(node, (Paragraph, List)):
                    text = render_inline(node)
                    for line in text.splitlines():
                        if RE_YIELD_PATTERN.search(line):
                            yield_val = line.strip()
                            break
                if yield_val:
                    break

        if not yield_val:
            warnings.append(
                "No serving or yield metadata detected near the block header (e.g., 'yields ...' or 'serves ...').")

        # 3. Ingredients, Directions, and Notes Extraction
        ingredients_map = {}
        directions_map = {}
        notes = []

        current_section = None
        current_component = "Main"

        has_ingredients_header = False
        has_directions_header = False

        # Pre-scan for standard layout headers to toggle Fallback behavior correctly
        for node in block_nodes:
            if isinstance(node, Heading) and node.level == 2:
                h_text = render_inline(node).strip()
                if RE_ING_HEADER.match(h_text):
                    has_ingredients_header = True
                elif RE_DIR_HEADER.match(h_text):
                    has_directions_header = True

        for node in block_nodes:
            if isinstance(node, Heading):
                if node.level == 1:
                    continue
                elif node.level == 2:
                    h_text = render_inline(node).strip()
                    ing_match = RE_ING_HEADER.match(h_text)
                    dir_match = RE_DIR_HEADER.match(h_text)

                    if ing_match:
                        current_section = "ingredients"
                        current_component = ing_match.group(1) or "Main"
                        if current_component not in ingredients_map:
                            ingredients_map[current_component] = []
                    elif dir_match:
                        current_section = "directions"
                        current_component = dir_match.group(1) or "Main"
                        if current_component not in directions_map:
                            directions_map[current_component] = []
                    elif any(x in h_text.lower() for x in
                             ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                        current_section = "notes"
                        current_component = "Main"
                    else:
                        current_section = None
                        current_component = "Main"
                else:
                    if current_section == "notes":
                        notes.append(render_inline(node).strip())

            elif isinstance(node, List):
                # Fallback: Treat list elements natively as ingredients or directions if headings are omitted
                is_ordered = getattr(node, "start", None) is not None or getattr(node, "ordered", False)
                if current_section is None or (not has_ingredients_header and not has_directions_header):
                    if is_ordered:
                        current_section_node = "directions"
                    else:
                        current_section_node = "ingredients"
                else:
                    current_section_node = current_section

                if current_section_node == "ingredients":
                    comp_list = ingredients_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(parse_ingredient_line(render_inline(item)))
                elif current_section_node == "directions":
                    comp_list = directions_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(render_inline(item).strip())

            elif isinstance(node, Paragraph):
                p_text = render_inline(node).strip()
                if current_section == "notes":
                    notes.append(p_text)

                # Check for bare URLs line by line
                for line in p_text.splitlines():
                    match = RE_BARE_URL.search(line)
                    if match:
                        warnings.append(
                            f"Contains bare URL not wrapped in angle brackets or Markdown links: '{match.group(0)}'")

        # Enforce validation notifications
        if not has_ingredients_header:
            warnings.append("Missing '## Ingredients' header.")
        if not has_directions_header:
            warnings.append("Missing '## Directions' or '## Instructions' header.")

        # Re-map ingredient map to expected layout list
        formatted_ingredients = []
        for comp, items in ingredients_map.items():
            if items:
                formatted_ingredients.append({
                    "component": comp,
                    "items":     items
                })

        # Re-map direction map to expected layout list
        formatted_directions = []
        for comp, steps in directions_map.items():
            if steps:
                formatted_directions.append({
                    "component": comp,
                    "steps":     steps
                })

        recipes.append({
            "title":       title,
            "yield":       yield_val,
            "ingredients": formatted_ingredients,
            "directions":  formatted_directions,
            "notes":       notes,
            "warnings":    warnings
        })

    return recipes

banana_pudding_md = """# Magnolia Bakery's Banana Pudding

* https://www.the-girl-who-ate-everything.com/magnolia-bakerys-famous-banana-pudding/
* https://astudio.google.com/app/prompts

## Ingredients

* 6 Tbsp sweetened condensed milk
* ~3/4 cup iced water

## Directions

1. Create the pudding base.
"""
parsed = parse_and_audit_blocks(banana_pudding_md, {"title": "Banana Pudding"})
print(json.dumps(parsed, indent=2))

"""
then later
"""

# Let's test all these parser improvements inside the sandbox to verify that:
# 1. H1 headers are correctly extracted as the title.
# 2. Ingredients/Directions are correctly separated.
# 3. Blockquotes are parsed as notes.
# 4. List items under Notes are parsed as notes.
# 5. Wrapped URLs are flagged (and bare URLs are allowed without warnings).

class RawText:
    def __init__(self, content):
        self.content = content


class Heading:
    def __init__(self, level, children):
        self.level = level
        self.children = children


class Paragraph:
    def __init__(self, children):
        self.children = children


class ListItem:
    def __init__(self, children):
        self.children = children


class List:
    def __init__(self, children, start=None):
        self.children = children
        self.start = start


class ThematicBreak:
    pass


class Quote:
    def __init__(self, children):
        self.children = children


def render_inline_v2(token) -> str:
    """Recursively flattens inline and block nodes into standard text, preserving newlines for structural blocks."""
    if hasattr(token, 'content'):
        return token.content
    if hasattr(token, 'children') and token.children:
        # Join block-level containers with newlines to keep lines distinct
        if type(token).__name__ in ('List', 'ListItem', 'Document', 'Quote'):
            return "\n".join(render_inline_v2(child) for child in token.children)
        return "".join(render_inline_v2(child) for child in token.children)
    return ""


def mock_parse_markdown_v2(content_text: str):
    # Normalize line endings first
    content_text = content_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = content_text.splitlines()
    children = []

    current_list = None
    is_current_ordered = None

    # Simple blockquote parser state
    in_quote = False
    quote_lines = []

    for line in lines:
        stripped = line.strip()

        # Parse blockquotes
        if stripped.startswith('>'):
            if current_list:
                children.append(current_list)
                current_list = None
            in_quote = True
            quote_lines.append(stripped.lstrip('> ').strip())
            continue
        elif in_quote:
            # End of quote block
            in_quote = False
            children.append(Quote([Paragraph([RawText("\n".join(quote_lines))])]))
            quote_lines = []

        if not stripped:
            if current_list:
                children.append(current_list)
                current_list = None
            continue

        if re.match(r'^(?:---|\*\*\*)\s*$', stripped):
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(ThematicBreak())
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(Heading(len(heading_match.group(1)), [RawText(heading_match.group(2))]))
            continue

        ul_match = re.match(r'^[\*\-+]\s+(.+)$', stripped)
        if ul_match:
            item_text = ul_match.group(1)
            if current_list is None or is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=None)
                is_current_ordered = False
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if ol_match:
            start_num = int(ol_match.group(1))
            item_text = ol_match.group(2)
            if current_list is None or not is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=start_num)
                is_current_ordered = True
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        if current_list:
            children.append(current_list)
            current_list = None

        if children and type(children[-1]).__name__ == 'Paragraph':
            p_text = render_inline_v2(children[-1]) + "\n" + stripped
            children[-1] = Paragraph([RawText(p_text)])
        else:
            children.append(Paragraph([RawText(stripped)]))

    if in_quote:
        children.append(Quote([Paragraph([RawText("\n".join(quote_lines))])]))
    if current_list:
        children.append(current_list)

    return children


RE_WRAPPED_URL = re.compile(r'<(https?://[^\s>]+)>', re.IGNORECASE)


def parse_and_audit_blocks_v2(content_text: str, metadata: dict) -> list:
    content_text = content_text.replace('\r\n', '\n').replace('\r', '')
    children = mock_parse_markdown_v2(content_text)

    raw_blocks = []
    current_block = []

    for i, node in enumerate(children):
        if type(node).__name__ == 'ThematicBreak':
            next_heading = False
            for j in range(i + 1, len(children)):
                next_node = children[j]
                if type(next_node).__name__ == 'Heading':
                    if next_node.level == 1:
                        next_heading = True
                    break
                if type(next_node).__name__ != 'ThematicBreak':
                    break
            if next_heading:
                if current_block:
                    raw_blocks.append(current_block)
                    current_block = []
                continue
        current_block.append(node)
    if current_block:
        raw_blocks.append(current_block)

    recipes = []

    for idx, block_nodes in enumerate(raw_blocks):
        warnings = []

        # 1. Title Extraction
        title = None
        for node in block_nodes:
            if type(node).__name__ == 'Heading' and node.level == 1:
                title = render_inline_v2(node).strip()
                break
        if not title:
            if idx == 0 and 'title' in metadata:
                title = metadata['title']
            else:
                title = f"Recipe {idx + 1}"

        # 2. Yield Extraction
        yield_val = None
        for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
            if key in metadata and metadata[key]:
                yield_val = str(metadata[key]).strip()
                break

        if not yield_val:
            for node in block_nodes[:15]:
                if type(node).__name__ in ('Paragraph', 'List'):
                    text = render_inline_v2(node)
                    for line in text.splitlines():
                        if RE_YIELD_PATTERN.search(line):
                            yield_val = line.strip()
                            break
                if yield_val:
                    break

        # 3. Ingredients, Directions, and Notes Extraction
        ingredients_map = {}
        directions_map = {}
        notes = []

        current_section = None
        current_component = "Main"

        has_ingredients_header = False
        has_directions_header = False

        for node in block_nodes:
            if type(node).__name__ == 'Heading' and node.level == 2:
                h_text = render_inline_v2(node).strip()
                if RE_ING_HEADER.match(h_text):
                    has_ingredients_header = True
                elif RE_DIR_HEADER.match(h_text):
                    has_directions_header = True

        for node in block_nodes:
            node_type = type(node).__name__

            if node_type == 'Heading':
                if node.level == 1:
                    continue
                elif node.level == 2:
                    h_text = render_inline_v2(node).strip()
                    ing_match = RE_ING_HEADER.match(h_text)
                    dir_match = RE_DIR_HEADER.match(h_text)

                    if ing_match:
                        current_section = "ingredients"
                        current_component = ing_match.group(1) or "Main"
                        if current_component not in ingredients_map:
                            ingredients_map[current_component] = []
                    elif dir_match:
                        current_section = "directions"
                        current_component = dir_match.group(1) or "Main"
                        if current_component not in directions_map:
                            directions_map[current_component] = []
                    elif any(x in h_text.lower() for x in
                             ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                        current_section = "notes"
                        current_component = "Main"
                    else:
                        current_section = None
                        current_component = "Main"
                else:
                    # Heading 3 or deeper
                    if current_section == "notes":
                        notes.append(render_inline_v2(node).strip())

            elif node_type == 'List':
                is_ordered = getattr(node, "start", None) is not None
                if current_section is None or (not has_ingredients_header and not has_directions_header):
                    if is_ordered:
                        current_section_node = "directions"
                    else:
                        current_section_node = "ingredients"
                else:
                    current_section_node = current_section

                if current_section_node == "ingredients":
                    comp_list = ingredients_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(parse_ingredient_line(render_inline_v2(item)))
                elif current_section_node == "directions":
                    comp_list = directions_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(render_inline_v2(item).strip())
                elif current_section_node == "notes":
                    for item in node.children:
                        notes.append(render_inline_v2(item).strip())

            elif node_type == 'Paragraph':
                p_text = render_inline_v2(node).strip()
                if current_section == "notes":
                    notes.append(p_text)

                # Flag wrapped links line by line
                for line in p_text.splitlines():
                    wrapped_match = RE_WRAPPED_URL.search(line)
                    if wrapped_match:
                        warnings.append(
                            f"Contains wrapped link (standardize on bare links): '{wrapped_match.group(0)}'")

            elif node_type == 'Quote':
                q_text = render_inline_v2(node).strip()
                notes.append(q_text)

        # Re-map lists to output shapes
        formatted_ingredients = []
        for comp, items in ingredients_map.items():
            if items:
                formatted_ingredients.append({"component": comp, "items": items})
        formatted_directions = []
        for comp, steps in directions_map.items():
            if steps:
                formatted_directions.append({"component": comp, "steps": steps})

        recipes.append({
            "title":       title,
            "yield":       yield_val,
            "ingredients": formatted_ingredients,
            "directions":  formatted_directions,
            "notes":       notes,
            "warnings":    warnings
        })

    return recipes


# Run test on banana_pudding_full!
parsed = parse_and_audit_blocks_v2(banana_pudding_full, {})
print(json.dumps(parsed, indent=2))
"""
some test code?
"""


# Let's run a detailed trace of parse_and_audit_blocks on banana-pudding markdown
banana_pudding_full = """# Magnolia Bakery's Banana Pudding

* https://www.the-girl-who-ate-everything.com/magnolia-bakerys-famous-banana-pudding/
* https://aistudio.google.com/app/prompts?state=%7B%22ids%22:%5B%221jwyLxdi_EUWitPu6iqiDydJ1OAD7WQDN%22%5D,%22action%22:%22open%22,%22userId%22:%22117280320071755292615%22,%22resourceKeys%22:%7B%7D%7D&usp=sharing

## Ingredients

* 6 Tbsp sweetened condensed milk
* ~3/4 cup iced water
* 2-3 Tbsp jell-o instant vanilla pudding mix (must be "instant")
* 1 cup heavy cream
* 250g (8oz) pack of Biscoff Lotus biscuits <- can use less, maybe 200g
* 3-4 ripe bananas, peeled, de-stringed, and sliced

## Directions

1. **Create the pudding base:**
   In a medium bowl, whisk together the sweetened condensed milk, ice, and water until combined.
   Add the instant vanilla pudding mix and continue to whisk until the mixture is smooth and free of lumps.
   Cover the bowl and refrigerate for at least 3-4 hours, or overnight, until the pudding has set and is firm.
2. **Make the whipped cream and fold in the pudding:**
   In a separate large bowl, use an electric mixer or stand mixer to whip the cold heavy cream until stiff peaks form.
   Be careful not to over-whip. Gently fold the chilled pudding mixture into the whipped cream with a spatula
   until they are fully incorporated and no streaks remain.
3. **Assemble and chill:**
   You can layer the pudding mixture, bananas, and about three-quarters of the Biscoff cookies (broken into pieces)
   in a trifle dish or individual bowls, or simply fold them all together.
   Cover and refrigerate for at least 4 hours to allow the cookies to soften and the flavors to meld.
4. **Serve:**
   Before serving, garnish the banana pudding with the remaining Biscoff cookies, either whole or crumbled on top.

---

# (Original) Magnolia's Famous Banana Pudding

SERVES 12-15

> I started making this pudding when I was in my early twenties and cooking at a Tex-Mex restaurant and bar.
> Customers loved it, so when we opened the bakery many years later, it seemed like a great idea to serve it there.
> It remains the second most popular dessert (after the cupcakes) at the bakery.

## Ingredients

* One 14-ounce can sweetened condensed milk
* 1½ cups ice-cold water
* One 3.4-ounce package instant vanilla pudding mix (preferably Jell-O brand)
* 3 cups heavy cream
* One 12-ounce box Nabisco Nilla Wafers (no substitutions!)
* 4 cups sliced ripe bananas

## Directions

1. In a small bowl, on the medium speed of an electric mixer,
   beat together the sweetened condensed milk and water until well combined, about 1 minute.
   Add the pudding mix and beat well, about 2 minutes more.
   Cover and refrigerate for 3-4 hours or overnight, before continuing.
   It is very important to allow the proper amount of time for the pudding mixture to set.

2. In a large bowl, on the medium speed of an electric mixer, whip the heavy cream until stiff peaks form.
   Gently fold the pudding mixture into the whipped cream until well blended and no streaks of pudding remain.

3. To assemble the dessert, select a large, wide bowl (preferably glass) with a 4-5 quart capacity.
   Arrange one-third of the wafers to cover the bottom of the bowl, overlapping if necessary,
   then one-third of the bananas and one-third of the pudding.
   Repeat the layering twice more, garnishing with additional wafers or wafer crumbs on the top layer of the pudding.
   Cover tightly with plastic wrap and allow to chill in the refrigerator for 4 hours--or up to 8 hours,
   but no longer!--before serving.

*Ice Creams and Icebox Desserts*
*Page 113*
"""

# Let's run the parser on this
parsed = parse_and_audit_blocks(banana_pudding_full, {})
print(json.dumps(parsed, indent=2))

"""
from later on
"""
# Define the regexes and parsing functions and run the test

import re
import json

class RawText:
    def __init__(self, content):
        self.content = content

class Heading:
    def __init__(self, level, children):
        self.level = level
        self.children = children

class Paragraph:
    def __init__(self, children):
        self.children = children

class ListItem:
    def __init__(self, children):
        self.children = children

class List:
    def __init__(self, children, start=None):
        self.children = children
        self.start = start

    @property
    def is_ordered(self):
        return self.start is not None

class ThematicBreak:
    pass

def render_inline(token) -> str:
    if hasattr(token, 'content'):
        return token.content
    if hasattr(token, 'children') and token.children:
        return "".join(render_inline(child) for child in token.children)
    return ""

def parse_markdown_to_ast(content_text: str):
    lines = content_text.splitlines()
    children = []
    current_list = None
    is_current_ordered = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_list:
                children.append(current_list)
                current_list = None
            continue

        if re.match(r'^(?:---|\*\*\*)\s*$', stripped):
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(ThematicBreak())
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(Heading(len(heading_match.group(1)), [RawText(heading_match.group(2))]))
            continue

        ul_match = re.match(r'^[\*\-+]\s+(.+)$', stripped)
        if ul_match:
            item_text = ul_match.group(1)
            if current_list is None or is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=None)
                is_current_ordered = False
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if ol_match:
            start_num = int(ol_match.group(1))
            item_text = ol_match.group(2)
            if current_list is None or not is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=start_num)
                is_current_ordered = True
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        if current_list:
            children.append(current_list)
            current_list = None

        if children and isinstance(children[-1], Paragraph):
            p_text = render_inline(children[-1]) + "\n" + stripped
            children[-1] = Paragraph([RawText(p_text)])
        else:
            children.append(Paragraph([RawText(stripped)]))

    if current_list:
        children.append(current_list)

    return children

RE_YIELD_PATTERN = re.compile(r'\b(yields?|serves?|makes|pax|portions?|people)\b', re.IGNORECASE)
RE_BARE_URL = re.compile(r'(?<![<"\'`=])(?<!]\()(https?://[^\s<>"\'`]+[^\s<>"\'`.,;:!?)]+)', re.IGNORECASE)

# Category regex matchers for ingredients and directions
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
    return {
        "raw":      line,
        "quantity": "",
        "unit":     "",
        "name":     line
    }

def parse_and_audit_blocks(content_text: str, metadata: dict) -> list:
    children = parse_markdown_to_ast(content_text)
    raw_blocks = []
    current_block = []

    for i, node in enumerate(children):
        if isinstance(node, ThematicBreak):
            next_heading = False
            for j in range(i + 1, len(children)):
                next_node = children[j]
                if isinstance(next_node, Heading):
                    if next_node.level == 1:
                        next_heading = True
                    break
                if not isinstance(next_node, ThematicBreak):
                    break
            if next_heading:
                if current_block:
                    raw_blocks.append(current_block)
                    current_block = []
                continue
        current_block.append(node)
    if current_block:
        raw_blocks.append(current_block)

    recipes = []

    for idx, block_nodes in enumerate(raw_blocks):
        warnings = []

        # 1. Title Extraction
        title = None
        for node in block_nodes:
            if isinstance(node, Heading) and node.level == 1:
                title = render_inline(node).strip()
                break
        if not title:
            if idx == 0 and 'title' in metadata:
                title = metadata['title']
                warnings.append("Missing H1 Title ('# Title') at start of block (using frontmatter title).")
            else:
                title = f"Recipe {idx + 1}"
                warnings.append("Missing H1 Title ('# Title') at the start of this block.")

        # 2. Yield Extraction
        yield_val = None
        for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
            if key in metadata and metadata[key]:
                yield_val = str(metadata[key]).strip()
                break

        if not yield_val:
            for node in block_nodes[:15]:
                if isinstance(node, (Paragraph, List)):
                    text = render_inline(node)
                    for line in text.splitlines():
                        if RE_YIELD_PATTERN.search(line):
                            yield_val = line.strip()
                            break
                if yield_val:
                    break

        if not yield_val:
            warnings.append(
                "No serving or yield metadata detected near the block header (e.g., 'yields ...' or 'serves ...').")

        # 3. Ingredients, Directions, and Notes Extraction
        ingredients_map = {}
        directions_map = {}
        notes = []

        current_section = None
        current_component = "Main"

        has_ingredients_header = False
        has_directions_header = False

        # Pre-scan for standard layout headers to toggle Fallback behavior correctly
        for node in block_nodes:
            if isinstance(node, Heading) and node.level == 2:
                h_text = render_inline(node).strip()
                if RE_ING_HEADER.match(h_text):
                    has_ingredients_header = True
                elif RE_DIR_HEADER.match(h_text):
                    has_directions_header = True

        for node in block_nodes:
            if isinstance(node, Heading):
                if node.level == 1:
                    continue
                elif node.level == 2:
                    h_text = render_inline(node).strip()
                    ing_match = RE_ING_HEADER.match(h_text)
                    dir_match = RE_DIR_HEADER.match(h_text)

                    if ing_match:
                        current_section = "ingredients"
                        current_component = ing_match.group(1) or "Main"
                        if current_component not in ingredients_map:
                            ingredients_map[current_component] = []
                    elif dir_match:
                        current_section = "directions"
                        current_component = dir_match.group(1) or "Main"
                        if current_component not in directions_map:
                            directions_map[current_component] = []
                    elif any(x in h_text.lower() for x in
                             ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                        current_section = "notes"
                        current_component = "Main"
                    else:
                        current_section = None
                        current_component = "Main"
                else:
                    if current_section == "notes":
                        notes.append(render_inline(node).strip())

            elif isinstance(node, List):
                # Fallback: Treat list elements natively as ingredients or directions if headings are omitted
                is_ordered = getattr(node, "start", None) is not None or getattr(node, "ordered", False)
                if current_section is None or (not has_ingredients_header and not has_directions_header):
                    if is_ordered:
                        current_section_node = "directions"
                    else:
                        current_section_node = "ingredients"
                else:
                    current_section_node = current_section

                if current_section_node == "ingredients":
                    comp_list = ingredients_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(parse_ingredient_line(render_inline(item)))
                elif current_section_node == "directions":
                    comp_list = directions_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(render_inline(item).strip())

            elif isinstance(node, Paragraph):
                p_text = render_inline(node).strip()
                if current_section == "notes":
                    notes.append(p_text)

                # Check for bare URLs line by line
                for line in p_text.splitlines():
                    match = RE_BARE_URL.search(line)
                    if match:
                        warnings.append(
                            f"Contains bare URL not wrapped in angle brackets or Markdown links: '{match.group(0)}'")

        # Enforce validation notifications
        if not has_ingredients_header:
            warnings.append("Missing '## Ingredients' header.")
        if not has_directions_header:
            warnings.append("Missing '## Directions' or '## Instructions' header.")

        # Re-map ingredient map to expected layout list
        formatted_ingredients = []
        for comp, items in ingredients_map.items():
            if items:
                formatted_ingredients.append({
                    "component": comp,
                    "items":     items
                })

        # Re-map direction map to expected layout list
        formatted_directions = []
        for comp, steps in directions_map.items():
            if steps:
                formatted_directions.append({
                    "component": comp,
                    "steps":     steps
                })

        recipes.append({
            "title":       title,
            "yield":       yield_val,
            "ingredients": formatted_ingredients,
            "directions":  formatted_directions,
            "notes":       notes,
            "warnings":    warnings
        })

    return recipes

banana_pudding_md = """# Magnolia Bakery's Banana Pudding

* https://www.the-girl-who-ate-everything.com/magnolia-bakerys-famous-banana-pudding/
* https://astudio.google.com/app/prompts

## Ingredients

* 6 Tbsp sweetened condensed milk
* ~3/4 cup iced water

## Directions

1. Create the pudding base.
"""
parsed = parse_and_audit_blocks(banana_pudding_md, {"title": "Banana Pudding"})
print(json.dumps(parsed, indent=2))



"""
from even later on
"""
# Let's test all these parser improvements inside the sandbox to verify that:
# 1. H1 headers are correctly extracted as the title.
# 2. Ingredients/Directions are correctly separated.
# 3. Blockquotes are parsed as notes.
# 4. List items under Notes are parsed as notes.
# 5. Wrapped URLs are flagged (and bare URLs are allowed without warnings).

class RawText:
    def __init__(self, content):
        self.content = content


class Heading:
    def __init__(self, level, children):
        self.level = level
        self.children = children


class Paragraph:
    def __init__(self, children):
        self.children = children


class ListItem:
    def __init__(self, children):
        self.children = children


class List:
    def __init__(self, children, start=None):
        self.children = children
        self.start = start


class ThematicBreak:
    pass


class Quote:
    def __init__(self, children):
        self.children = children


def render_inline_v2(token) -> str:
    """Recursively flattens inline and block nodes into standard text, preserving newlines for structural blocks."""
    if hasattr(token, 'content'):
        return token.content
    if hasattr(token, 'children') and token.children:
        # Join block-level containers with newlines to keep lines distinct
        if type(token).__name__ in ('List', 'ListItem', 'Document', 'Quote'):
            return "\n".join(render_inline_v2(child) for child in token.children)
        return "".join(render_inline_v2(child) for child in token.children)
    return ""


def mock_parse_markdown_v2(content_text: str):
    # Normalize line endings first
    content_text = content_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = content_text.splitlines()
    children = []

    current_list = None
    is_current_ordered = None

    # Simple blockquote parser state
    in_quote = False
    quote_lines = []

    for line in lines:
        stripped = line.strip()

        # Parse blockquotes
        if stripped.startswith('>'):
            if current_list:
                children.append(current_list)
                current_list = None
            in_quote = True
            quote_lines.append(stripped.lstrip('> ').strip())
            continue
        elif in_quote:
            # End of quote block
            in_quote = False
            children.append(Quote([Paragraph([RawText("\n".join(quote_lines))])]))
            quote_lines = []

        if not stripped:
            if current_list:
                children.append(current_list)
                current_list = None
            continue

        if re.match(r'^(?:---|\*\*\*)\s*$', stripped):
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(ThematicBreak())
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading_match:
            if current_list:
                children.append(current_list)
                current_list = None
            children.append(Heading(len(heading_match.group(1)), [RawText(heading_match.group(2))]))
            continue

        ul_match = re.match(r'^[\*\-+]\s+(.+)$', stripped)
        if ul_match:
            item_text = ul_match.group(1)
            if current_list is None or is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=None)
                is_current_ordered = False
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if ol_match:
            start_num = int(ol_match.group(1))
            item_text = ol_match.group(2)
            if current_list is None or not is_current_ordered:
                if current_list:
                    children.append(current_list)
                current_list = List(children=[], start=start_num)
                is_current_ordered = True
            current_list.children.append(ListItem([RawText(item_text)]))
            continue

        if current_list:
            children.append(current_list)
            current_list = None

        if children and type(children[-1]).__name__ == 'Paragraph':
            p_text = render_inline_v2(children[-1]) + "\n" + stripped
            children[-1] = Paragraph([RawText(p_text)])
        else:
            children.append(Paragraph([RawText(stripped)]))

    if in_quote:
        children.append(Quote([Paragraph([RawText("\n".join(quote_lines))])]))
    if current_list:
        children.append(current_list)

    return children


RE_WRAPPED_URL = re.compile(r'<(https?://[^\s>]+)>', re.IGNORECASE)


def parse_and_audit_blocks_v2(content_text: str, metadata: dict) -> list:
    content_text = content_text.replace('\r\n', '\n').replace('\r', '')
    children = mock_parse_markdown_v2(content_text)

    raw_blocks = []
    current_block = []

    for i, node in enumerate(children):
        if type(node).__name__ == 'ThematicBreak':
            next_heading = False
            for j in range(i + 1, len(children)):
                next_node = children[j]
                if type(next_node).__name__ == 'Heading':
                    if next_node.level == 1:
                        next_heading = True
                    break
                if type(next_node).__name__ != 'ThematicBreak':
                    break
            if next_heading:
                if current_block:
                    raw_blocks.append(current_block)
                    current_block = []
                continue
        current_block.append(node)
    if current_block:
        raw_blocks.append(current_block)

    recipes = []

    for idx, block_nodes in enumerate(raw_blocks):
        warnings = []

        # 1. Title Extraction
        title = None
        for node in block_nodes:
            if type(node).__name__ == 'Heading' and node.level == 1:
                title = render_inline_v2(node).strip()
                break
        if not title:
            if idx == 0 and 'title' in metadata:
                title = metadata['title']
            else:
                title = f"Recipe {idx + 1}"

        # 2. Yield Extraction
        yield_val = None
        for key in ['yield', 'yields', 'serves', 'servings', 'portions', 'pax']:
            if key in metadata and metadata[key]:
                yield_val = str(metadata[key]).strip()
                break

        if not yield_val:
            for node in block_nodes[:15]:
                if type(node).__name__ in ('Paragraph', 'List'):
                    text = render_inline_v2(node)
                    for line in text.splitlines():
                        if RE_YIELD_PATTERN.search(line):
                            yield_val = line.strip()
                            break
                if yield_val:
                    break

        # 3. Ingredients, Directions, and Notes Extraction
        ingredients_map = {}
        directions_map = {}
        notes = []

        current_section = None
        current_component = "Main"

        has_ingredients_header = False
        has_directions_header = False

        for node in block_nodes:
            if type(node).__name__ == 'Heading' and node.level == 2:
                h_text = render_inline_v2(node).strip()
                if RE_ING_HEADER.match(h_text):
                    has_ingredients_header = True
                elif RE_DIR_HEADER.match(h_text):
                    has_directions_header = True

        for node in block_nodes:
            node_type = type(node).__name__

            if node_type == 'Heading':
                if node.level == 1:
                    continue
                elif node.level == 2:
                    h_text = render_inline_v2(node).strip()
                    ing_match = RE_ING_HEADER.match(h_text)
                    dir_match = RE_DIR_HEADER.match(h_text)

                    if ing_match:
                        current_section = "ingredients"
                        current_component = ing_match.group(1) or "Main"
                        if current_component not in ingredients_map:
                            ingredients_map[current_component] = []
                    elif dir_match:
                        current_section = "directions"
                        current_component = dir_match.group(1) or "Main"
                        if current_component not in directions_map:
                            directions_map[current_component] = []
                    elif any(x in h_text.lower() for x in
                             ["note", "comment", "troubleshoot", "science", "to-do", "todo", "editor"]):
                        current_section = "notes"
                        current_component = "Main"
                    else:
                        current_section = None
                        current_component = "Main"
                else:
                    # Heading 3 or deeper
                    if current_section == "notes":
                        notes.append(render_inline_v2(node).strip())

            elif node_type == 'List':
                is_ordered = getattr(node, "start", None) is not None
                if current_section is None or (not has_ingredients_header and not has_directions_header):
                    if is_ordered:
                        current_section_node = "directions"
                    else:
                        current_section_node = "ingredients"
                else:
                    current_section_node = current_section

                if current_section_node == "ingredients":
                    comp_list = ingredients_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(parse_ingredient_line(render_inline_v2(item)))
                elif current_section_node == "directions":
                    comp_list = directions_map.setdefault(current_component, [])
                    for item in node.children:
                        comp_list.append(render_inline_v2(item).strip())
                elif current_section_node == "notes":
                    for item in node.children:
                        notes.append(render_inline_v2(item).strip())

            elif node_type == 'Paragraph':
                p_text = render_inline_v2(node).strip()
                if current_section == "notes":
                    notes.append(p_text)

                # Flag wrapped links line by line
                for line in p_text.splitlines():
                    wrapped_match = RE_WRAPPED_URL.search(line)
                    if wrapped_match:
                        warnings.append(
                            f"Contains wrapped link (standardize on bare links): '{wrapped_match.group(0)}'")

            elif node_type == 'Quote':
                q_text = render_inline_v2(node).strip()
                notes.append(q_text)

        # Re-map lists to output shapes
        formatted_ingredients = []
        for comp, items in ingredients_map.items():
            if items:
                formatted_ingredients.append({"component": comp, "items": items})
        formatted_directions = []
        for comp, steps in directions_map.items():
            if steps:
                formatted_directions.append({"component": comp, "steps": steps})

        recipes.append({
            "title":       title,
            "yield":       yield_val,
            "ingredients": formatted_ingredients,
            "directions":  formatted_directions,
            "notes":       notes,
            "warnings":    warnings
        })

    return recipes


# Run test on banana_pudding_full!
parsed = parse_and_audit_blocks_v2(banana_pudding_full, {})
print(json.dumps(parsed, indent=2))