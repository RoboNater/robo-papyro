"""Page specs for PDFs: label resolution here, generic parsing in rp-core."""

import pytest

from rp_pdf.pages import PageSpecError, parse_page_labels, parse_pages

# physical pages 1-10: cover, FM1-FM3, i-iii, then content pages 1-3
LABELS = ["cover", "FM1", "FM2", "FM3", "i", "ii", "iii", "1", "2", "3"]
HYPHEN_LABELS = ["A-1", "A-2", "B-1"]


class TestParsePages:
    """A thin wrapper over rp_core.ranges — checked here only for the page
    vocabulary its errors keep, and to pin the delegation."""

    def test_delegates_to_the_generic_parser(self):
        assert parse_pages("1,3-5,9", 10) == [1, 3, 4, 5, 9]

    def test_all(self):
        assert parse_pages("all", 4) == [1, 2, 3, 4]

    def test_out_of_range_message_says_pages(self):
        with pytest.raises(PageSpecError, match="valid pages are 1-10"):
            parse_pages("11", 10)

    def test_malformed_message_says_page(self):
        with pytest.raises(PageSpecError, match="Invalid page number"):
            parse_pages("abc", 10)


class TestParsePageLabels:
    def test_all(self):
        assert parse_page_labels("all", LABELS) == list(range(1, 11))

    def test_single_label(self):
        assert parse_page_labels("FM2", LABELS) == [3]

    def test_numeric_label_resolves_to_labeled_page(self):
        assert parse_page_labels("1", LABELS) == [8]

    def test_roman_range(self):
        assert parse_page_labels("i-iii", LABELS) == [5, 6, 7]

    def test_decimal_range(self):
        assert parse_page_labels("1-3", LABELS) == [8, 9, 10]

    def test_range_across_schemes(self):
        assert parse_page_labels("FM3-ii", LABELS) == [4, 5, 6]

    def test_mixed_list(self):
        assert parse_page_labels("cover,FM2,2", LABELS) == [1, 3, 9]

    def test_case_insensitive_fallback(self):
        assert parse_page_labels("fm2", LABELS) == [3]

    def test_whitespace_tolerated(self):
        assert parse_page_labels(" cover , 1 - 2 ", LABELS) == [1, 8, 9]

    def test_exact_label_wins_over_range(self):
        assert parse_page_labels("A-1", HYPHEN_LABELS) == [1]

    def test_range_of_hyphenated_labels(self):
        assert parse_page_labels("A-1-B-1", HYPHEN_LABELS) == [1, 2, 3]

    def test_unknown_label(self):
        with pytest.raises(PageSpecError, match="No page labeled"):
            parse_page_labels("xyz", LABELS)

    def test_reversed_label_range(self):
        with pytest.raises(PageSpecError, match="Reversed"):
            parse_page_labels("iii-i", LABELS)

    def test_empty_spec(self):
        with pytest.raises(PageSpecError):
            parse_page_labels("", LABELS)

    def test_empty_list_item(self):
        with pytest.raises(PageSpecError):
            parse_page_labels("cover,,1", LABELS)


class TestOpenEndedLabelRanges:
    """The label equivalents of rp_core.ranges' open endpoints, so `--pages 7-`
    does not mean different things depending on whether the PDF has labels."""

    def test_omitted_start_runs_from_the_first_physical_page(self):
        assert parse_page_labels("-ii", LABELS) == [1, 2, 3, 4, 5, 6]

    def test_omitted_end_runs_to_the_last_physical_page(self):
        assert parse_page_labels("2-", LABELS) == [9, 10]

    def test_mixed_with_closed_forms(self):
        assert parse_page_labels("-FM1,i-ii,3-", LABELS) == [1, 2, 5, 6, 10]

    def test_exact_hyphenated_label_still_wins(self):
        """A document labeled "A-1" must keep addressing it, not read a trailing
        hyphen as an open range."""
        assert parse_page_labels("A-1", HYPHEN_LABELS) == [1]

    def test_open_ended_over_hyphenated_labels(self):
        assert parse_page_labels("A-2-", HYPHEN_LABELS) == [2, 3]

    def test_unknown_label_in_an_open_range(self):
        with pytest.raises(PageSpecError, match="No page labeled"):
            parse_page_labels("xyz-", LABELS)

    def test_bare_hyphen_is_rejected(self):
        with pytest.raises(PageSpecError, match="Ambiguous"):
            parse_page_labels("-", LABELS)
