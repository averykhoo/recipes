"""
Generates the site's service worker from `scripts/sw_template.js`.

Runs after Jekyll has built the site. It walks the built output, sorts what it finds
into the shell assets that are precached on install and the pages that are warmed in
the background, and stamps a build id into the template.

The build id is a hash of the built site's contents rather than a timestamp or a
commit sha, so rebuilding unchanged content produces a byte-identical service worker.
That matters: open pages reload themselves when the build id changes, and a build id
that churned on every deploy would reload readers for no reason.

Usage (from the repository root):

    python scripts/build_sw.py
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import List
from typing import Tuple

# --- Configuration ---

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = REPO_ROOT / 'scripts' / 'sw_template.js'
DEFAULT_SITE_DIR = REPO_ROOT / '.jekyll-build' / '_site'
SW_FILENAME = 'sw.js'

# Precached during install, so these must stay small and genuinely needed on every
# page. Everything else is cached lazily as it is requested.
SHELL_SUFFIXES = {'.css', '.js', '.mjs', '.json', '.woff', '.woff2', '.ttf', '.eot', '.ico'}

# Fetched in the background after activation, so the whole site stays available offline.
PAGE_SUFFIXES = {'.html'}

# A shell asset larger than this is left to runtime caching rather than blocking install.
MAX_SHELL_ASSET_BYTES = 2 * 1024 * 1024

# Never cached: build metadata and machine-readable output nothing renders from.
EXCLUDED_NAMES = {SW_FILENAME, 'sitemap.xml', 'robots.txt', 'feed.xml'}

# Source files have no business being served. Reaching the site means a helper folder
# was added without being listed under `exclude` in _config.yml, which is how
# scripts/*.py ended up readable at the site root.
UNPUBLISHABLE_SUFFIXES = {'.py', '.pyc', '.rb'}

PLACEHOLDER_BUILD_ID = '__BUILD_ID__'
PLACEHOLDER_SHELL = '__SHELL_ASSETS__'
PLACEHOLDER_PAGES = '__PAGES__'


# --- Helper Functions ---

def to_url_path(path: Path, site_dir: Path) -> str:
    """
    Converts a file inside the built site into a site-relative URL reference.

    The service worker resolves these against its own scope, which keeps the same
    output working on both the GitHub Pages subpath and a custom domain.

    Only the three characters that would change how a relative reference *parses* are
    escaped. Everything else is left raw on purpose, so that `new URL()` inside the
    worker normalises a manifest entry into character-for-character the same URL the
    browser requests for that file. Percent-encoding more than this breaks the match:
    a browser leaves an apostrophe alone, so a manifest saying `%27` would cache a page
    under a key that no page visit ever looks up.

    :param path: a file inside `site_dir`
    :param site_dir: root of the built site
    :return: a forward-slashed relative URL reference
    """
    relative = path.relative_to(site_dir).as_posix()

    # '%' first, so the escapes introduced below are not escaped again.
    for character, escape in (('%', '%25'), ('#', '%23'), ('?', '%3F')):
        relative = relative.replace(character, escape)

    return relative


def collect_assets(site_dir: Path) -> Tuple[List[str], List[str]]:
    """
    Sorts the built site into shell assets and pages.

    :param site_dir: root of the built site
    :return: (shell asset URLs, page URLs), each sorted for deterministic output
    """
    shell: List[str] = []
    pages: List[str] = []

    for path in sorted(site_dir.rglob('*')):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_NAMES:
            continue

        suffix = path.suffix.lower()
        if suffix in PAGE_SUFFIXES:
            pages.append(to_url_path(path, site_dir))
        elif suffix in SHELL_SUFFIXES:
            if path.stat().st_size > MAX_SHELL_ASSET_BYTES:
                print(f'Skipping oversized shell asset ({path.stat().st_size} bytes): {path.name}')
                continue
            shell.append(to_url_path(path, site_dir))

    return sorted(shell), sorted(pages)


def find_published_source_files(site_dir: Path) -> List[str]:
    """
    Finds source files that were copied into the built site.

    Reported rather than raised: an unwanted file in the output is worth shouting about
    in the build log, but it is not a reason to block a deploy of the recipes.

    :param site_dir: root of the built site
    :return: site-relative paths, sorted
    """
    return sorted(
        path.relative_to(site_dir).as_posix()
        for path in site_dir.rglob('*')
        if path.is_file() and path.suffix.lower() in UNPUBLISHABLE_SUFFIXES
    )


def compute_build_id(site_dir: Path) -> str:
    """
    Hashes the built site's contents.

    Both the path and the bytes of every file are folded in, so a rename counts as a
    change just as an edit does. The service worker itself is excluded, since it is
    the thing being stamped.

    :param site_dir: root of the built site
    :return: a short hex digest
    """
    digest = hashlib.sha256()

    for path in sorted(site_dir.rglob('*')):
        if not path.is_file() or path.name == SW_FILENAME:
            continue
        digest.update(path.relative_to(site_dir).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())

    return digest.hexdigest()[:16]


def render_service_worker(template: str, build_id: str, shell: List[str], pages: List[str]) -> str:
    """
    Substitutes the template placeholders.

    :param template: contents of `sw_template.js`
    :param build_id: value for `__BUILD_ID__`
    :param shell: asset URLs precached on install
    :param pages: page URLs warmed in the background
    :return: the finished service worker source
    :raises ValueError: if a placeholder is missing, or if any survives substitution
    """
    for placeholder in (PLACEHOLDER_BUILD_ID, PLACEHOLDER_SHELL, PLACEHOLDER_PAGES):
        if placeholder not in template:
            raise ValueError(f'Service worker template is missing the {placeholder} placeholder')

    rendered = template.replace(PLACEHOLDER_BUILD_ID, build_id)
    rendered = rendered.replace(PLACEHOLDER_SHELL, json.dumps(shell, indent=None))
    rendered = rendered.replace(PLACEHOLDER_PAGES, json.dumps(pages, indent=None))

    for placeholder in (PLACEHOLDER_BUILD_ID, PLACEHOLDER_SHELL, PLACEHOLDER_PAGES):
        if placeholder in rendered:
            raise ValueError(f'Placeholder {placeholder} survived substitution')

    return rendered


def build(site_dir: Path, template_path: Path) -> Path:
    """
    Generates `sw.js` inside the built site.

    :param site_dir: root of the built site
    :param template_path: path to `sw_template.js`
    :return: the path written
    :raises FileNotFoundError: if the site or template is missing
    """
    if not site_dir.is_dir():
        raise FileNotFoundError(f'Built site not found: {site_dir}')
    if not template_path.is_file():
        raise FileNotFoundError(f'Service worker template not found: {template_path}')

    shell, pages = collect_assets(site_dir)
    if not pages:
        raise ValueError(f'No pages found in {site_dir} -- refusing to ship an empty service worker')

    for stray in find_published_source_files(site_dir):
        print(f'WARNING: source file published to the site: {stray} (add its folder to `exclude` in _config.yml)')

    build_id = compute_build_id(site_dir)
    rendered = render_service_worker(template_path.read_text(encoding='utf-8'), build_id, shell, pages)

    output_path = site_dir / SW_FILENAME
    output_path.write_text(rendered, encoding='utf-8')

    print(f'Build id:      {build_id}')
    print(f'Shell assets:  {len(shell)} precached on install')
    print(f'Pages:         {len(pages)} warmed in the background')
    print(f'Wrote:         {output_path} ({output_path.stat().st_size} bytes)')

    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', type=Path, default=DEFAULT_SITE_DIR,
                        help='root of the built Jekyll site (default: %(default)s)')
    parser.add_argument('--template', type=Path, default=DEFAULT_TEMPLATE,
                        help='service worker template (default: %(default)s)')
    args = parser.parse_args()

    print('--- Generating service worker ---')
    build(site_dir=args.site_dir, template_path=args.template)
    print('Service worker generation complete.')
