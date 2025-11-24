# ==============================================================================
# Build Repository Prompt Script (Using File Extensions & Regex Token Estimation) # MODIFIED
# ==============================================================================
# This script scans a Git repository, identifies relevant text files based on
# their extensions while respecting ignore rules, estimates content size using
# regex, and constructs a detailed system prompt for an LLM. The prompt includes
# the repository structure and the content of included files, using consistent
# 4+ backticks for code blocks.
# ==============================================================================

import os
import re
import json
from pathlib import Path
from typing import Callable
from typing import Dict
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple

import pathspec

# ==============================================================================
# Configuration
# ==============================================================================

# !!! EDIT THESE VALUES !!!
REPO_PATH = Path("./")  # Path to the repository to scan
# List of filenames to treat as ignore files (e.g., .gitignore, .aiignore)
IGNORE_FILENAMES = [".gitignore", ".aiignore", ".llmignore"]
# Max file size based on estimated "tokens" (word/symbol chunks counted by regex)
# This limit applies ONLY to files included in the CONTENT section.
MAX_FILE_ESTIMATED_TOKENS = 80000  # Adjust based on experience
# Output filename for the generated prompt
OUTPUT_FILENAME = "system-prompt.txt"
# Chunk size for reading file head (no longer used for binary check, but kept for potential future use)
# UNKNOWN_FILE_CHECK_CHUNK_SIZE = 4096 # REMOVED (or keep if needed elsewhere)

# --- File Extension Configuration --- # NEW SECTION
# Define file extensions (lowercase, without the dot) to include.
# Add any text-based file types relevant to your repository.
INCLUDED_EXTENSIONS = {
    "asp", "asm", "S", "bat", "cmd", "c", "h", "cs", "cpp", "hpp", "cxx", "hxx",
    "clj", "cmake", "coffee", "lisp", "cl", "css", "csv", "dart", "dockerfile",
    "ex", "exs", "erl", "hrl", "f", "for", "f90", "f95", "txt", "text", "log",
    "go", "gql", "graphql", "groovy", "hs", "html", "htm", "ini", "java",
    "js", "mjs", "cjs", "json", "jsonl", "jsp", "jsx", "jl", "kt", "kts",
    "tex", "less", "lua", "mk", "makefile", "md", "markdown", "m", "mm",
    "ml", "mli", "pas", "pl", "pm", "php", "ps1", "pro", "proto", "py", "pyw",
    "r", "rb", "rs", "sass", "scss", "scala", "scm", "ss", "sh", "bash", "zsh",
    "sql", "swift", "tcl", "tf", "toml", "tsv", "tsx", "ts", "vb", "vbs",
    "v", "sv", "vhdl", "xml", "yaml", "yml",
}
# Define extensions (lowercase, without the dot) to explicitly exclude,
# even if they are text-like (e.g., large data files you don't want).
EXCLUDED_EXTENSIONS = {"sub", "srt"}  # Example

# Map common extensions (lowercase, without dot) to language hints for Markdown fences.
# If an extension is in INCLUDED_EXTENSIONS but not here, the hint will be the extension itself.
EXTENSION_TO_LANGUAGE_HINT = {
    "py": "python", "js": "javascript", "ts": "typescript", "tsx": "tsx",
    "jsx": "jsx", "java": "java", "c": "c", "cpp": "cpp", "cs": "csharp",  # c# -> csharp
    "go": "go", "rs": "rust", "rb": "ruby", "php": "php", "html": "html",
    "css": "css", "scss": "scss", "md": "markdown", "sh": "bash", "sql": "sql",
    "yaml": "yaml", "yml": "yaml", "json": "json", "xml": "xml", "kt": "kotlin",
    "swift": "swift", "pl": "perl", "lua": "lua", "r": "r", "scala": "scala",
    "hs": "haskell", "clj": "clojure", "ex": "elixir", "exs": "elixir",
    "dart": "dart", "tf": "terraform", "dockerfile": "dockerfile", "proto": "protobuf",
    "ps1": "powershell", "bat": "batch", "cmd": "batch", "h": "c", "hpp": "cpp",
    "hxx": "cpp", "cxx": "cpp", "m": "objectivec", "mm": "objectivec",  # obj-c
    "mk": "makefile", "makefile": "makefile", "tex": "latex", "vb": "vbnet",  # vb.net -> vbnet
    "v": "verilog", "sv": "systemverilog", "vhdl": "vhdl", "asm": "assembly", "S": "assembly",
    "lisp": "lisp", "cl": "commonlisp", "pas": "pascal", "f": "fortran", "for": "fortran",
    "f90": "fortran", "f95": "fortran", "groovy": "groovy", "ini": "ini", "toml": "toml",
    "less": "less", "tcl": "tcl", "gql": "graphql", "graphql": "graphql", "cmake": "cmake",
    "jsp": "jsp", "vbs": "vbscript", "txt": "", "text": "", "log": "",  # Empty hint for generic text
}

# --- Magika Configuration --- # REMOVED Magika specific config
# INCLUDED_MAGIKA_LABELS = { ... }
# EXCLUDED_MAGIKA_LABELS = {"subtitle"}
# HANDLE_UNKNOWN_AS_TEXT = True

# --- Prompt Template ---
# Uses 4 backticks for the repository tree block.
PROMPT_TEMPLATE = """
System Prompt:
{prompt_header}

**Repository Structure:**
````
{repository_tree}
````

**File Contents:**

{file_contents}
"""

# Define the introductory part of the system prompt.
PROMPT_HEADER = """
You will be provided with a snapshot of a repository, including its directory structure and the content of its key text files.

**Your primary task is to carefully read, analyze, and thoroughly understand the *entirety* of this provided information.** Do not just skim the contents. Process the directory structure, the relationships between files (e.g., how they might link, import, or relate thematically), and the substance within each file.

**Synthesize this information to build a comprehensive internal understanding of the repository's:**
*   **Overall purpose:** What is this repository *for*? (e.g., a software project, documentation, recipe collection, project plan, notes)
*   **Structure and Organization:** How are the files and directories laid out? How do they logically group together?
*   **Key Components and Content:** What are the most important files, concepts, topics, data points, or pieces of information contained within?

Your goal is to develop a robust mental model of this repository based *only* on the provided snapshot. This understanding is crucial for you to accurately and effectively answer subsequent user questions about any aspect of the repository.
"""


# ==============================================================================
# Data Structures
# ==============================================================================

class FileData(NamedTuple):
    """Holds information about files included in the prompt."""
    relative_path: Path
    absolute_path: Path
    estimated_tokens: int
    language_hint: str


# ==============================================================================
# Helper Functions
# ==============================================================================

# Compile regex for token estimation once for efficiency
# Matches sequences of word characters OR sequences of non-word/non-space characters
TOKEN_ESTIMATION_REGEX = re.compile(r'(\w+|[^\s\w]+)')


# ------------------------------------------------------------------------------
# Token Estimation
# ------------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Estimates token count by splitting text into word-like and symbol-like chunks
    using a regular expression. This is faster than formal tokenization but less accurate.
    """
    if not text:
        return 0
    # Find all matches and return the count (length of the list of matches)
    return len(TOKEN_ESTIMATION_REGEX.findall(text))


# ------------------------------------------------------------------------------
# Ignore File Handling
# ------------------------------------------------------------------------------

def load_specs_for_directory(directory: Path, ignore_filenames: List[str]) -> Optional[pathspec.PathSpec]:
    """
    Loads and combines ignore rules from all specified ignore files found
    within a single directory into a single PathSpec object.
    """
    spec_lines = []
    found_ignore_file = False
    for filename in ignore_filenames:
        ignore_file_path = directory / filename
        if ignore_file_path.is_file():
            found_ignore_file = True
            try:
                # Use errors='ignore' as ignore files might have encoding issues
                with ignore_file_path.open('r', encoding='utf-8', errors='ignore') as f:
                    # Add newline separator if adding lines after previous file content
                    if spec_lines and not spec_lines[-1].endswith('\n'):
                        spec_lines.append('\n')
                    spec_lines.extend(f.readlines())
            except Exception as e:
                print(f"Warning: Could not read ignore file {ignore_file_path}: {e}")

    if not found_ignore_file or not spec_lines:
        return None  # No ignore files found or they were empty/unreadable

    try:
        # Use 'gitwildmatch' factory for standard .gitignore pattern syntax
        return pathspec.PathSpec.from_lines('gitwildmatch', spec_lines)
    except Exception as e:
        print(f"Warning: Could not parse combined ignore rules in {directory}: {e}")
        return None


def get_ignore_matcher(repo_root: Path, ignore_filenames: List[str]) -> Callable[[Path], bool]:
    """
    Creates a function that checks if an absolute file path is ignored based on
    hierarchical ignore files (.gitignore, .aiignore, etc.).

    Logic mimics Git's behavior:
    1. Checks ignore files from the file's directory up to the repo root.
    2. Rules in deeper directories override rules in parent directories for the
       same file path patterns. Pathspec handles negation (`!`) within a single file.
    3. Ignoring a directory ignores all its contents.
    4. The `.git` directory is always ignored.

    Returns:
        A function `is_ignored(absolute_path)` -> bool.
    """
    repo_root = repo_root.resolve()
    # Cache compiled PathSpec objects per directory to avoid re-parsing
    specs_cache: Dict[Path, Optional[pathspec.PathSpec]] = {}

    def is_ignored(filepath: Path) -> bool:
        """Checks if the absolute path should be ignored."""
        filepath = filepath.resolve()

        # Check 1: Always ignore files inside the .git directory
        try:
            relative_to_repo = filepath.relative_to(repo_root)
            # Check if the first part of the relative path is '.git'
            if relative_to_repo.parts and relative_to_repo.parts[0] == '.git':
                return True
        except ValueError:
            # File path is not inside the repo root? Should not happen via rglob normally.
            print(f"Warning: Path {filepath} seems outside repo root {repo_root}")
            return True  # Treat paths outside the root as ignored

        # Check 2: Walk up the directory tree applying ignore files
        # The decision is based on the *last* applicable rule encountered during the
        # walk up (from file's dir -> root), simulating Git's precedence.
        ignored_decision = False  # Default state: not ignored
        current_dir = filepath.parent

        while current_dir >= repo_root:
            # Load spec for this directory level if not already cached
            if current_dir not in specs_cache:
                specs_cache[current_dir] = load_specs_for_directory(current_dir, ignore_filenames)

            spec = specs_cache.get(current_dir)

            if spec:  # If an ignore spec exists for this directory level
                try:
                    # Pathspec needs the path relative to the directory containing the spec file
                    relative_path_to_spec_dir = filepath.relative_to(current_dir)
                    # pathspec requires POSIX-style paths for matching
                    path_to_match = str(relative_path_to_spec_dir).replace(os.path.sep, '/')

                    # We need to check if the file itself OR any of its parent directories
                    # (relative to the current spec file location) are matched by the spec.
                    path_parts = Path(path_to_match).parts
                    current_check_path = ""
                    match_found_at_this_level = False
                    # Iterate through path segments (e.g., 'src', 'src/app', 'src/app/main.py')
                    for i, part in enumerate(path_parts):
                        current_check_path += part
                        is_last_part = (i == len(path_parts) - 1)
                        # Add trailing slash for directories, important for some gitignore rules
                        match_path = current_check_path + ('/' if not is_last_part else '')

                        if spec.match_file(match_path):
                            # A rule in this spec file matches this path segment.
                            # Pathspec handles negation (`!`) within this file internally.
                            # Because we walk up, this match is from the deepest relevant spec file found so far.
                            ignored_decision = True  # Tentatively ignore based on this level's rule
                            match_found_at_this_level = True
                            # print(f"Debug: Match found in {current_dir} for '{match_path}'. Decision -> Ignored")
                            break  # No need to check further path segments for *this* spec file

                        # Add separator for the next part if not the last part
                        if not is_last_part:
                            current_check_path += '/'

                    if match_found_at_this_level:
                        # A match (ignore or re-include via `!`) occurred at this level.
                        # This level's decision takes precedence over parent levels for this pattern.
                        return ignored_decision  # Return the decision from this level immediately

                except ValueError:
                    # Path is outside the current directory being checked? Should not happen.
                    pass

            # Stop if we've reached the repository root directory
            if current_dir == repo_root:
                break
            # Move up to the parent directory for the next iteration
            current_dir = current_dir.parent

        # If loop completes without any matching rule found in any spec file
        return ignored_decision

    return is_ignored


# ------------------------------------------------------------------------------
# File Type and Content Handling
# ------------------------------------------------------------------------------

# REMOVED looks_like_text function as it's no longer needed for Magika fallback
# def looks_like_text(filepath: Path, chunk_size: int) -> bool:
#     ...

# NEW function using file extensions
def get_file_type_and_hint_by_extension(filepath: Path) -> Tuple[Optional[str], bool]:
    """
    Determines if a file should be included based on its extension and provides
    a language hint for Markdown code blocks.

    Uses INCLUDED_EXTENSIONS, EXCLUDED_EXTENSIONS, and EXTENSION_TO_LANGUAGE_HINT
    from the configuration.

    Returns:
        Tuple: (language_hint or None, should_include_bool)
    """
    # Get the extension (e.g., '.py', '.txt', '')
    suffix = filepath.suffix.lower()

    # Handle files with no extension or just a dot (e.g., 'Makefile', '.bashrc')
    if not suffix or suffix == '.':
        # Treat files with common "no-extension" names as potentially includable text
        # You might want to expand this list or use a different heuristic
        no_ext_name = filepath.name.lower()
        if no_ext_name in {"makefile", "dockerfile", "readme", "license"} or \
                no_ext_name.startswith(('.', '_')):  # Include dotfiles/config files
            # print(f"Info: Including content of file with no/dot extension: {filepath.name}")
            # Use the filename itself as a hint, or provide a default like 'text'
            hint = EXTENSION_TO_LANGUAGE_HINT.get(no_ext_name, no_ext_name)
            return hint, True
        else:
            # Otherwise, exclude content of files without a recognized extension
            return None, False

    # Remove the leading dot for lookup (e.g., '.py' -> 'py')
    ext = suffix[1:]

    # Check exclusion list first
    if ext in EXCLUDED_EXTENSIONS:
        return None, False

    # Check inclusion list
    if ext in INCLUDED_EXTENSIONS:
        # Get language hint from mapping, defaulting to the extension itself if not found
        language_hint = EXTENSION_TO_LANGUAGE_HINT.get(ext, ext)
        return language_hint, True
    else:
        # Extension not in the included list
        return None, False


# def looks_like_text(filepath: Path, chunk_size: int) -> bool:
#     """
#     Performs a basic heuristic check to see if a file is likely text-based.
#     Reads a chunk and checks for null bytes or UTF-8 decoding errors.
#     """
#     try:
#         with filepath.open('rb') as f:
#             chunk = f.read(chunk_size)
#         # Check for null bytes - strong indicator of binary data
#         if b'\x00' in chunk:
#             return False
#         # Try decoding as UTF-8 - if it fails, likely not standard text
#         chunk.decode('utf-8')
#         return True # Decodes as UTF-8 and no null bytes found in chunk
#     except (UnicodeDecodeError, OSError):
#         # Decoding failed or OS error during read
#         return False
#     except Exception as e:
#         # Catch any other unexpected errors during the check
#         print(f"Warning: Error performing text check on file {filepath}: {e}")
#         return False

# def get_file_type_and_hint(filepath: Path, magika_instance: Magika) -> Tuple[Optional[str], bool]:
#     """
#     Uses Magika to identify the file's content type label. Determines if the file
#     should be included based on configured lists and performs a fallback text
#     check for 'unknown' types if enabled.
#
#     Returns:
#         Tuple: (detected_label or "text", should_include_bool)
#     """
#     try:
#         # Get Magika's prediction for the file path
#         result = magika_instance.identify_path(filepath)
#         ct_label = result.output.ct_label # e.g., 'python', 'markdown', 'jpeg', 'unknown'
#
#         # Decision logic:
#         if ct_label in EXCLUDED_MAGIKA_LABELS:
#             return ct_label, False # Explicitly excluded type
#
#         if ct_label in INCLUDED_MAGIKA_LABELS:
#             return ct_label, True # It's an explicitly included type
#
#         # Handle 'unknown' type based on configuration
#         if ct_label == "unknown" and HANDLE_UNKNOWN_AS_TEXT:
#             # Perform the fallback heuristic check
#             if looks_like_text(filepath, UNKNOWN_FILE_CHECK_CHUNK_SIZE):
#                  print(f"Info: Magika label 'unknown', but passed text check. Including: {filepath.name}")
#                  return "text", True # Use generic 'text' hint if it looks like text
#             else:
#                  # Failed the text check, treat as non-text/binary
#                  return ct_label, False
#
#         # If the type is not explicitly included, excluded, or handled as unknown-but-text
#         return ct_label, False # Exclude by default
#
#     except Exception as e:
#         print(f"Warning: Magika processing failed for {filepath}: {e}")
#         return None, False # Exclude if Magika fails

def find_longest_backtick_sequence(content: str) -> int:
    """Finds the length of the longest sequence of backticks (` ` `) in the content."""
    longest = 0
    # Regex to find sequences of 3 or more backticks
    matches = re.findall(r"`{3,}", content)
    for match in matches:
        longest = max(longest, len(match))
    return longest


# --- NEW FUNCTION FOR IPYNB CONVERSION ---
def convert_ipynb_to_python(filepath: Path) -> Optional[str]:
    """
    Reads a Jupyter Notebook and converts it to a simplified Python string.
    Code cells are preserved. Markdown cells are converted to comments.
    """
    try:
        with filepath.open('r', encoding='utf-8') as f:
            notebook_data = json.load(f)

        converted_lines = []
        converted_lines.append(f"# [NOTE] This is a converted Jupyter Notebook: {filepath.name}")
        converted_lines.append(f"# [NOTE] Markdown cells are commented out.\n")

        cells = notebook_data.get("cells", [])

        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "")
            source_lines = cell.get("source", [])

            # Handle if source is a string instead of list
            if isinstance(source_lines, str):
                source_lines = source_lines.splitlines(keepends=True)

            if not source_lines:
                continue

            converted_lines.append(f"\n# %% [{cell_type}] cell_id: {i}")

            if cell_type == "code":
                # Join lines and append
                code_block = "".join(source_lines)
                converted_lines.append(code_block)

            elif cell_type == "markdown":
                # Comment out markdown lines
                for line in source_lines:
                    # Use simple # commenting
                    converted_lines.append(f"# {line.rstrip()}")

            else:
                # Raw or other types, just comment them
                for line in source_lines:
                    converted_lines.append(f"# [Raw/Other] {line.rstrip()}")

        return "\n".join(converted_lines)

    except json.JSONDecodeError:
        print(f"Warning: Could not parse JSON in notebook {filepath}")
        return None
    except Exception as e:
        print(f"Warning: Error converting notebook {filepath}: {e}")
        return None


def read_file_content(filepath: Path) -> Optional[str]:
    """
    Reads file content, trying UTF-8 first, then falling back to Latin-1.
    If .ipynb, converts to Python script representation.
    Returns None if the file cannot be read or decoded.
    """
    # Handle Jupyter Notebooks specially
    if filepath.suffix.lower() == '.ipynb':
        return convert_ipynb_to_python(filepath)

    try:
        # Try reading as UTF-8 first, the most common encoding
        return filepath.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        try:
            # Fallback for files that might contain arbitrary bytes but are mostly text
            # Latin-1 maps byte values 0-255 directly to Unicode code points.
            # print(f"Info: File {filepath.name} not UTF-8, trying Latin-1 fallback for content.")
            return filepath.read_text(encoding='latin-1')
        except Exception:
            # If even Latin-1 fails, give up
            print(f"Warning: Skipping content of file {filepath} due to persistent decoding errors.")
            return None
    except OSError as e:
        # Handle OS-level errors like permission denied
        print(f"Warning: Could not read content of file {filepath} due to OS error: {e}")
        return None
    except Exception as e:
        # Catch any other unexpected errors during read
        print(f"Warning: Unexpected error reading content of file {filepath}: {e}")
        return None


# ------------------------------------------------------------------------------
# Tree Building
# ------------------------------------------------------------------------------

def build_tree_string(all_relative_paths: List[Path], repo_root: Path) -> str:  # <<< CORRECTED SIGNATURE
    """
    Generates a tree-like string representation of ALL provided file paths
    (which should be non-ignored files relative to the repository root).
    """
    # Use the list of all relative paths passed to the function
    paths_for_tree = all_relative_paths  # <<< USE THE PARAMETER

    if not paths_for_tree:
        return "(No files found in the repository after applying ignore rules)"

    # Use a nested dictionary to represent the file tree structure
    tree_dict = {}

    for rel_path in paths_for_tree:  # <<< ITERATE OVER THE PARAMETER
        parts = list(rel_path.parts)  # e.g., ['src', 'app', 'main.py']
        current_level = tree_dict  # Start at the root of our tree dict
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            # If this part (directory or file name) is not yet in the current level dict
            if part not in current_level:
                # Mark as 'file' if it's the last part of the path, else as an empty dict (directory)
                current_level[part] = 'file' if is_last else {}

            # If this isn't the last part, move into the subdirectory dict
            if not is_last:
                # Handle edge case: if a file exists with the same name as a directory prefix (e.g., 'a/b' file and 'a/b/c' dir)
                # Ensure the node is treated as a directory if we need to descend into it.
                if current_level[part] == 'file':
                    current_level[part] = {}  # Promote/overwrite to directory representation
                current_level = current_level[part]  # Move deeper into the tree dict

    lines = ["."]  # Start the tree output with the root directory symbol

    # Recursive function to format the tree levels with connectors
    def format_level(level_dict, prefix=""):
        # Sort items alphabetically for a consistent tree structure
        items = sorted(level_dict.items())
        for i, (name, item) in enumerate(items):
            # Determine the connector ('├── ' or '└── ') based on position
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{name}")
            # If the item is a dictionary, it represents a directory; recurse
            if isinstance(item, dict):
                # Calculate the prefix for the next level's indentation
                new_prefix = prefix + ("    " if i == len(items) - 1 else "│   ")
                format_level(item, new_prefix)

    # Start the recursive formatting from the top level of the tree dict
    format_level(tree_dict)
    # Join all generated lines into a single string
    return "\n".join(lines)


# ==============================================================================
# Main Logic
# ==============================================================================

def generate_repo_prompt(repo_path: Path) -> Tuple[str, List[FileData], int]:
    """
    Generates the main LLM prompt by scanning the repository.
    - The directory tree shows ALL non-ignored files.
    - The file content section includes only filtered text files (type, size, etc.).

    Returns:
        Tuple containing:
            - The final prompt string.
            - A list of FileData objects for files whose CONTENT is included.
            - The total estimated 'token' count (regex chunks) for the prompt.
    """
    # --- Initialization ---
    if not repo_path.is_dir():
        raise ValueError(f"Repository path not found or is not a directory: {repo_path}")

    repo_path = repo_path.resolve()

    print(f"Scanning repository: {repo_path}")
    print(f"Using ignore files: {IGNORE_FILENAMES}")
    print(f"Including extensions for CONTENT: {', '.join(sorted(list(INCLUDED_EXTENSIONS)))}")
    print(f"Excluding extensions for CONTENT: {', '.join(sorted(list(EXCLUDED_EXTENSIONS)))}")
    print(f"Max estimated 'tokens' per file for CONTENT: {MAX_FILE_ESTIMATED_TOKENS}")

    # Get the function that checks if a path is ignored
    ignore_checker = get_ignore_matcher(repo_path, IGNORE_FILENAMES)

    # List to store data for files whose CONTENT passes all filters
    included_files_data: List[FileData] = []
    # List to store relative paths of ALL non-ignored files for the TREE
    all_scanned_files_relative_paths: List[Path] = []
    skipped_for_content_count = 0  # Tracks files skipped specifically for content inclusion filters
    ignored_or_non_file_count = 0  # Tracks items skipped by initial ignore/type checks

    # --- File Discovery and Filtering ---
    print("Walking directory, filtering files for tree and content...")
    # Use Path.rglob to recursively find all files and directories
    for item in repo_path.rglob('*'):
        abs_path = item.resolve()

        # --- Filters applied to BOTH Tree and Content ---

        # Filter 1: Ignore based on rules (.gitignore, .aiignore, .git dir)
        if ignore_checker(abs_path):
            ignored_or_non_file_count += 1
            continue

        # Filter 2: Ensure it's a file (not a directory, broken link, etc.)
        if not abs_path.is_file():
            ignored_or_non_file_count += 1
            continue  # Skip directories, links etc. for both tree and content lists

        # --- Add to list for TREE structure ---
        # If it passed ignore checks and is a file, add it for the tree view
        try:
            relative_path = abs_path.relative_to(repo_path)
            all_scanned_files_relative_paths.append(relative_path)
        except ValueError:
            # Should not happen if item is from rglob within repo_path
            print(f"Warning: Path {abs_path} could not be made relative to {repo_path}. Skipping for tree.")
            ignored_or_non_file_count += 1
            continue

        # --- Filters applied ONLY for CONTENT inclusion ---

        # Filter 3: Exclude the script file itself from content
        script_path = Path(__file__).resolve()
        if abs_path == script_path:
            skipped_for_content_count += 1
            continue  # Skip content processing

        # also skip the previous output file
        if abs_path.name == OUTPUT_FILENAME:
            skipped_for_content_count += 1
            continue  # Skip content processing

        # Filter 4: Exclude .gitkeep files from content
        if abs_path.name == '.gitkeep':
            skipped_for_content_count += 1
            continue  # Skip content processing

        # Filter 5: Use file extension check for content inclusion
        lang_hint, should_include_content = get_file_type_and_hint_by_extension(abs_path)
        if not should_include_content:
            skipped_for_content_count += 1
            continue  # Skip content processing

        # --- Processing for Files Passing CONTENT Filters ---

        # Read file content only if it might be included based on type
        content = read_file_content(abs_path)
        if content is None:
            # File could not be read or decoded
            skipped_for_content_count += 1
            continue  # Skip content processing

        # Filter 6: Check *estimated* token count against the limit for content
        estimated_token_count = estimate_tokens(content)
        if estimated_token_count > MAX_FILE_ESTIMATED_TOKENS:
            # print(f"Info: Skipping file CONTENT due to estimated token count ({estimated_token_count} > {MAX_FILE_ESTIMATED_TOKENS}): {relative_path}")
            skipped_for_content_count += 1
            continue  # Skip content processing

        # --- Add to list for CONTENT section ---
        # If all content checks pass, store file data for inclusion in the prompt body
        included_files_data.append(FileData(
            relative_path=relative_path,  # Use relative_path calculated earlier
            absolute_path=abs_path,
            estimated_tokens=estimated_token_count,
            language_hint=lang_hint or ""
        ))

    # --- Post-Scanning Summary ---
    print(f"Finished scanning.")
    print(f" - Found {len(all_scanned_files_relative_paths)} non-ignored files for the tree.")
    print(f" - Included content of {len(included_files_data)} files after filtering.")
    print(f" - Skipped {ignored_or_non_file_count} items due to ignore rules or not being files.")
    print(f" - Skipped content of {skipped_for_content_count} files due to type, name, or size filters.")

    # <<< ADD THIS DEBUG BLOCK >>>
    print("\n--- DEBUG: Inspecting included_files_data BEFORE processing ---")
    print(f"Total items in included_files_data: {len(included_files_data)}")
    temp_paths_for_debug = [str(fd.relative_path) for fd in included_files_data]
    temp_paths_for_debug.sort()  # Sort paths for easier duplicate spotting
    duplicates_found = False
    for i in range(len(temp_paths_for_debug) - 1):
        print(f"  - {temp_paths_for_debug[i]}")
        if temp_paths_for_debug[i] == temp_paths_for_debug[i + 1]:
            print(f"    ^ DUPLICATE DETECTED!")
            duplicates_found = True
    if temp_paths_for_debug:  # Print the last item if list wasn't empty
        print(f"  - {temp_paths_for_debug[-1]}")
    if not duplicates_found:
        print("(No duplicate paths found in included_files_data)")
    print("--- END DEBUG BLOCK ---\n")
    # <<< END DEBUG BLOCK >>>

    # --- Prompt Assembly ---
    # Sort included files (for content) by path for consistent prompt generation
    included_files_data.sort(key=lambda x: x.relative_path)
    # Sort all files (for tree) by path for consistent tree generation
    all_scanned_files_relative_paths.sort()

    # Build the repository tree string using ALL non-ignored file paths
    print("Building repository tree string...")
    tree_string = build_tree_string(all_scanned_files_relative_paths, repo_path)  # <<< PASS TREE LIST >>>

    # Process file contents (only for files in included_files_data)
    file_content_blocks = []
    total_file_content_est_tokens = 0
    total_wrapper_est_tokens = 0

    print("Processing file contents for prompt...")
    # Loop ONLY over the files selected for content inclusion
    for file_data in included_files_data:
        # Re-read content (could optimize by passing content in FileData if memory allows)
        content = read_file_content(file_data.absolute_path)
        if content is None: continue  # Should already be checked, but safeguard

        # Add this file's estimated content tokens to the total
        total_file_content_est_tokens += file_data.estimated_tokens

        # Determine backtick fence length (minimum 4, or 1 more than longest sequence)
        longest_ticks = find_longest_backtick_sequence(content)
        wrapper_len = max(4, longest_ticks + 1)
        wrapper_ticks = "`" * wrapper_len

        # Format paths consistently with forward slashes for readability
        rel_path_str = str(file_data.relative_path).replace(os.path.sep, '/')
        file_marker_start = f"--- File: {rel_path_str} ---"
        file_marker_end = f"--- End of File: {rel_path_str} ---"

        # Construct the text components added *around* the actual file content
        wrapper_text_start = (
            f"{file_marker_start}\n"
            f"{wrapper_ticks}{file_data.language_hint}\n"  # e.g., `````python
        )
        wrapper_text_end = (
            f"\n{wrapper_ticks}\n"  # Closing fence
            f"{file_marker_end}\n\n"  # End marker and blank line separator
        )

        # Estimate tokens for these wrapper parts
        total_wrapper_est_tokens += estimate_tokens(wrapper_text_start + wrapper_text_end)

        # Assemble the full block for this file: StartWrapper + Content + EndWrapper
        block = wrapper_text_start + content + wrapper_text_end
        # Add the fully constructed block to the list
        file_content_blocks.append(block.rstrip('\n'))  # Remove trailing newline from the very last block

    # Join all individual file blocks into one large string
    joined_file_contents = "\n".join(file_content_blocks)

    # --- Calculate Total Estimated Prompt Tokens ---
    print("Calculating total estimated prompt 'tokens' (regex chunks)...")
    # Estimate tokens for the static parts of the prompt
    base_est_tokens = estimate_tokens(PROMPT_HEADER)  # Estimate tokens for the header text
    # The template uses 4 backticks for the tree, add those plus newlines
    tree_wrapper_est_tokens = estimate_tokens("````\n\n````\n")
    tree_content_est_tokens = estimate_tokens(tree_string)

    # Total = Base Header + Tree Wrapper + Tree Content + File Wrappers + File Content
    total_prompt_est_tokens = (base_est_tokens +
                               tree_wrapper_est_tokens + tree_content_est_tokens +
                               total_wrapper_est_tokens +
                               total_file_content_est_tokens)

    # Assemble the final prompt string using the template and generated parts
    final_prompt = PROMPT_TEMPLATE.format(
        prompt_header=PROMPT_HEADER,
        repository_tree=tree_string,
        file_contents=joined_file_contents
    )

    return final_prompt, included_files_data, total_prompt_est_tokens


# ==============================================================================
# Execution Block
# ==============================================================================

if __name__ == "__main__":
    try:
        # --- Pre-checks ---
        # Ensure the specified repository path exists and is a directory
        if not REPO_PATH.is_dir():
            raise ValueError(f"Repository path not found or is not a directory: {REPO_PATH.resolve()}")

        # --- Generation ---
        # Call the main function to generate the prompt and get statistics
        final_prompt_text, included_files, total_est_tokens = generate_repo_prompt(REPO_PATH)

        # --- Output ---
        # Attempt to save the generated prompt to the specified output file
        try:
            with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
                f.write(final_prompt_text)
            print(f"\n✅ System prompt saved successfully to: {OUTPUT_FILENAME}")
        except Exception as e:
            print(f"\n❌ Error saving prompt to file {OUTPUT_FILENAME}: {e}")
            # Consider uncommenting below to dump to console if saving fails
            # print("\n--- Generated System Prompt (dumping to console due to save error) ---")
            # print(final_prompt_text)
            # print("--- End of Prompt ---")

        # Print summary statistics to the console
        print("\n--- Prompt Generation Summary ---")
        print(f"Total files included in prompt: {len(included_files)}")
        print(f"Total estimated 'tokens' (regex chunks): ~{total_est_tokens}")
        print("\nIncluded Files (path, estimated 'tokens'):")
        if included_files:
            # Sort by estimated token count (descending) for clarity in the summary
            for file_data in sorted(included_files, key=lambda x: x.estimated_tokens, reverse=True):
                # Display paths with forward slashes consistently
                path_str = str(file_data.relative_path).replace(os.path.sep, '/')
                print(f"  - {path_str} ({file_data.estimated_tokens} est. tokens)")
        else:
            print("  (No files were included based on the filtering criteria)")
        print("--- End of Summary ---")

    except ValueError as e:
        # Handle configuration errors (like bad repo path)
        print(f"Configuration Error: {e}")
    except Exception as e:
        # Catch any other unexpected errors during script execution
        print(f"\n❌ An unexpected error occurred during script execution: {e}")
        import traceback

        traceback.print_exc()  # Print detailed traceback for debugging
