from pathlib import Path

# --- Configuration ---
ROOT_DIRS = [Path('recipes'), Path('in-progress'), Path('curated-untested')]
TITLE_MAP = {
    'recipes': 'Recipes',
    'in-progress': 'In Progress',
    'curated-untested': 'Curated & Un-tested',
    'kfc': 'KFC',
    'pasta': 'Pasta',
    'confectionery': 'Confectionery',
}


# --- Helper Functions ---

def get_title(dir_name: str) -> str:
    """
    Generates a human-readable title from a file or folder name.

    :param dir_name:
    :return:
    """
    return TITLE_MAP.get(dir_name, dir_name.replace('-', ' ').replace('_', ' ').title())


def generate_front_matter_str(title: str,
                              parent: str | None = None,
                              has_children: bool = False,
                              nav_order: int | None = None,
                              ) -> str:
    """
    Generates a complete front matter block as a string using f-strings.

    :param title:
    :param parent:
    :param has_children:
    :param nav_order:
    :return:
    """
    lines = [
        "---",
        "layout: default",
        f"title: {title}"
    ]
    if parent:
        lines.append(f"parent: {parent}")
    if has_children:
        lines.append("has_children: true")
    if nav_order:
        lines.append(f"nav_order: {nav_order}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# --- Main Script Logic ---

# 1. Clean up unwanted Markdown files
print("--- Cleaning up unwanted markdown files ---")

for md_file in Path('.').glob('**/*.md'):
    # Keep the root index.md
    if md_file.resolve() == Path('index.md').resolve():
        continue

    # Keep any file that is within one of the ROOT_DIRS
    is_in_root_dirs = any(root_dir.resolve() in md_file.resolve().parents for root_dir in ROOT_DIRS)
    if not is_in_root_dirs:
        print(f"Deleting unwanted file: {md_file}")
        md_file.unlink()

# 2. Create parent index.md pages for navigation
print("\n--- Generating parent index.md pages ---")
for root_dir in ROOT_DIRS:
    # Use rglob to find all directories including the root
    all_dirs = [root_dir] + list(root_dir.rglob('**/'))
    for directory in all_dirs:
        if not directory.is_dir():
            continue

        index_path = directory / 'index.md'
        if index_path.exists():
            continue

        title = get_title(directory.name)
        parent = get_title(directory.parent.name) if directory.parent != Path('.') else None

        front_matter = generate_front_matter_str(title=title, parent=parent, has_children=True, nav_order=1)

        content = f"# {title}\n\nThis section contains recipes related to {title}."
        index_path.write_text(front_matter + content, encoding='utf-8')
        print(f"Created parent page: {index_path}")

# 3. Process all individual recipe files
print("\n--- Generating front matter for recipe files ---")
for root_dir in ROOT_DIRS:
    for md_file in root_dir.rglob('*.md'):
        # Skip the index files we just created/verified
        if md_file.name == 'index.md':
            continue

        title = get_title(md_file.stem)
        parent = get_title(md_file.parent.name)

        front_matter = generate_front_matter_str(title=title, parent=parent)

        original_content = md_file.read_text(encoding='utf-8')

        # Make the process idempotent: don't add front matter if it already exists
        if original_content.startswith('---'):
            print(f"Skipping already processed file: {md_file}")
            continue

        md_file.write_text(front_matter + original_content, encoding='utf-8')
        print(f"Generated front matter for: {md_file}")

# 4. Fix internal markdown links to point to .html
print("\n--- Fixing internal markdown links ---")
for root_dir in root_dirs_paths:
    for md_file in root_dir.rglob('*.md'):
        content = md_file.read_text(encoding='utf-8')
        if '.md)' in content:
            new_content = content.replace('.md)', '.html)')
            md_file.write_text(new_content, encoding='utf-8')
            print(f"Fixed links in: {md_file}")

print("\nJekyll pre-build script complete.")