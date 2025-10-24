from pathlib import Path

# --- Configuration ---
ROOT_DIRS = [Path('recipes'), Path('in-progress'), Path('curated-untested')]


# --- Helper Functions ---

def get_title(dir_name: str) -> str:
    """
    Generates a human-readable title from a file or folder name.

    :param dir_name:
    :return:
    """
    # change `-` and `_` to space and titlecase (after coalescing and stripping whitespace)
    _default = ' '.join(dir_name.replace('-', ' ').replace('_', ' ').split()).title()

    # these are the special cases
    _title_map = {
        'curated-untested': 'Curated & Untested',
        'kfc': 'KFC',
    }

    return _title_map.get(dir_name, _default)


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
    for directory in root_dir.rglob('**/'):
        if not directory.is_dir(): continue

        if directory in ROOT_DIRS:
            print(f"Skipping index.md for top-level collection folder: {directory}")
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

        parent = None
        if md_file.parent not in ROOT_DIRS:
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
for root_dir in ROOT_DIRS:
    for md_file in root_dir.rglob('*.md'):
        content = md_file.read_text(encoding='utf-8')
        if '.md)' in content:
            new_content = content.replace('.md)', '.html)')
            md_file.write_text(new_content, encoding='utf-8')
            print(f"Fixed links in: {md_file}")

print("\nJekyll pre-build script complete.")
