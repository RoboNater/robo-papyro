"""rp_xlsx.refs — A1 notation and sheet selection, pure functions.

Built and tested standalone before anything depends on it (spec section 12
step 4), the way rp-pptx built runs.py first.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_xlsx.errors import RefSpecError
from rp_xlsx.refs import (
    A1Range,
    CellPosition,
    column_index,
    column_letters,
    parse_a1_range,
    parse_cell_ref,
    resolve_sheet_selection,
    sheet_reference_matcher,
    validate_sheet_name,
)


class TestColumnConversion:
    @pytest.mark.parametrize(
        "letters,index",
        [("A", 1), ("Z", 26), ("AA", 27), ("AZ", 52), ("BA", 53), ("ZZ", 702), ("AAA", 703)],
    )
    def test_column_index(self, letters, index):
        assert column_index(letters) == index

    @pytest.mark.parametrize(
        "letters,index",
        [("A", 1), ("Z", 26), ("AA", 27), ("AZ", 52), ("BA", 53), ("ZZ", 702), ("AAA", 703)],
    )
    def test_column_letters(self, letters, index):
        assert column_letters(index) == letters

    def test_column_index_is_case_insensitive(self):
        assert column_index("aa") == column_index("AA")

    def test_round_trip_over_a_range(self):
        for index in range(1, 800):
            assert column_index(column_letters(index)) == index

    def test_invalid_column_letters(self):
        with pytest.raises(RefSpecError):
            column_index("1A")

    def test_empty_column_letters(self):
        with pytest.raises(RefSpecError):
            column_index("")

    def test_column_letters_rejects_zero(self):
        with pytest.raises(RefSpecError):
            column_letters(0)


class TestCellRef:
    def test_simple_ref(self):
        assert parse_cell_ref("B5") == CellPosition(row=5, column=2)

    def test_multi_letter_column(self):
        assert parse_cell_ref("AA1") == CellPosition(row=1, column=27)

    def test_ref_round_trips_through_property(self):
        pos = parse_cell_ref("C10")
        assert pos.ref == "C10"

    def test_lowercase_ref(self):
        assert parse_cell_ref("b5") == CellPosition(row=5, column=2)

    @pytest.mark.parametrize("bad", ["", "5B", "B", "5", "B0", "B-1", "1A1"])
    def test_malformed_ref_raises(self, bad):
        with pytest.raises(RefSpecError):
            parse_cell_ref(bad)

    def test_error_names_the_offending_token(self):
        with pytest.raises(RefSpecError, match="whoops"):
            parse_cell_ref("whoops")


class TestA1Range:
    def test_single_cell(self):
        assert parse_a1_range("A1") == A1Range(1, 1, 1, 1)

    def test_bounded_range(self):
        assert parse_a1_range("A1:D20") == A1Range(1, 1, 20, 4)

    def test_reversed_bounded_range_normalizes(self):
        assert parse_a1_range("D20:A1") == A1Range(1, 1, 20, 4)

    def test_whole_column(self):
        assert parse_a1_range("B:B") == A1Range(None, 2, None, 2)

    def test_whole_column_range(self):
        assert parse_a1_range("B:D") == A1Range(None, 2, None, 4)

    def test_whole_row(self):
        assert parse_a1_range("3:3") == A1Range(3, None, 3, None)

    def test_whole_row_range(self):
        assert parse_a1_range("3:7") == A1Range(3, None, 7, None)

    def test_empty_spec_raises(self):
        with pytest.raises(RefSpecError):
            parse_a1_range("")

    def test_missing_endpoint_raises(self):
        with pytest.raises(RefSpecError):
            parse_a1_range("A1:")

    def test_malformed_range_raises(self):
        with pytest.raises(RefSpecError):
            parse_a1_range("A1:!!")


class TestResolveSheetSelection:
    NAMES = ["Cover", "2024", "2", "Appendix"]

    def test_default_selects_all_in_order(self):
        assert resolve_sheet_selection(self.NAMES) == [1, 2, 3, 4]

    def test_sheets_spec_selects_by_position(self):
        assert resolve_sheet_selection(self.NAMES, sheets="2") == [2]

    def test_sheets_spec_range(self):
        assert resolve_sheet_selection(self.NAMES, sheets="1-2") == [1, 2]

    def test_names_selects_by_name(self):
        assert resolve_sheet_selection(self.NAMES, names=["Appendix"]) == [4]

    def test_sheet_literally_named_2_is_distinct_from_position_2(self):
        """The disambiguation test spec section 4 and section 11.2 require:
        `--sheets 2` and `--sheet "2"` must select different sheets."""
        by_position = resolve_sheet_selection(self.NAMES, sheets="2")
        by_name = resolve_sheet_selection(self.NAMES, names=["2"])
        assert by_position == [2]  # "2024"
        assert by_name == [3]  # the sheet literally named "2"
        assert by_position != by_name

    def test_names_are_sorted_by_position(self):
        assert resolve_sheet_selection(self.NAMES, names=["Appendix", "Cover"]) == [1, 4]

    def test_duplicate_names_deduplicate(self):
        assert resolve_sheet_selection(self.NAMES, names=["Cover", "Cover"]) == [1]

    def test_both_sheets_and_names_raises(self):
        with pytest.raises(InputError):
            resolve_sheet_selection(self.NAMES, sheets="1", names=["Cover"])

    def test_default_sheets_with_names_is_not_both(self):
        # sheets="all" is the default, so passing names alone must not trip
        # the "both" check.
        assert resolve_sheet_selection(self.NAMES, sheets="all", names=["Cover"]) == [1]

    def test_unknown_name_raises_and_lists_available(self):
        with pytest.raises(InputError, match="Cover"):
            resolve_sheet_selection(self.NAMES, names=["Nope"])

    def test_empty_names_list_falls_back_to_sheets(self):
        assert resolve_sheet_selection(self.NAMES, sheets="1", names=[]) == [1]


class TestValidateSheetName:
    def test_a_plain_name_is_fine(self):
        validate_sheet_name("Report")  # must not raise

    def test_empty_name_raises(self):
        with pytest.raises(InputError):
            validate_sheet_name("")

    def test_over_31_characters_raises(self):
        with pytest.raises(InputError):
            validate_sheet_name("x" * 32)

    def test_31_characters_is_fine(self):
        validate_sheet_name("x" * 31)  # must not raise

    @pytest.mark.parametrize("char", list(":\\/?*[]"))
    def test_forbidden_characters_raise(self, char):
        with pytest.raises(InputError):
            validate_sheet_name(f"Bad{char}Name")

    def test_an_exact_duplicate_raises(self):
        with pytest.raises(InputError):
            validate_sheet_name("Data", ["Data"])

    def test_case_only_difference_also_raises(self):
        """Verified against openpyxl 3.1.5: Excel treats sheet names as
        case-insensitive, and wb.create_sheet("data") next to an existing
        "Data" does not raise -- it silently renames the new sheet to
        "data1". This function must not repeat that silence."""
        with pytest.raises(InputError, match="Data"):
            validate_sheet_name("data", ["Data"])

    def test_a_distinct_name_is_fine(self):
        validate_sheet_name("New", ["Data", "Other"])  # must not raise


class TestSheetReferenceMatcher:
    def test_matches_the_bare_form(self):
        assert sheet_reference_matcher("Data")("=Data!A1")

    def test_matches_the_bare_form_case_insensitively(self):
        assert sheet_reference_matcher("Data")("=DATA!A1")

    def test_does_not_match_a_longer_name_sharing_a_prefix(self):
        assert not sheet_reference_matcher("Data")("=Data2!A1")

    def test_does_not_match_an_unrelated_sheet(self):
        assert not sheet_reference_matcher("Data")("=Other!B1")

    def test_matches_the_quoted_form(self):
        assert sheet_reference_matcher("My Sheet")("='My Sheet'!A1")

    def test_matches_the_quoted_form_with_a_doubled_apostrophe(self):
        """Excel escapes an internal `'` as `''` inside the quoted sheet
        name -- verified against a real workbook (`It's Data` renders as
        `'It''s Data'!A1`)."""
        assert sheet_reference_matcher("It's Data")("='It''s Data'!A1")

    def test_matches_inside_a_defined_name_attr_text(self):
        assert sheet_reference_matcher("Data")("'Data'!$A$1")

    def test_matches_the_second_endpoint_of_a_bare_3d_range(self):
        assert sheet_reference_matcher("Sheet3")("=SUM(Sheet1:Sheet3!A1)")

    def test_matches_the_first_endpoint_of_a_bare_3d_range(self):
        """A prior version only matched a name immediately before `!`,
        which caught the second endpoint of `Sheet1:Sheet3!A1` but missed
        the first -- verified as a real gap (renaming `Sheet1` proceeded
        undetected against exactly this formula)."""
        assert sheet_reference_matcher("Sheet1")("=SUM(Sheet1:Sheet3!A1)")

    def test_matches_either_endpoint_of_a_quoted_3d_range(self):
        """Excel wraps both endpoints of a quoted 3-D range in one pair of
        quotes -- verified against a real workbook: `'Sheet 1:Sheet 3'!A1`,
        not `'Sheet 1':'Sheet 3'!A1`."""
        text = "=SUM('Sheet 1:Sheet 3'!A1)"
        assert sheet_reference_matcher("Sheet 1")(text)
        assert sheet_reference_matcher("Sheet 3")(text)

    def test_does_not_match_an_unrelated_name_inside_a_3d_range(self):
        assert not sheet_reference_matcher("Sheet2")("=SUM(Sheet1:Sheet3!A1)")
