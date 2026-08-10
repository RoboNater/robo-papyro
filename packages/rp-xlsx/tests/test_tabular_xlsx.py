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
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert {p.name for p in paths} == {"One.csv", "Two.csv"}

    def test_content_includes_header(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["Name", "Amount"], rows=[["a", 1]])],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        # Path.read_text() applies universal-newline translation, so \r\n on
        # disk (verified separately) normalizes to \n here -- this asserts
        # content, not line-ending bytes.
        assert paths[0].read_text() == "Name,Amount\na,1\n"

    def test_writes_carriage_return_line_feed_on_disk(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name="Data", header=["A"], rows=[["x"]])]
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert b"\r\n" in paths[0].read_bytes()

    def test_none_becomes_empty_field(self, tmp_path):
        # A header row is required: to_csv always reads with header=True, and
        # a sheet with only one row would have that single row read back as
        # the header (stringified) rather than as the data row under test.
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["A", "B"], rows=[["a", None]])],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv", sheets="1")
        assert paths[0].read_text() == "A,B\na,\n"

    def test_tab_delimiter_writes_tsv_extension(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["A", "B"], rows=[["a", "b"]])],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv", delimiter="\t")
        assert paths[0].suffix == ".tsv"
        assert "a\tb" in paths[0].read_text()

    def test_sheets_selector_restricts_output(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="One", rows=[["x"]]), SheetSpec(name="Two", rows=[["y"]])],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv", sheets="1")
        assert len(paths) == 1

    def test_datetime_is_isoformat(self, tmp_path):
        from datetime import datetime

        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[SheetSpec(name="Data", header=["When"], rows=[[datetime(2024, 5, 1, 12, 30)]])],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert "2024-05-01T12:30:00" in paths[0].read_text()

    def test_boolean_is_lowercase(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name="Data", header=["Flag"], rows=[[True]])]
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert paths[0].read_text().splitlines()[1] == "true"

    def test_a_sheet_name_with_windows_forbidden_characters_is_sanitized(self, tmp_path):
        """ "<", ">", '"', and "|" are all valid Excel sheet-name characters
        and all illegal in a Windows filename -- Excel's own forbidden set
        (": \\ / ? * [ ]") does not cover them."""
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name='Q1|Draft<2024>"', rows=[["x"]])]
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert len(paths) == 1
        for char in '<>:"|':
            assert char not in paths[0].name
        assert paths[0].is_file()

    def test_a_reserved_windows_device_name_gets_a_suffix(self, tmp_path):
        out = write.create(
            tmp_path / "src.xlsx", sheets=[SheetSpec(name="CON", rows=[["x"]])]
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert paths[0].stem.upper() != "CON"

    def test_sheets_that_sanitize_to_the_same_stem_stay_distinct_files(self, tmp_path):
        """Two sheets differing only in a character Windows forbids -- e.g.
        "Q1|A" and "Q1_A" -- would otherwise sanitize to the same filename
        and the second write would silently clobber the first."""
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[
                SheetSpec(name="Q1|A", header=["X"], rows=[["one"]]),
                SheetSpec(name="Q1_A", header=["X"], rows=[["two"]]),
            ],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert len(paths) == 2
        assert len({p.name for p in paths}) == 2
        contents = {p.read_text() for p in paths}
        assert any("one" in c for c in contents)
        assert any("two" in c for c in contents)

    def test_sheets_that_sanitize_to_a_case_only_collision_stay_distinct_files(self, tmp_path):
        """ "A<B" and "a_b" are distinct, valid Excel sheet names -- Excel's
        own case-insensitive uniqueness does not merge them, since "a<b" and
        "a_b" are different strings -- but both sanitize to stems that
        differ only in case ("A_B", "a_b"), which collide on any normal
        (case-insensitive) Windows or macOS filesystem."""
        out = write.create(
            tmp_path / "src.xlsx",
            sheets=[
                SheetSpec(name="A<B", header=["X"], rows=[["one"]]),
                SheetSpec(name="a_b", header=["X"], rows=[["two"]]),
            ],
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        assert len(paths) == 2
        assert len({p.name.casefold() for p in paths}) == 2
        contents = {p.read_text() for p in paths}
        assert any("one" in c for c in contents)
        assert any("two" in c for c in contents)


class TestSafeArtifactStems:
    def test_a_plain_name_is_unchanged(self):
        assert tabular.safe_artifact_stems(["Data"]) == {"Data": "Data"}

    def test_forbidden_characters_are_replaced(self):
        stems = tabular.safe_artifact_stems(['A<B>C:D"E/F\\G|H?I*J'])
        stem = next(iter(stems.values()))
        for char in '<>:"/\\|?*':
            assert char not in stem

    def test_a_reserved_device_name_gets_a_suffix(self):
        stems = tabular.safe_artifact_stems(["NUL"])
        assert next(iter(stems.values())).upper() != "NUL"

    def test_reserved_device_names_are_case_insensitive(self):
        stems = tabular.safe_artifact_stems(["con"])
        assert next(iter(stems.values())).upper() != "CON"

    def test_colliding_sanitized_names_get_distinct_suffixes(self):
        stems = tabular.safe_artifact_stems(["Q1|A", "Q1_A", "Q1?A"])
        assert len(set(stems.values())) == 3

    def test_the_first_occurrence_keeps_the_bare_stem(self):
        stems = tabular.safe_artifact_stems(["Report", "Report|2"])
        assert stems["Report"] == "Report"

    def test_trailing_dots_and_spaces_are_stripped(self):
        """Also forbidden by Windows -- a trailing dot or space in a
        filename is silently stripped by the OS itself, which is exactly
        the kind of surprise this function exists to avoid causing."""
        stems = tabular.safe_artifact_stems(["Report. "])
        assert next(iter(stems.values())) == "Report"

    def test_collisions_are_detected_case_insensitively(self):
        """Normal Windows and macOS filesystems are case-insensitive, so two
        sheets that sanitize to stems differing only in case -- "A<B" ->
        "A_B" and "a_b" (already safe) -- collide on disk even though they
        are distinct strings to a case-sensitive comparison."""
        stems = tabular.safe_artifact_stems(["A<B", "a_b"])
        assert len(set(s.casefold() for s in stems.values())) == 2

    def test_the_first_occurrence_keeps_its_casing_on_a_case_only_collision(self):
        stems = tabular.safe_artifact_stems(["A<B", "a_b"])
        assert stems["A<B"] == "A_B"

    def test_a_reserved_device_name_followed_by_an_extension_is_still_caught(self):
        """Windows reserves a device name up to the *first* dot, whatever
        follows it -- "CON.txt" is exactly as reserved as "CON", including
        when a caller appends its own extension on top ("CON.txt.csv")."""
        stems = tabular.safe_artifact_stems(["CON.txt"])
        stem = next(iter(stems.values()))
        base = stem.split(".")[0]
        assert base.upper() != "CON"

    def test_a_reserved_device_name_with_extension_keeps_the_extension(self):
        stems = tabular.safe_artifact_stems(["NUL.report"])
        stem = next(iter(stems.values()))
        assert stem.endswith(".report")


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
        ).output
        paths = tabular.to_csv(out, tmp_path / "csv")
        specs = tabular.from_csv(paths)
        rebuilt = write.create(tmp_path / "rebuilt.xlsx", sheets=specs).output
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
        out = write.create(tmp_path / "out.xlsx", sheets=specs).output
        data = read.get_data(out, sheets="1")
        assert data[0].header == ["Name", "Amount"]
        assert data[0].rows == [["a", 1], ["b", 2]]
