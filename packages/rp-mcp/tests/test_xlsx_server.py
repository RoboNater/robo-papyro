"""The rp-xlsx tool surface, driven through an in-process MCP client."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rp_mcp.sandbox import Sandbox
from rp_mcp.server import build_xlsx_server
from rp_xlsx import get_data, get_index

READ_TOOLS = {
    "xlsx_index",
    "xlsx_data",
    "xlsx_cells",
    "xlsx_formulas",
    "xlsx_tables",
    "xlsx_names",
    "xlsx_comments",
    "xlsx_images",
    "xlsx_charts",
    "xlsx_properties",
    "xlsx_markdown",
    "xlsx_fidelity",
    "xlsx_list_templates",
}

WRITE_TOOLS = {
    "xlsx_create",
    "xlsx_set_cells",
    "xlsx_append_rows",
    "xlsx_replace_text",
    "xlsx_set_properties",
    "xlsx_fill_template",
    "xlsx_add_sheet",
    "xlsx_delete_sheets",
    "xlsx_rename_sheet",
    "xlsx_reorder_sheets",
}


@pytest.fixture
def server(read_sandbox: Sandbox):
    return build_xlsx_server(read_sandbox)


@pytest.fixture
def writable(write_sandbox: Sandbox):
    return build_xlsx_server(write_sandbox)


class TestSurface:
    def test_the_read_tools_are_always_registered(self, server, mcp):
        assert READ_TOOLS <= mcp.names(server)

    def test_the_write_tools_are_absent_without_a_write_root(self, server, mcp):
        assert not (WRITE_TOOLS & mcp.names(server))

    def test_the_write_tools_appear_with_a_write_root(self, writable, mcp):
        assert WRITE_TOOLS <= mcp.names(writable)

    def test_every_write_tool_requires_its_output(self, writable, mcp):
        for name in sorted(WRITE_TOOLS):
            assert "output" in mcp.schema(writable, name)["required"], name

    def test_the_sheets_spec_says_it_is_one_based(self, server, mcp):
        description = mcp.schema(server, "xlsx_data")["properties"]["sheets"]["description"]
        assert "1-based" in description

    def test_allow_lossy_is_on_every_write_tool(self, writable, mcp):
        """Section 6: rp-xlsx exposes ``allow_lossy`` on every write tool, not
        just edits of an existing workbook -- unlike its own CLI."""
        for name in sorted(WRITE_TOOLS - {"xlsx_create", "xlsx_fill_template"}):
            assert "allow_lossy" in mcp.schema(writable, name)["properties"], name


class TestReads:
    def test_index_reports_the_sheets(self, server, sample_xlsx: Path, mcp):
        result = mcp.structured(mcp.call(server, "xlsx_index", {"path": sample_xlsx.name}))
        assert result["sheet_count"] == 1
        assert result["sheets"][0]["name"] == "Data"

    def test_data_honours_the_sheets_spec(self, server, sample_xlsx: Path, mcp):
        result = mcp.structured(
            mcp.call(server, "xlsx_data", {"path": sample_xlsx.name, "sheets": "1"})
        )["result"]
        assert result[0]["rows"] == [["North", 12], ["South", 8]]

    def test_markdown_comes_back_as_a_string(self, server, sample_xlsx: Path, mcp):
        result = mcp.structured(mcp.call(server, "xlsx_markdown", {"path": sample_xlsx.name}))
        assert "Data" in result["result"]

    def test_comments_are_empty_on_a_sheet_without_any(self, server, sample_xlsx: Path, mcp):
        assert (
            mcp.structured(mcp.call(server, "xlsx_comments", {"path": sample_xlsx.name}))["result"]
            == []
        )

    def test_fidelity_reports_a_plain_workbook_as_clean(self, server, sample_xlsx: Path, mcp):
        result = mcp.structured(mcp.call(server, "xlsx_fidelity", {"path": sample_xlsx.name}))
        assert result["at_risk"] == []


class TestWrites:
    def test_create_writes_into_the_write_root(self, writable, outbox: Path, mcp):
        result = mcp.structured(
            mcp.call(
                writable,
                "xlsx_create",
                {
                    "output": "book.xlsx",
                    "sheets": [{"name": "A", "header": ["H"], "rows": [["x"]]}],
                },
            )
        )
        assert Path(result["output"]) == outbox.resolve() / "book.xlsx"
        assert get_index(outbox / "book.xlsx").sheet_count == 1

    def test_create_refuses_to_overwrite(self, writable, outbox: Path, mcp):
        (outbox / "book.xlsx").write_bytes(b"already here")
        result = mcp.call(writable, "xlsx_create", {"output": "book.xlsx"})
        assert mcp.error_type(result) == "OutputExistsError"

    def test_set_cells_writes_a_new_file_and_leaves_the_input_alone(
        self, writable, sample_xlsx: Path, outbox: Path, mcp
    ):
        before = sample_xlsx.read_bytes()
        mcp.structured(
            mcp.call(
                writable,
                "xlsx_set_cells",
                {
                    "path": sample_xlsx.name,
                    "updates": {"Data": {"B4": 99}},
                    "output": "edited.xlsx",
                },
            )
        )
        assert sample_xlsx.read_bytes() == before
        data = get_data(outbox / "edited.xlsx", header=True)
        assert data[0].rows[2][1] == 99

    def test_append_rows_reaches_the_sheet(self, writable, sample_xlsx: Path, outbox: Path, mcp):
        mcp.structured(
            mcp.call(
                writable,
                "xlsx_append_rows",
                {
                    "path": sample_xlsx.name,
                    "sheet": "Data",
                    "rows": [["East", 15]],
                    "output": "appended.xlsx",
                },
            )
        )
        data = get_data(outbox / "appended.xlsx", header=True)
        assert data[0].rows[-1] == ["East", 15]

    def test_add_rename_delete_sheet(self, writable, sample_xlsx: Path, outbox: Path, mcp):
        """Each step's input is the previous step's output, addressed by its
        absolute path -- a relative ``path`` always resolves against the
        server's first root (``docs``), never the write root."""
        added = mcp.structured(
            mcp.call(
                writable,
                "xlsx_add_sheet",
                {"path": sample_xlsx.name, "name": "New", "output": "a.xlsx"},
            )
        )
        assert "New" in added["sheets"]

        renamed = mcp.structured(
            mcp.call(
                writable,
                "xlsx_rename_sheet",
                {
                    "path": str(outbox / "a.xlsx"),
                    "old": "New",
                    "new": "Renamed",
                    "output": "b.xlsx",
                },
            )
        )
        assert "Renamed" in renamed["sheets"]

        deleted = mcp.structured(
            mcp.call(
                writable,
                "xlsx_delete_sheets",
                {"path": str(outbox / "b.xlsx"), "names": ["Renamed"], "output": "c.xlsx"},
            )
        )
        assert "Renamed" not in deleted["sheets"]

    def test_replace_text_reaches_the_cells(self, writable, sample_xlsx: Path, outbox: Path, mcp):
        result = mcp.structured(
            mcp.call(
                writable,
                "xlsx_replace_text",
                {
                    "path": sample_xlsx.name,
                    "replacements": {"North": "Northeast"},
                    "output": "edited.xlsx",
                },
            )
        )
        assert result["replacements"] == {"North": 1}
        data = get_data(outbox / "edited.xlsx", header=True)
        assert data[0].rows[0][0] == "Northeast"

    def test_fill_template_writes_the_context(
        self, writable, xlsx_template: Path, outbox: Path, mcp
    ):
        mcp.structured(
            mcp.call(
                writable,
                "xlsx_fill_template",
                {
                    "template_name": xlsx_template.name,
                    "context": {"client_name": "Acme", "start_date": "2024-01-01"},
                    "output": "filled.xlsx",
                },
            )
        )
        data = get_data(outbox / "filled.xlsx", header=False)
        text = "\n".join(str(cell) for row in data[0].rows for cell in row)
        assert "Acme" in text

    def test_ranged_extraction_accumulates_in_one_directory(
        self, writable, xlsx_with_images: Path, outbox: Path, mcp
    ):
        first = mcp.structured(
            mcp.call(
                writable,
                "xlsx_images",
                {"path": xlsx_with_images.name, "sheets": "1-2", "output_dir": "shots"},
            )
        )["result"]
        early = {p.name: p.read_bytes() for p in (outbox / "shots").iterdir()}
        assert len(first) == len(early) == 2

        second = mcp.structured(
            mcp.call(
                writable,
                "xlsx_images",
                {"path": xlsx_with_images.name, "sheets": "3-4", "output_dir": "shots"},
            )
        )["result"]
        assert len(second) == 2

        after = {p.name: p.read_bytes() for p in (outbox / "shots").iterdir()}
        assert len(after) == 4, sorted(after)
        for name, blob in early.items():
            assert after[name] == blob
        assert [image["index"] for image in second] == [3, 4]

    def test_a_lossy_edit_is_refused_without_the_flag(
        self, writable, xlsx_at_risk: Path, outbox: Path, mcp
    ):
        result = mcp.call(
            writable,
            "xlsx_set_properties",
            {"path": xlsx_at_risk.name, "properties": {"title": "Q1"}, "output": "edited.xlsx"},
        )
        assert mcp.error_type(result) == "LossyEditError"

    def test_allow_lossy_on_set_properties_reports_what_was_dropped(
        self, writable, xlsx_at_risk: Path, outbox: Path, mcp
    ):
        """Section 6's contract, exercised on a non-cell write: `dropped` and
        `recalculation_required` must come from the source workbook, not be
        hard-coded, once `allow_lossy` lets the edit through."""
        result = mcp.structured(
            mcp.call(
                writable,
                "xlsx_set_properties",
                {
                    "path": xlsx_at_risk.name,
                    "properties": {"title": "Q1"},
                    "output": "edited.xlsx",
                    "allow_lossy": True,
                },
            )
        )
        assert result["dropped"]

    def test_allow_lossy_on_rename_sheet_reports_what_was_dropped(
        self, writable, xlsx_at_risk: Path, outbox: Path, mcp
    ):
        result = mcp.structured(
            mcp.call(
                writable,
                "xlsx_rename_sheet",
                {
                    "path": xlsx_at_risk.name,
                    "old": "Data",
                    "new": "Renamed",
                    "output": "renamed.xlsx",
                    "allow_lossy": True,
                },
            )
        )
        assert result["dropped"]

    def test_fill_template_cannot_reach_outside_the_roots(self, writable, tmp_path: Path, mcp):
        stray = tmp_path / "stray" / "book.xlsx"
        stray.parent.mkdir()
        shutil.copy(__file__, stray)
        result = mcp.call(
            writable,
            "xlsx_fill_template",
            {"template_name": str(stray), "context": {}, "output": "out.xlsx"},
        )
        assert mcp.error_type(result) == "PathNotAllowedError"
