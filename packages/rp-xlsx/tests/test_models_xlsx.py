"""CellValue's union order is a correctness property, not a style choice.

Pydantic's coercion can turn ``True`` into ``1`` when a union puts a numeric
type before ``bool``; declaring ``bool`` first (models.py) is the fix, and
this is the test AGENTS.md and the spec both call for.
"""

from __future__ import annotations

from datetime import datetime

from rp_xlsx.models import Cell, SheetData


def _cell(value):
    return Cell(
        sheet="Sheet1",
        ref="A1",
        row=1,
        column=1,
        value=value,
        formula=None,
        value_available=True,
        number_format="General",
        is_date=False,
        is_merged_origin=False,
    )


class TestCellValueUnionOrder:
    def test_boolean_true_survives_as_bool(self):
        cell = _cell(True)
        assert cell.value is True
        assert cell.model_dump()["value"] is True

    def test_boolean_false_survives_as_bool(self):
        cell = _cell(False)
        assert cell.value is False
        assert cell.model_dump()["value"] is False

    def test_boolean_serializes_as_json_true_not_one(self):
        cell = _cell(True)
        assert cell.model_dump_json().count('"value":true') == 1

    def test_int_stays_int(self):
        cell = _cell(5)
        assert cell.value == 5
        assert type(cell.value) is int

    def test_float_stays_float(self):
        cell = _cell(0.25)
        assert cell.value == 0.25
        assert type(cell.value) is float

    def test_datetime_stays_datetime(self):
        when = datetime(2024, 5, 1, 12, 30)
        cell = _cell(when)
        assert cell.value == when

    def test_string_stays_string(self):
        cell = _cell("hello")
        assert cell.value == "hello"

    def test_none_stays_none(self):
        cell = _cell(None)
        assert cell.value is None

    def test_boolean_in_sheet_data_rows(self):
        data = SheetData(
            sheet="Sheet1", index=1, range="A1:A1", header=None, rows=[[True]], truncated=False
        )
        assert data.rows[0][0] is True
