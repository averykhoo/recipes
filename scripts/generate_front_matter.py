import os

# --- Configuration ---
# The directories we want to process.
ROOT_DIRS = ['recipes', 'in-progress', 'curated-untested']

# A mapping to create human-readable titles from folder names.
# Add any special cases here. If a folder name isn't in this map,
# a default title will be generated (e.g., 'kfc' -> 'Kfc').
TITLE_MAP = {
    'recipes': 'Recipes',
    'in-progress': 'In Progress',
    'curated-untested': 'Curated & Un-tested',
    'kfc': 'KFC',
    'pasta': 'Pasta',
    'confectionery': 'Confectionery',
}


# --- Script Logic ---

def get_title(name):
    """Generates a human-readable title from a file or folder name."""
    # Use the map if available, otherwise generate a default title.
    return TITLE_MAP.get(name, name.replace('-', ' ').replace('_', ' ').title())


if __name__ == '__main__':
    print("Starting front matter generation...")

    for root_dir in ROOT_DIRS:
        for dirpath, _, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith('.md'):
                    full_path = os.path.join(dirpath, filename)

                    # Split the path into parts (e.g., ['recipes', 'kfc', 'alternative-1.md'])
                    path_parts = full_path.split(os.sep)

                    # --- Determine Title, Parent, and Grandparent ---

                    # The title is the filename without extension.
                    file_basename = os.path.splitext(filename)[0]
                    title = get_title(file_basename)

                    parent = None
                    grand_parent = None

                    # If the file is in a subdirectory, determine parent/grandparent.
                    if len(path_parts) > 2:
                        parent_name = path_parts[-2]
                        parent = get_title(parent_name)
                    if len(path_parts) > 3:
                        grand_parent_name = path_parts[-3]
                        grand_parent = get_title(grand_parent_name)

                    # The root directory of the collection is the top-level parent.
                    if len(path_parts) > 1 and parent is None:
                        parent = get_title(path_parts[0])

                    # --- Build the Front Matter ---

                    front_matter = [
                        "---",
                        "layout: default",
                        f"title: {title}"
                    ]
                    if parent:
                        front_matter.append(f"parent: {parent}")
                    if grand_parent:
                        front_matter.append(f"grand_parent: {grand_parent}")
                    front_matter.append("---")

                    front_matter_str = "\n".join(front_matter) + "\n\n"

                    # --- Read original content and prepend new front matter ---

                    with open(full_path, 'r', encoding='utf-8') as f:
                        original_content = f.read()

                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(front_matter_str)
                        f.write(original_content)

                    print(f"Generated front matter for: {full_path}")

    print("Front matter generation complete.")
