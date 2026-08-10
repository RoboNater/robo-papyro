"""rp_xlsx.xlsx.tabular -- CSV/TSV both directions, JSON in, Markdown
tables in (spec section 4 and 9). Explicit delimiters, explicit encodings,
no sniffing.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_xlsx.models import SheetSpec
from rp_xlsx.xlsx import read, tabular, write


class TestToCsv:
    def test_writes_one_file_per_sheet(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[
                SheetSpec(name="One", header=["A"], rows=[["x"]]),
                SheetSpec(name="Two", header=["B"], rows=[["y"]]),
            ],
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert {p.name for p in paths} == {"One.csv", "Two.csv"}

    def test_content_includes_header(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["Name", "Amount"], rows=[["a", 1]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        # Path.read_text() applies universal-newline translation, so \r\n on
        # disk (verified separately) normalizes to \n here -- this asserts
        # content, not line-ending bytes.
        assert paths[0].read_text() == "Name,Amount\na,1\n"

    def test_writes_carriage_return_line_feed_on_disk(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name="Data", header=["A"], rows=[["x"]])]
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert b"\r\n" in paths[0].read_bytes()

    def test_none_becomes_empty_field(self, tmp_path):
        # A header row is required: to_csv always reads with header=True, and
        # a sheet with only one row would have that single row read back as
        # the header (stringified) rather than as the data row under test.
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["A", "B"], rows=[["a", None]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv", sheets="1")
        assert paths[0].read_text() == "A,B\na,\n"

    def test_tab_delimiter_writes_tsv_extension(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["A", "B"], rows=[["a", "b"]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv", delimiter="\t")
        assert paths[0].suffix == ".tsv"
        assert "a\tb" in paths[0].read_text()

    def test_sheets_selector_restricts_output(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="One", rows=[["x"]]), SheetSpec(name="Two", rows=[["y"]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv", sheets="1")
        assert len(paths) == 1

    def test_datetime_is_isoformat(self, tmp_path):
        from datetime import datetime

        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["When"], rows=[[datetime(2024, 5, 1, 12, 30)]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert "2024-05-01T12:30:00" in paths[0].read_text()

    def test_boolean_is_lowercase(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name="Data", header=["Flag"], rows=[[True]])]
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert paths[0].read_text().splitlines()[1] == "true"


class TestFromCsv:
    def test_reads_header_and_rows(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("Name,Amount\na,1\nb,2\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].name == "data"
        assert specs[0].header == ["Name", "Amount"]
        assert specs[0].rows == [["a", 1], ["b", 2]]

    def test_no_header_flag_treats_first_row_as_data(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("a,1\nb,2\n", encoding="utf-8")
        specs = tabular.from_csv([source], header=False)
        assert specs[0].header is None
        assert specs[0].rows == [["a", 1], ["b", 2]]

    def test_tsv_extension_infers_tab_delimiter(self, tmp_path):
        source = tmp_path / "data.tsv"
        source.write_text("a\tb\n1\t2\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].header == ["a", "b"]
        assert specs[0].rows == [[1, 2]]

    def test_explicit_delimiter_overrides_extension(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("a;b\n1;2\n", encoding="utf-8")
        specs = tabular.from_csv([source], delimiter=";")
        assert specs[0].header == ["a", "b"]

    def test_leading_zeros_stay_text(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("id\n007\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [["007"]]

    def test_plain_zero_becomes_int(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("n\n0\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [[0]]

    def test_float_parses(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("n\n2.5\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [[2.5]]

    def test_negative_int(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("n\n-5\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [[-5]]

    def test_empty_field_becomes_none(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("a,b\nx,\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [["x", None]]

    def test_true_false_text_stays_text_not_bool(self, tmp_path):
        source = tmp_path / "data.csv"
        source.write_text("flag\ntrue\n", encoding="utf-8")
        specs = tabular.from_csv([source])
        assert specs[0].rows == [["true"]]
        assert specs[0].rows[0][0] is not True

    def test_multiple_sources_produce_multiple_specs(self, tmp_path):
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("x\n1\n", encoding="utf-8")
        b.write_text("y\n2\n", encoding="utf-8")
        specs = tabular.from_csv([a, b])
        assert [s.name for s in specs] == ["a", "b"]

    def test_round_trip_via_to_csv(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["Name", "Amount"], rows=[["x", 5], ["y", 10]])],
        )
        paths = tabular.to_csv(out, tmp_path / "csv")
        specs = tabular.from_csv(paths)
        rebuilt = write.create(tmp_path / "rebuilt.xlsx", sheets=specs)
        data = read.get_data(rebuilt, sheets="1")
        assert data[0].header == ["Name", "Amount"]
        assert data[0].rows == [["x", 5], ["y", 10]]


class TestFromJson:
    def test_parses_a_json_string(self):
        specs = tabular.from_json('[{"name": "S", "header": ["A"], "rows": [[1], [2]]}]')
        assert specs[0].name == "S"
        assert specs[0].rows == [[1], [2]]

    def test_parses_a_json_file(self, tmp_path):
        source = tmp_path / "sheets.json"
        source.write_text('[{"name": "S", "rows": [["x"]]}]', encoding="utf-8")
        specs = tabular.from_json(source)
        assert specs[0].name == "S"

    def test_non_array_top_level_is_input_error(self):
        with pytest.raises(InputError):
            tabular.from_json('{"name": "S", "rows": []}')

    def test_invalid_json_is_input_error(self):
        with pytest.raises(InputError):
            tabular.from_json("not json at all {")

    def test_invalid_sheet_object_is_input_error(self):
        with pytest.raises(InputError):
            tabular.from_json('[{"rows": "not-a-list-of-lists"}]')

    def test_multiple_sheets(self):
        specs = tabular.from_json('[{"name": "A", "rows": []}, {"name": "B", "rows": []}]')
        assert [s.name for s in specs] == ["A", "B"]


class TestFromMarkdown:
    def test_table_uses_preceding_heading_as_sheet_name(self):
        text = """# Q1 Report

| Item | Amount |
| --- | --- |
| Widgets | 100 |
"""
        specs = tabular.from_markdown(text)
        assert specs[0].name == "Q1 Report"
        assert specs[0].header == ["Item", "Amount"]
        assert specs[0].rows == [["Widgets", 100]]

    def test_table_with_no_heading_gets_a_generated_name(self):
        text = "| A |\n| --- |\n| x |\n"
        specs = tabular.from_markdown(text)
        assert specs[0].name == "Sheet1"

    def test_multiple_tables_each_get_their_own_spec(self):
        text = """# One

| A |
| --- |
| 1 |

# Two

| B |
| --- |
| 2 |
"""
        specs = tabular.from_markdown(text)
        assert [s.name for s in specs] == ["One", "Two"]
        assert specs[0].rows == [[1]]
        assert specs[1].rows == [[2]]

    def test_no_tables_returns_empty_list(self):
        assert tabular.from_markdown("# Just a heading\n\nSome text.\n") == []

    def test_accepts_a_path(self, tmp_path):
        source = tmp_path / "report.md"
        source.write_text("# Sheet\n\n| A |\n| --- |\n| x |\n", encoding="utf-8")
        specs = tabular.from_markdown(source)
        assert specs[0].name == "Sheet"

    def test_round_trip_via_create(self, tmp_path):
        text = """# Report

| Name | Amount |
| --- | --- |
| a | 1 |
| b | 2 |
"""
        specs = tabular.from_markdown(text)
        out = write.create(tmp_path / "out.xlsx", sheets=specs)
        data = read.get_data(out, sheets="1")
        assert data[0].header == ["Name", "Amount"]
        assert data[0].rows == [["a", 1], ["b", 2]]
