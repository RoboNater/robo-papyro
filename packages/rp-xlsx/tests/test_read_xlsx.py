"""rp_xlsx.xlsx.read -- index, data, cells, formulas, tables, names, comments,
images, charts, properties, markdown.

Exercised primarily against `rich_workbook_path` (one workbook touching
every code path at once) plus targeted fixtures for section 9's footguns:
phantom dimensions, merged cells, dates, percentages, booleans, and a sheet
literally named "2".
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import pytest

from rp_core.errors import InputError
from rp_xlsx import ooxml
from rp_xlsx.xlsx import read


class TestProperties:
    def test_reports_creator_as_author(self, plain_workbook):
        props = read.get_properties(plain_workbook)
        assert props.author == "openpyxl"

    def test_missing_fields_are_none_not_empty_string(self, plain_workbook):
        props = read.get_properties(plain_workbook)
        assert props.title is None


class TestIndex:
    def test_it_counts_everything(self, rich_workbook_path):
        idx = read.get_index(rich_workbook_path)
        assert idx.sheet_count == 2
        data = idx.sheets[0]
        assert data.formula_count == 1
        assert data.merged_count == 1
        assert data.table_count == 1
        assert data.chart_count == 1
        assert data.image_count == 1
        assert data.comment_count == 1

    def test_hidden_sheet_state_is_reported(self, rich_workbook_path):
        idx = read.get_index(rich_workbook_path)
        assert idx.sheets[1].name == "2"
        assert idx.sheets[1].state == "hidden"

    def test_freeze_panes_and_autofilter(self, rich_workbook_path):
        idx = read.get_index(rich_workbook_path)
        assert idx.sheets[0].freeze_panes == "A2"
        assert idx.sheets[0].autofilter == "A1:C3"

    def test_defined_names_count_workbook_and_sheet_scoped(self, rich_workbook_path):
        idx = read.get_index(rich_workbook_path)
        assert idx.defined_name_count == 2

    def test_format_is_the_extension(self, rich_workbook_path):
        assert read.get_index(rich_workbook_path).format == "xlsx"

    def test_stays_total_on_a_workbook_with_at_risk_parts(self, at_risk_workbook):
        idx = read.get_index(at_risk_workbook)
        assert idx.at_risk
        assert idx.sheet_count == 1

    def test_reports_cached_values_present(self, cached_value_workbook):
        idx = read.get_index(cached_value_workbook)
        assert idx.has_cached_values is True

    def test_reports_no_cached_values_for_an_openpyxl_authored_formula(self, formula_workbook_path):
        idx = read.get_index(formula_workbook_path)
        assert idx.has_cached_values is False

    def test_reports_macros_present(self, macro_workbook):
        idx = read.get_index(macro_workbook)
        assert idx.has_macros is True

    def test_a_workbook_with_no_comments_reports_zero_not_null(self, plain_workbook):
        idx = read.get_index(plain_workbook)
        assert idx.sheets[0].comment_count == 0

    def test_empty_sheet_reports_none_used_range(self, empty_workbook):
        idx = read.get_index(empty_workbook)
        assert idx.sheets[0].used_range is None
        assert idx.sheets[0].rows == 0


class TestPhantomDimensions:
    """Spec section 9: declared dimensions lie; used_range must not."""

    def test_used_range_excludes_the_phantom_cell(self, phantom_dimension_workbook):
        idx = read.get_index(phantom_dimension_workbook)
        sheet = idx.sheets[0]
        assert sheet.used_range == "A1:A1"
        assert sheet.declared_range != sheet.used_range
        assert sheet.declared_range == "A1:E1000"

    def test_data_does_not_return_999_rows_of_nulls(self, phantom_dimension_workbook):
        data = read.get_data(phantom_dimension_workbook, sheets="1", header=False)
        assert len(data[0].rows) == 1

    def test_index_stays_fast_at_excels_actual_row_and_column_limits(
        self, adversarial_phantom_dimension_workbook
    ):
        """A used-range scan that walks the *declared* rectangle instead of
        the sheet's populated cells costs max_row * max_col cell
        constructions -- billions, at Excel's real limits. This must stay a
        function of how much data the sheet actually has, not of how large
        its phantom dimension claims to be. 5s is generous for "must not
        walk 17 billion phantom cells"; a correct scan of two real cells
        finishes in milliseconds."""
        import time

        start = time.monotonic()
        idx = read.get_index(adversarial_phantom_dimension_workbook)
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"get_index took {elapsed:.1f}s -- must not scan the declared rectangle"
        sheet = idx.sheets[0]
        assert sheet.used_range == "A1:A1"
        assert sheet.declared_range == "A1:XFD1048576"


class TestSelectors:
    def test_sheets_spec_and_sheet_name_select_differently(self, rich_workbook_path):
        """The disambiguation test spec section 4/11.2 requires: `sheets="2"`
        (position) and `names=["2"]` (the literal sheet name) differ."""
        by_position = read.get_data(rich_workbook_path, sheets="2", header=False)
        by_name = read.get_data(rich_workbook_path, names=["2"], header=False)
        assert by_position[0].sheet == "2"  # position 2 happens to be named "2"
        assert by_name[0].sheet == "2"
        # Both select the same sheet here (position 2 IS named "2"), so prove
        # the distinction on data instead: position 1 vs name "Data".
        by_pos1 = read.get_data(rich_workbook_path, sheets="1", header=False)
        by_name_data = read.get_data(rich_workbook_path, names=["Data"], header=False)
        assert by_pos1[0].sheet == by_name_data[0].sheet == "Data"

    def test_both_sheets_and_names_is_an_input_error(self, rich_workbook_path):
        with pytest.raises(InputError):
            read.get_data(rich_workbook_path, sheets="1", names=["Data"])

    def test_unknown_sheet_name_is_an_input_error(self, rich_workbook_path):
        with pytest.raises(InputError):
            read.get_data(rich_workbook_path, names=["Nope"])

    def test_default_selects_every_sheet(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path)
        assert [d.sheet for d in data] == ["Data", "2"]


class TestData:
    def test_values_not_display_strings(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", header=False)
        rows = data[0].rows
        # D2 is 0.25 formatted as a percentage -- the raw value comes back.
        assert 0.25 in rows[1]

    def test_header_defaults_to_first_row(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1")
        assert data[0].header[:3] == ["Name", "Amount", "Done"]

    def test_no_header_includes_the_first_row_as_data(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", header=False)
        assert data[0].header is None
        assert data[0].rows[0][:3] == ["Name", "Amount", "Done"]

    def test_max_rows_truncates(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", header=False, max_rows=2)
        assert len(data[0].rows) == 2
        assert data[0].truncated is True

    def test_no_truncation_when_max_rows_covers_everything(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", header=False, max_rows=100)
        assert data[0].truncated is False

    def test_cells_restricts_the_range(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", cells="A1:B1", header=False)
        assert data[0].range == "A1:B1"
        assert data[0].rows == [["Name", "Amount"]]

    def test_boolean_survives_as_bool(self, rich_workbook_path):
        # header=False, so rows[0] is row 1 (the header text itself as data);
        # rows[1]/rows[2] are the alpha/beta data rows.
        data = read.get_data(rich_workbook_path, sheets="1", header=False)
        assert data[0].rows[1][2] is True
        assert data[0].rows[2][2] is False

    def test_dates_are_always_datetime(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", header=False)
        e2 = data[0].rows[1][4]
        e3 = data[0].rows[2][4]
        assert isinstance(e2, datetime)
        assert isinstance(e3, datetime)
        assert e3 == datetime(2024, 5, 1, 0, 0)

    def test_cached_values_mode_merges_the_second_load(self, cached_value_workbook):
        data = read.get_data(cached_value_workbook, sheets="1", header=False, values="cached")
        assert data[0].rows[2][0] == 3

    def test_formulas_mode_reports_the_formula_text(self, cached_value_workbook):
        data = read.get_data(cached_value_workbook, sheets="1", header=False, values="formulas")
        assert data[0].rows[2][0] == "=SUM(A1:A2)"

    def test_merged_spanned_cell_reports_none(self, rich_workbook_path):
        data = read.get_data(rich_workbook_path, sheets="1", cells="A6:B6", header=False)
        assert data[0].rows == [["merged", None]]

    def test_empty_sheet_reports_empty_rows(self, empty_workbook):
        data = read.get_data(empty_workbook, sheets="1")
        assert data[0].rows == []
        assert data[0].header is None

    def test_progress_step_starts_before_the_file_is_opened(self, rich_workbook_path, monkeypatch):
        """AGENTS.md's warning, made concrete: a progress test that only
        checks the step fired eventually would not catch a reporter that
        starts too late to show a hang during the open itself. Asserting the
        order -- step entered, *then* the file opened -- is what catches it."""
        from rp_core.progress import Progress, Step

        events: list[str] = []

        class RecordingStep(Step):
            def advance(self, n: int = 1) -> None:
                events.append("advance")

            def set_total(self, total: int | None) -> None:
                events.append("set_total")

        class RecordingProgress(Progress):
            enabled = True

            @contextmanager
            def step(self, name: str, total: int | None = None):
                events.append("step_entered")
                yield RecordingStep()

        # check_readable() runs inside opened()'s generator body, so it only
        # fires at __enter__ time -- unlike patching opened() itself, which
        # would also catch the (harmless) construction of the not-yet-entered
        # context manager object and give a false negative on ordering.
        original_check_readable = ooxml.check_readable

        def _tracking_check_readable(*args, **kwargs):
            events.append("opened")
            return original_check_readable(*args, **kwargs)

        monkeypatch.setattr(read.ooxml, "check_readable", _tracking_check_readable)
        read.get_data(rich_workbook_path, progress=RecordingProgress())
        assert events[0] == "step_entered"
        assert "opened" in events
        assert events.index("step_entered") < events.index("opened")
        assert "advance" in events


class TestCells:
    def test_formula_cell_carries_both_formula_and_cached_value(self, cached_value_workbook):
        cells = {c.ref: c for c in read.get_cells(cached_value_workbook, sheets="1", empty=True)}
        assert cells["A3"].formula == "=SUM(A1:A2)"
        assert cells["A3"].value == 3
        assert cells["A3"].value_available is True

    def test_formula_with_no_cached_value_reports_unavailable(self, formula_workbook_path):
        cells = {c.ref: c for c in read.get_cells(formula_workbook_path, sheets="1", empty=True)}
        assert cells["A3"].value is None
        assert cells["A3"].value_available is False

    def test_empty_false_skips_empty_cells(self, rich_workbook_path):
        cells = read.get_cells(rich_workbook_path, sheets="1", cells="A1:A1", empty=False)
        assert len(cells) == 1
        cells_wide = read.get_cells(rich_workbook_path, sheets="1", cells="A10:A10", empty=False)
        assert cells_wide == []

    def test_empty_true_includes_empty_cells(self, rich_workbook_path):
        cells = read.get_cells(rich_workbook_path, sheets="1", cells="A10:A10", empty=True)
        assert len(cells) == 1
        assert cells[0].value is None

    def test_percentage_value_and_format(self, rich_workbook_path):
        cells = {c.ref: c for c in read.get_cells(rich_workbook_path, sheets="1", empty=True)}
        assert cells["D2"].value == 0.25
        assert cells["D2"].number_format == "0.00%"

    def test_merge_origin_is_marked(self, rich_workbook_path):
        cells = {
            c.ref: c
            for c in read.get_cells(rich_workbook_path, sheets="1", cells="A6:B6", empty=True)
        }
        assert cells["A6"].is_merged_origin is True
        assert cells["B6"].is_merged_origin is False
        assert cells["B6"].value is None

    def test_is_date_flag(self, rich_workbook_path):
        cells = {c.ref: c for c in read.get_cells(rich_workbook_path, sheets="1", empty=True)}
        assert cells["E2"].is_date is True
        assert cells["A1"].is_date is False


class TestFormulas:
    def test_only_formula_cells_are_returned(self, rich_workbook_path):
        formulas = read.get_formulas(rich_workbook_path, sheets="1")
        assert all(cell.formula is not None for cell in formulas)
        assert {cell.ref for cell in formulas} == {"B4"}


class TestTables:
    def test_table_is_read(self, rich_workbook_path):
        tables = read.get_tables(rich_workbook_path, sheets="1")
        assert len(tables) == 1
        table = tables[0]
        assert table.name == "DataTable"
        assert table.ref == "A1:C3"
        assert table.header_row is True
        assert table.totals_row is False
        assert table.style == "TableStyleMedium9"
        assert table.columns == ["Name", "Amount", "Done"]


class TestNames:
    def test_workbook_and_sheet_scoped_names(self, rich_workbook_path):
        names = read.get_names(rich_workbook_path)
        by_name = {n.name: n for n in names}
        assert by_name["Revenue"].scope is None
        assert by_name["LocalNote"].scope == "Data"


class TestComments:
    def test_classic_comment_is_read(self, rich_workbook_path):
        comments = read.get_comments(rich_workbook_path, sheets="1")
        assert len(comments) == 1
        assert comments[0].ref == "A1"
        assert comments[0].author == "Author"
        assert comments[0].text == "header note"


class TestImages:
    def test_image_is_read_with_dimensions(self, rich_workbook_path):
        images = read.get_images(rich_workbook_path, sheets="1")
        assert len(images) == 1
        image = images[0]
        assert image.width_px == 12
        assert image.height_px == 8
        assert image.content_type == "image/png"
        assert image.anchor == "F10"

    def test_extraction_writes_the_bytes(self, rich_workbook_path, tmp_path):
        out = tmp_path / "images"
        images = read.get_images(rich_workbook_path, sheets="1", output_dir=out)
        assert images[0].extracted_path.exists()
        assert images[0].extracted_path.stat().st_size > 0

    def test_nothing_extracted_without_output_dir(self, rich_workbook_path):
        images = read.get_images(rich_workbook_path, sheets="1")
        assert images[0].extracted_path is None

    def test_indices_count_across_the_workbook_not_the_selection(self, rich_workbook_path):
        all_images = read.get_images(rich_workbook_path)
        selected = read.get_images(rich_workbook_path, sheets="1")
        assert [i.index for i in all_images] == [i.index for i in selected]


class TestCharts:
    def test_chart_is_read(self, rich_workbook_path):
        charts = read.get_charts(rich_workbook_path, sheets="1")
        assert len(charts) == 1
        chart = charts[0]
        assert chart.chart_type == "BarChart"
        assert chart.title == "Amounts"
        assert chart.data_available is True
        assert chart.anchor == "F2"

    def test_series_reports_references_not_values(self, rich_workbook_path):
        chart = read.get_charts(rich_workbook_path, sheets="1")[0]
        series = chart.series[0]
        assert series.values_ref == "'Data'!$B$2:$B$3"
        assert series.categories_ref == "'Data'!$A$2:$A$3"


class TestMarkdown:
    def test_it_renders_a_heading_and_a_pipe_table(self, rich_workbook_path):
        markdown = read.get_markdown(rich_workbook_path, sheets="1")
        assert "## Data" in markdown
        assert "| Name | Amount | Done" in markdown

    def test_empty_sheet_reports_no_data(self, empty_workbook):
        markdown = read.get_markdown(empty_workbook)
        assert "no data" in markdown

    def test_multiple_sheets_get_separate_sections(self, rich_workbook_path):
        markdown = read.get_markdown(rich_workbook_path)
        assert "## Data" in markdown
        assert "## 2" in markdown
