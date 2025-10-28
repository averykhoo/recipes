import re
from pathlib import Path
from typing import Optional

import frontmatter

# --- Configuration ---

# these are the collections to be published in the Jekyll site
# all other folders (and any md files not in folders) will not be published, except for the main index.md
COLLECTION_DIRS = [
    Path('_recipes'),
    Path('_in-progress'),
    Path('_curated-untested'),
]

# this is used to replace links to *.md with links to *.html, which is what jekyll generates
# it's a little long so i suggest using https://www.debuggex.com to inspect the diagram
RE_LINK = re.compile(
    r"(?<!!)(\[(?:\\[\[\]]|(?<!\\)[^[\]])*])\((((?<!<)[^)#\s]+)\.md([\s#][^)]*)?|(<[^)#>]+)\.md(\s*[#>][^)]*)?)\)",
    re.I)
RE_LINK_SUB = r'\1(\3\5.html\4\6)'


# --- Helper Functions ---

def get_title(dir_name: str) -> str:
    """
    Generates a human-readable title from a file or folder name.
    Note that collection names are not processed here, but via `_config.yml`

    :param dir_name:
    :return:
    """
    # replace hyphens and underscores with spaces, then title case
    title = re.sub(r'[\s_-]+', ' ', dir_name).strip().title()

    # these are the special cases
    special_cases = {
        'kfc': 'KFC',
    }
    return special_cases.get(dir_name, title)


def update_front_matter(file_path: Path,
                        title: str,
                        parent: str | None = None,
                        has_children: bool = False,
                        nav_order: int | None = None,
                        initial_content: str | None = None,
                        setdefault_layout: str = "default",
                        ) -> None:
    """
    Reads a file, updates its YAML front matter, and writes it back.

    - If the file or its parent directories do not exist, they will be created.
    - If the file has no front matter, it will be added.
    - Existing front matter keys will be updated with the provided values.
    - Keys for optional arguments (parent, has_children, nav_order) are only
      added or updated if a value is provided or if has_children is True.

    :param file_path: The path to the markdown file.
    :param title: The title for the front matter.
    :param parent: The parent page's title.
    :param has_children: Whether the page has child pages.
    :param nav_order: The navigation order.
    :param initial_content: New file content
    :param setdefault_layout: The default layout to set if none exists.
    """

    # 1. Ensure parent directories exist
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Read the existing file and its front matter
    try:
        post = frontmatter.load(str(file_path.resolve()))
        if post.content.rstrip('\r\n'):
            initial_content = None
    except FileNotFoundError:  # frontmatter.YAMLParseError:
        post = frontmatter.Post(content='')  # If file doesn't exist, start fresh

    # 3. Update the front matter with new or corrected info
    post.metadata.setdefault('layout', setdefault_layout)
    post.metadata['title'] = title
    if parent:
        post.metadata['parent'] = parent

    # In "Just the Docs", has_children is usually only present if true
    if has_children:
        post.metadata['has_children'] = True
    elif 'has_children' in post.metadata:
        del post.metadata['has_children']  # Clean up if not needed

    if nav_order is not None:
        post.metadata['nav_order'] = nav_order

    # If the file was newly created, add the initial content
    if initial_content:
        post.content = initial_content

    # 4. Write the updated post (front matter + content) back to the file
    with open(file_path, 'wb') as f:
        frontmatter.dump(post, f)


# --- Main Script Logic ---

if __name__ == '__main__':

    # (not needed now that we're copying in just the desired folders)
    # # 1. Clean up unwanted Markdown files to avoid building them into the site
    # print("--- Cleaning up unwanted markdown files ---")
    #
    # for md_file in Path('').glob('**/*.[mM][dD]'):
    #     # Keep the root index.md
    #     if md_file.resolve() == Path('index.md').resolve():
    #         continue
    #
    #     # Keep any file that is within one of the ROOT_DIRS, remove the rest
    #     is_in_root_dirs = any(root_dir.resolve() in md_file.resolve().parents for root_dir in COLLECTION_DIRS)
    #     if not is_in_root_dirs:
    #         print(f"Deactivating file by renaming: {md_file}")
    #         md_file.rename(md_file.with_suffix('.deactivated_md.txt'))

    # 2. Create parent index.md pages for navigation
    print("\n--- Generating parent index.md pages ---")
    for collection_dir in COLLECTION_DIRS:
        for directory in collection_dir.glob('**/'):
            if not directory.is_dir():
                continue

            if directory in COLLECTION_DIRS:
                print(f"Skipping index.md for top-level collection folder: {directory}")
                continue

            index_path = directory / 'index.md'
            _title = get_title(directory.name)

            update_front_matter(
                file_path=index_path,
                title=_title,
                parent=get_title(directory.parent.name) if directory.parent not in COLLECTION_DIRS else None,
                has_children=True,
                nav_order=1,
                initial_content=f"# {_title}\n\nThis section contains recipes related to {_title}.",
            )
            print(f"Processed parent page: {index_path}")

    # 3. Process all individual recipe files
    print("\n--- Generating front matter for recipe files ---")
    for collection_dir in COLLECTION_DIRS:
        for md_file in collection_dir.glob('**/*.[mM][dD]'):
            # Skip the index files we just created/verified
            if md_file.name == 'index.md':
                continue

            update_front_matter(
                file_path=md_file,
                title=get_title(md_file.stem),
                parent=get_title(md_file.parent.name) if md_file.parent not in COLLECTION_DIRS else None,
            )
            print(f"Processed recipe file: {md_file}")

    # 4. Fix internal Markdown links to point to .html

    # Regex to find .md links, capturing the part before the extension.
    # It is case-insensitive and handles anchors correctly.

    print("\n--- Fixing internal markdown links ---")
    all_md_files = [_md for _dir in COLLECTION_DIRS for _md in _dir.glob('**/*.[mM][dD]')]
    for md_file in all_md_files:
        try:
            content = md_file.read_text(encoding='utf-8')

            # Replace the matched .md extension with .html, preserving the captured path.
            new_content, num_replacements = RE_LINK.subn(RE_LINK_SUB, content)

            # Only write to the file if a change was actually made.
            if num_replacements > 0:
                md_file.write_text(new_content, encoding='utf-8')
                print(f"Fixed {num_replacements} link(s) in: {md_file}")

        except Exception as e:
            print(f"Error processing {md_file}: {e}")

    print("\nJekyll pre-build script complete.")
