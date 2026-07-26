"""Tests for quantity string -> float conversion."""

import pytest

from recipe_parser.utils.numeric import format_float_to_string
from recipe_parser.utils.numeric import parse_quantity_bounds
from recipe_parser.utils.numeric import parse_quantity_string
from recipe_parser.utils.numeric import parse_single_quantity


class TestScalars:
    @pytest.mark.parametrize("text, expected", [
        ("1", 1.0),
        ("12", 12.0),
        ("0", 0.0),
        ("2.5", 2.5),
        ("0.333", 0.333),
        ("  7  ", 7.0),
    ])
    def test_plain_numbers(self, text, expected):
        assert parse_single_quantity(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text, expected", [
        ("1/2", 0.5),
        ("3/4", 0.75),
        ("2/3", pytest.approx(2 / 3)),
        ("1 / 2", 0.5),  # whitespace around the solidus
    ])
    def test_ascii_fractions(self, text, expected):
        assert parse_single_quantity(text) == expected

    @pytest.mark.parametrize("text, expected", [
        ("1 1/2", 1.5),
        ("3 3/4", 3.75),
        ("2 1/3", pytest.approx(2 + 1 / 3)),
    ])
    def test_mixed_ascii_fractions(self, text, expected):
        assert parse_single_quantity(text) == expected

    @pytest.mark.parametrize("text, expected", [
        ("½", 0.5),
        ("¼", 0.25),
        ("¾", 0.75),
        ("⅓", pytest.approx(1 / 3)),
        ("1½", 1.5),
        ("2¼", 2.25),
    ])
    def test_vulgar_fractions(self, text, expected):
        assert parse_single_quantity(text) == expected

    def test_vulgar_fraction_with_space_before_it(self):
        """"1 1/2" is commonly typed as "1 ½" with a separating space."""
        assert parse_single_quantity("1 ½") == 1.5

    @pytest.mark.parametrize("text", ["", "   ", "abc", "many", "-", "/", "1/", "/2", "one"])
    def test_unparseable_returns_none(self, text):
        assert parse_single_quantity(text) is None


class TestRanges:
    @pytest.mark.parametrize("text, expected", [
        ("1-2", 1.5),
        ("2-3", 2.5),
        ("1 - 2", 1.5),
        ("1.5 - 2.5", 2.0),
        ("0.25-0.5", 0.375),
        ("70-140", 105.0),
    ])
    def test_hyphen_ranges_resolve_to_midpoint(self, text, expected):
        """Regression: the hyphen used to require surrounding whitespace."""
        assert parse_single_quantity(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text, expected", [
        ("200–300", 250.0),  # en-dash
        ("4–5", 4.5),  # en-dash
        ("1—2", 1.5),  # em-dash
    ])
    def test_unicode_dash_ranges(self, text, expected):
        assert parse_single_quantity(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text, expected", [
        ("1 to 2", 1.5),
        ("4 to 6", 5.0),
        ("0.333 to 0.5", pytest.approx((0.333 + 0.5) / 2)),
    ])
    def test_word_to_ranges(self, text, expected):
        assert parse_single_quantity(text) == expected

    def test_fraction_range(self):
        assert parse_single_quantity("1/2-1") == pytest.approx(0.75)

    def test_approximate_prefix_is_ignored(self):
        assert parse_single_quantity("~3") == 3.0
        assert parse_single_quantity("~1/2") == 0.5


class TestBounds:
    def test_scalar_has_equal_bounds(self):
        assert parse_quantity_bounds("5") == (5.0, 5.0)

    @pytest.mark.parametrize("text, low, high", [
        ("1-2", 1.0, 2.0),
        ("200–300", 200.0, 300.0),
        ("0.25-0.5", 0.25, 0.5),
        ("1 to 2", 1.0, 2.0),
    ])
    def test_range_preserves_endpoints(self, text, low, high):
        """The midpoint is lossy; bounds must survive for callers that need the spread."""
        assert parse_quantity_bounds(text) == (pytest.approx(low), pytest.approx(high))

    def test_bounds_are_ordered_even_if_written_backwards(self):
        assert parse_quantity_bounds("5-2") == (2.0, 5.0)

    def test_unparseable_returns_none(self):
        assert parse_quantity_bounds("not a number") is None


class TestFormatting:
    @pytest.mark.parametrize("value, expected", [
        (1.0, "1"),
        (2.5, "2.5"),
        (0.75, "0.75"),
        (10.0, "10"),
        (0.3333333, "0.333"),
    ])
    def test_format_float_to_string(self, value, expected):
        assert format_float_to_string(value) == expected

    @pytest.mark.parametrize("text, expected", [
        ("1 1/2", "1.5"),
        ("½", "0.5"),
        ("~2", "~2"),
        ("", ""),
    ])
    def test_parse_quantity_string(self, text, expected):
        assert parse_quantity_string(text) == expected

    def test_unparseable_quantity_string_is_returned_unchanged(self):
        assert parse_quantity_string("a handful") == "a handful"
