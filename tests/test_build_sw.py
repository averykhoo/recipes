"""Tests for the service worker generator in `scripts/build_sw.py`."""

import json
import re
from pathlib import Path

import pytest

from scripts.build_sw import PLACEHOLDER_BUILD_ID
from scripts.build_sw import PLACEHOLDER_PAGES
from scripts.build_sw import PLACEHOLDER_SHELL
from scripts.build_sw import build
from scripts.build_sw import collect_assets
from scripts.build_sw import compute_build_id
from scripts.build_sw import find_published_source_files
from scripts.build_sw import render_service_worker
from scripts.build_sw import to_url_path

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_TEMPLATE = REPO_ROOT / 'scripts' / 'sw_template.js'


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A miniature built site, shaped like the real Jekyll output."""
    root = tmp_path / '_site'
    (root / 'recipes' / 'sauces').mkdir(parents=True)
    (root / 'assets' / 'js').mkdir(parents=True)

    (root / 'index.html').write_text('<h1>Recipes</h1>', encoding='utf-8')
    (root / 'recipes' / 'index.html').write_text('<h1>All</h1>', encoding='utf-8')
    (root / 'recipes' / 'sauces' / 'sambal.html').write_text('<h1>Sambal</h1>', encoding='utf-8')
    (root / 'assets' / 'just-the-docs.css').write_text('body{}', encoding='utf-8')
    (root / 'assets' / 'js' / 'search-data.json').write_text('{}', encoding='utf-8')
    (root / 'favicon.ico').write_bytes(b'\x00')
    (root / 'cakebook.png').write_bytes(b'\x89PNG')
    return root


def read_array(rendered: str, variable: str) -> list:
    """Pulls a JSON array back out of the rendered service worker."""
    match = re.search(rf'^const {variable} = (\[.*?]);$', rendered, re.MULTILINE)
    assert match, f'{variable} not found in rendered service worker'
    return json.loads(match.group(1))


class TestCollectAssets:
    def test_pages_are_every_html_file(self, site):
        _, pages = collect_assets(site)
        assert pages == [
            'index.html',
            'recipes/index.html',
            'recipes/sauces/sambal.html',
        ]

    def test_shell_holds_css_js_json_and_icons(self, site):
        shell, _ = collect_assets(site)
        assert shell == [
            'assets/js/search-data.json',
            'assets/just-the-docs.css',
            'favicon.ico',
        ]

    def test_images_are_left_to_runtime_caching(self, site):
        shell, pages = collect_assets(site)
        assert not any('cakebook.png' in url for url in shell + pages)

    def test_the_service_worker_never_caches_itself(self, site):
        (site / 'sw.js').write_text('/* previous build */', encoding='utf-8')
        shell, pages = collect_assets(site)
        assert 'sw.js' not in shell + pages

    def test_oversized_shell_assets_are_skipped(self, site):
        (site / 'huge.js').write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        shell, _ = collect_assets(site)
        assert 'huge.js' not in shell

    def test_apostrophes_are_left_alone(self, site):
        """A browser does not escape `'`, so neither may the manifest.

        Escaping it would cache the page under a key no page visit looks up, which
        fails silently: online is fine, offline quietly 404s.
        """
        (site / "meema's-trifle.html").write_text('<h1>Trifle</h1>', encoding='utf-8')
        _, pages = collect_assets(site)
        assert "meema's-trifle.html" in pages

    def test_spaces_are_left_for_the_url_parser(self, site):
        """`new URL()` turns a raw space into %20, matching what the browser requests."""
        (site / 'a page with spaces.html').write_text('<h1>hi</h1>', encoding='utf-8')
        _, pages = collect_assets(site)
        assert 'a page with spaces.html' in pages

    @pytest.mark.parametrize('name, expected', [
        ('a#b.html', 'a%23b.html'),  # would otherwise parse as a fragment
        ('a?b.html', 'a%3Fb.html'),  # would otherwise parse as a query
        ('a%b.html', 'a%25b.html'),  # would otherwise parse as an escape
        ('a%20b.html', 'a%2520b.html'),  # already-escaped text is not double-decoded
        ("recipes/meema's.html", "recipes/meema's.html"),
    ])
    def test_reference_breaking_characters_are_escaped(self, tmp_path, name, expected):
        """Exercised on the pure function: Windows forbids `?` in a real filename."""
        assert to_url_path(tmp_path / name, tmp_path) == expected


class TestPublishedSourceFiles:
    def test_a_clean_site_reports_nothing(self, site):
        assert find_published_source_files(site) == []

    def test_python_helpers_left_in_the_output_are_reported(self, site):
        (site / 'scripts').mkdir()
        (site / 'scripts' / 'jekyll_prebuild.py').write_text('import re', encoding='utf-8')
        assert find_published_source_files(site) == ['scripts/jekyll_prebuild.py']

    def test_the_moon_widget_is_not_mistaken_for_a_stray(self, site):
        """`static/` is published on purpose, so its contents must not be flagged."""
        (site / 'static').mkdir()
        (site / 'static' / '3d-moon-widget.html').write_text('<canvas></canvas>', encoding='utf-8')

        assert find_published_source_files(site) == []
        _, pages = collect_assets(site)
        assert 'static/3d-moon-widget.html' in pages


class TestBuildId:
    def test_identical_content_produces_an_identical_id(self, site, tmp_path):
        copy = tmp_path / 'copy'
        copy.mkdir()
        for path in sorted(site.rglob('*')):
            target = copy / path.relative_to(site)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())

        assert compute_build_id(site) == compute_build_id(copy)

    def test_editing_a_page_changes_the_id(self, site):
        before = compute_build_id(site)
        (site / 'recipes' / 'sauces' / 'sambal.html').write_text('<h1>Sambal Bawang</h1>', encoding='utf-8')
        assert compute_build_id(site) != before

    def test_renaming_a_page_changes_the_id(self, site):
        before = compute_build_id(site)
        (site / 'recipes' / 'sauces' / 'sambal.html').rename(site / 'recipes' / 'sauces' / 'sambal-bawang.html')
        assert compute_build_id(site) != before

    def test_the_previous_service_worker_does_not_feed_the_id(self, site):
        before = compute_build_id(site)
        (site / 'sw.js').write_text('/* stamped by an earlier run */', encoding='utf-8')
        assert compute_build_id(site) == before


class TestRender:
    def test_every_placeholder_is_substituted(self):
        rendered = render_service_worker(REAL_TEMPLATE.read_text(encoding='utf-8'), 'abc123', ['a.css'], ['a.html'])
        for placeholder in (PLACEHOLDER_BUILD_ID, PLACEHOLDER_SHELL, PLACEHOLDER_PAGES):
            assert placeholder not in rendered

    def test_arrays_survive_as_valid_json(self):
        pages = ['index.html', 'a%20b.html']
        rendered = render_service_worker(REAL_TEMPLATE.read_text(encoding='utf-8'), 'abc123', ['x.css'], pages)
        assert read_array(rendered, 'PAGES') == pages
        assert read_array(rendered, 'SHELL_ASSETS') == ['x.css']

    def test_a_template_missing_a_placeholder_is_rejected(self):
        with pytest.raises(ValueError, match=PLACEHOLDER_PAGES):
            render_service_worker("const BUILD_ID = '__BUILD_ID__'; const S = __SHELL_ASSETS__;", 'x', [], [])


class TestBuild:
    def test_writes_a_service_worker_into_the_site(self, site):
        output = build(site_dir=site, template_path=REAL_TEMPLATE)
        assert output == site / 'sw.js'

        rendered = output.read_text(encoding='utf-8')
        assert read_array(rendered, 'PAGES') == ['index.html', 'recipes/index.html', 'recipes/sauces/sambal.html']
        assert "const BUILD_ID = '" in rendered

    def test_rebuilding_unchanged_content_is_byte_identical(self, site):
        first = build(site_dir=site, template_path=REAL_TEMPLATE).read_text(encoding='utf-8')
        second = build(site_dir=site, template_path=REAL_TEMPLATE).read_text(encoding='utf-8')
        assert first == second

    def test_changing_a_recipe_changes_the_shipped_build_id(self, site):
        first = build(site_dir=site, template_path=REAL_TEMPLATE).read_text(encoding='utf-8')
        (site / 'recipes' / 'sauces' / 'sambal.html').write_text('<h1>Now with garlic</h1>', encoding='utf-8')
        second = build(site_dir=site, template_path=REAL_TEMPLATE).read_text(encoding='utf-8')
        assert first != second

    def test_an_empty_site_is_refused(self, tmp_path):
        empty = tmp_path / 'empty'
        empty.mkdir()
        with pytest.raises(ValueError, match='No pages found'):
            build(site_dir=empty, template_path=REAL_TEMPLATE)

    def test_a_missing_site_is_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build(site_dir=tmp_path / 'nope', template_path=REAL_TEMPLATE)

    def test_a_missing_template_is_refused(self, site, tmp_path):
        with pytest.raises(FileNotFoundError):
            build(site_dir=site, template_path=tmp_path / 'nope.js')
