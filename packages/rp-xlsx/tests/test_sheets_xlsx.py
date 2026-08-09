"""rp_xlsx.xlsx.sheets -- add, delete, rename, reorder.

Section 4's rules: the permutation check for reorder (rp-pptx's rule,
unchanged), the at-least-one-visible-sheet invariant (stricter than
openpyxl, which will happily write a workbook Excel refuses to open), and
sheet-name validation on the way in.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_xlsx.errors import LossyEditError
from rp_xlsx.models import SheetSpec
from rp_xlsx.xlsx import read, sheets, write


@pytest.fixture
def three_sheet_workbook(tmp_path):
    return write.create(
        tmp_path / "three.xlsx",
        sheets=[
            SheetSpec(name="One", rows=[["1"]]),
            SheetSpec(name="Two", rows=[["2"]]),
            SheetSpec(name="Three", rows=[["3"]]),
        ],
    )


class TestAddSheet:
    def test_appends_by_default(self, three_sheet_workbook, tmp_path):
        result = sheets.add_sheet(three_sheet_workbook, "Four", output=tmp_path / "out.xlsx")
        assert result.sheets == ["One", "Two", "Three", "Four"]

    def test_inserts_at_index(self, three_sheet_workbook, tmp_path):
        result = sheets.add_sheet(
            three_sheet_workbook, "Zero", index=1, output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["Zero", "One", "Two", "Three"]

    def test_index_out_of_range_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.add_sheet(three_sheet_workbook, "X", index=99, output=tmp_path / "out.xlsx")

    def test_duplicate_name_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.add_sheet(three_sheet_workbook, "One", output=tmp_path / "out.xlsx")

    def test_forbidden_character_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.add_sheet(three_sheet_workbook, "Bad[Name]", output=tmp_path / "out.xlsx")

    def test_over_31_characters_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.add_sheet(three_sheet_workbook, "x" * 32, output=tmp_path / "out.xlsx")

    def test_empty_name_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.add_sheet(three_sheet_workbook, "", output=tmp_path / "out.xlsx")


class TestDeleteSheets:
    def test_deletes_by_position(self, three_sheet_workbook, tmp_path):
        result = sheets.delete_sheets(
            three_sheet_workbook, sheets="2", output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["One", "Three"]

    def test_deletes_by_name(self, three_sheet_workbook, tmp_path):
        result = sheets.delete_sheets(
            three_sheet_workbook, names=["Two"], output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["One", "Three"]

    def test_neither_sheets_nor_names_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.delete_sheets(three_sheet_workbook, output=tmp_path / "out.xlsx")

    def test_both_sheets_and_names_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.delete_sheets(
                three_sheet_workbook, sheets="1", names=["Two"], output=tmp_path / "out.xlsx"
            )

    def test_deleting_every_visible_sheet_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.delete_sheets(three_sheet_workbook, sheets="all", output=tmp_path / "out.xlsx")

    def test_deleting_all_but_one_succeeds(self, three_sheet_workbook, tmp_path):
        result = sheets.delete_sheets(
            three_sheet_workbook, sheets="1-2", output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["Three"]


class TestRenameSheet:
    def test_renames(self, three_sheet_workbook, tmp_path):
        result = sheets.rename_sheet(
            three_sheet_workbook, "Two", "Renamed", output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["One", "Renamed", "Three"]

    def test_unknown_old_name_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.rename_sheet(three_sheet_workbook, "Nope", "New", output=tmp_path / "out.xlsx")

    def test_renaming_to_an_existing_name_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError):
            sheets.rename_sheet(three_sheet_workbook, "Two", "Three", output=tmp_path / "out.xlsx")

    def test_renaming_to_a_forbidden_character_is_an_input_error(
        self, three_sheet_workbook, tmp_path
    ):
        with pytest.raises(InputError):
            sheets.rename_sheet(
                three_sheet_workbook, "Two", "Bad:Name", output=tmp_path / "out.xlsx"
            )


class TestReorderSheets:
    def test_reorders(self, three_sheet_workbook, tmp_path):
        result = sheets.reorder_sheets(
            three_sheet_workbook, [3, 1, 2], output=tmp_path / "out.xlsx"
        )
        assert result.sheets == ["Three", "One", "Two"]

    def test_reorder_persists_through_a_reload(self, three_sheet_workbook, tmp_path):
        sheets.reorder_sheets(three_sheet_workbook, [3, 1, 2], output=tmp_path / "out.xlsx")
        idx = read.get_index(tmp_path / "out.xlsx")
        assert [s.name for s in idx.sheets] == ["Three", "One", "Two"]

    def test_missing_index_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError, match="missing"):
            sheets.reorder_sheets(three_sheet_workbook, [1, 2], output=tmp_path / "out.xlsx")

    def test_duplicated_index_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError, match="duplicated"):
            sheets.reorder_sheets(three_sheet_workbook, [1, 1, 2], output=tmp_path / "out.xlsx")

    def test_out_of_range_index_is_an_input_error(self, three_sheet_workbook, tmp_path):
        with pytest.raises(InputError, match="out of range"):
            sheets.reorder_sheets(three_sheet_workbook, [1, 2, 9], output=tmp_path / "out.xlsx")


class TestFidelityGuardIntegration:
    def test_add_sheet_refuses_on_at_risk_workbook(self, at_risk_workbook, tmp_path):
        with pytest.raises(LossyEditError):
            sheets.add_sheet(at_risk_workbook, "New", output=tmp_path / "out.xlsx")

    def test_allow_lossy_proceeds(self, at_risk_workbook, tmp_path):
        result = sheets.add_sheet(
            at_risk_workbook, "New", output=tmp_path / "out.xlsx", allow_lossy=True
        )
        assert "New" in result.sheets
