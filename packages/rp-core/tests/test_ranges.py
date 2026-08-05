"""Generic range-spec parsing. Nothing here may know what a PDF page label is."""

import pytest

from rp_core.ranges import RangeSpecError, contiguous_runs, parse_range_spec


class TestParseRangeSpec:
    def test_all(self):
        assert parse_range_spec("all", 4) == [1, 2, 3, 4]

    def test_all_is_case_insensitive(self):
        assert parse_range_spec("ALL", 2) == [1, 2]

    def test_single(self):
        assert parse_range_spec("5", 10) == [5]

    def test_range(self):
        assert parse_range_spec("3-7", 10) == [3, 4, 5, 6, 7]

    def test_mixed_list(self):
        assert parse_range_spec("1,3-5,9", 10) == [1, 3, 4, 5, 9]

    def test_whitespace_tolerated(self):
        assert parse_range_spec(" 1 , 3 - 5 ", 10) == [1, 3, 4, 5]

    def test_sorted_and_deduplicated(self):
        assert parse_range_spec("9,1,3,1-3", 10) == [1, 2, 3, 9]

    def test_single_item_range(self):
        assert parse_range_spec("4-4", 10) == [4]

    def test_last_item(self):
        assert parse_range_spec("10", 10) == [10]


class TestParseRangeSpecErrors:
    def test_zero(self):
        with pytest.raises(RangeSpecError, match="1-10"):
            parse_range_spec("0", 10)

    def test_beyond_end(self):
        with pytest.raises(RangeSpecError, match="1-10"):
            parse_range_spec("11", 10)

    def test_range_beyond_end(self):
        with pytest.raises(RangeSpecError, match="1-10"):
            parse_range_spec("8-12", 10)

    def test_reversed_range(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("7-3", 10)

    def test_not_a_number(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("abc", 10)

    def test_empty_spec(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("", 10)

    def test_empty_list_item(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("1,,3", 10)

    def test_malformed_range(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("1-2-3", 10)


class TestOpenEndedRanges:
    """Spec section 4.3: an omitted endpoint takes the corresponding bound."""

    def test_omitted_start(self):
        assert parse_range_spec("-4", 10) == [1, 2, 3, 4]

    def test_omitted_end(self):
        assert parse_range_spec("7-", 10) == [7, 8, 9, 10]

    def test_omitted_end_at_the_last_item(self):
        assert parse_range_spec("10-", 10) == [10]

    def test_whitespace_tolerated(self):
        assert parse_range_spec(" - 4 , 9 - ", 10) == [1, 2, 3, 4, 9, 10]

    def test_mixed_with_closed_forms(self):
        assert parse_range_spec("-2,5,8-", 10) == [1, 2, 5, 8, 9, 10]

    def test_out_of_range_start_reports_the_bound_not_a_reversed_range(self):
        """ "7-" against a 5-item document is out of range, not backwards."""
        with pytest.raises(RangeSpecError, match="7 is out of range"):
            parse_range_spec("7-", 5)

    def test_out_of_range_end(self):
        with pytest.raises(RangeSpecError, match="12 is out of range"):
            parse_range_spec("-12", 10)

    def test_bare_hyphen_is_rejected(self):
        """It would mean 1..count, which "all" already says; far likelier a typo,
        and silently selecting everything is an expensive way to find out."""
        with pytest.raises(RangeSpecError, match="Ambiguous"):
            parse_range_spec("-", 10)

    def test_still_rejects_a_malformed_open_range(self):
        with pytest.raises(RangeSpecError):
            parse_range_spec("-4-6", 10)


class TestNoun:
    """``noun`` shapes error messages and nothing else, so each package's
    diagnostics read in its own vocabulary."""

    def test_default_noun(self):
        with pytest.raises(RangeSpecError, match="valid items are 1-10"):
            parse_range_spec("11", 10)

    def test_caller_supplied_noun(self):
        with pytest.raises(RangeSpecError, match="valid pages are 1-10"):
            parse_range_spec("11", 10, noun="page")

    def test_noun_does_not_change_parsing(self):
        assert parse_range_spec("1-3", 10, noun="slide") == parse_range_spec("1-3", 10)


class TestContiguousRuns:
    def test_empty(self):
        assert contiguous_runs([]) == []

    def test_single(self):
        assert contiguous_runs([4]) == [(4, 4)]

    def test_one_run(self):
        assert contiguous_runs([1, 2, 3]) == [(1, 3)]

    def test_gaps_split_runs(self):
        assert contiguous_runs([1, 2, 5, 7, 8, 9]) == [(1, 2), (5, 5), (7, 9)]
