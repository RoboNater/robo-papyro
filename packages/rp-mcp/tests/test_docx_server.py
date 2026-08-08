"""The rp-docx tool surface, driven through an in-process MCP client.

The write half is the interesting half: it is registered only with a write
root, it never edits in place, and it refuses an output that is already there.
Each of those is a claim `rp_mcp.docx`'s module docstring makes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rp_docx import get_index, get_text
from rp_mcp.sandbox import Sandbox
from rp_mcp.server import build_docx_server

READ_TOOLS = {
    "docx_index",
    "docx_text",
    "docx_markdown",
    "docx_tables",
    "docx_images",
    "docx_comments",
    "docx_tracked_changes",
    "docx_properties",
    "docx_find_placeholders",
    "docx_list_templates",
}

WRITE_TOOLS = {
    "docx_create",
    "docx_append_markdown",
    "docx_replace_text",
    "docx_fill_template",
    "docx_set_properties",
    "docx_accept_changes",
    "docx_reject_changes",
}


@pytest.fixture
def server(read_sandbox: Sandbox):
    return build_docx_server(read_sandbox)


@pytest.fixture
def writable(write_sandbox: Sandbox):
    return build_docx_server(write_sandbox)


class TestSurface:
    def test_the_read_tools_are_always_registered(self, server, mcp):
        assert READ_TOOLS <= mcp.names(server)

    def test_the_write_tools_are_absent_without_a_write_root(self, server, mcp):
        """Absent, not present-and-failing: the tool list is the capability list."""
        assert not (WRITE_TOOLS & mcp.names(server))

    def test_the_write_tools_appear_with_a_write_root(self, writable, mcp):
        assert WRITE_TOOLS <= mcp.names(writable)

    def test_no_write_tool_offers_an_in_place_option(self, writable, mcp):
        """There is no `--in-place` over MCP, so no tool may spell one."""
        for name in sorted(WRITE_TOOLS):
            properties = mcp.schema(writable, name)["properties"]
            assert "in_place" not in properties
            assert "output" in properties

    def test_every_write_tool_requires_its_output(self, writable, mcp):
        for name in sorted(WRITE_TOOLS):
            assert "output" in mcp.schema(writable, name)["required"], name


class TestReads:
    def test_index_summarizes_the_document(self, server, sample_docx: Path, mcp):
        result = mcp.structured(mcp.call(server, "docx_index", {"path": sample_docx.name}))
        assert result["table_count"] == 1
        assert [heading["text"] for heading in result["headings"]] == [
            "Quarterly Report",
            "Findings",
        ]

    def test_text_returns_paragraphs_with_styles(self, server, sample_docx: Path, mcp):
        paragraphs = mcp.structured(mcp.call(server, "docx_text", {"path": sample_docx.name}))[
            "result"
        ]
        assert any(p["text"] == "Quarterly Report" for p in paragraphs)

    def test_a_style_filter_narrows_the_result(self, server, sample_docx: Path, mcp):
        paragraphs = mcp.structured(
            mcp.call(server, "docx_text", {"path": sample_docx.name, "style_filter": "Heading 1"})
        )["result"]
        assert [p["text"] for p in paragraphs] == ["Quarterly Report"]

    def test_tables_come_back_as_rows_of_cells(self, server, sample_docx: Path, mcp):
        tables = mcp.structured(mcp.call(server, "docx_tables", {"path": sample_docx.name}))[
            "result"
        ]
        assert tables[0]["data"][0] == ["Region", "Total"]

    def test_markdown_is_returned_as_a_plain_string(self, server, sample_docx: Path, mcp):
        result = mcp.structured(mcp.call(server, "docx_markdown", {"path": sample_docx.name}))
        assert "Quarterly Report" in result["result"]

    def test_find_placeholders_lists_the_names(self, server, docx_template: Path, mcp):
        found = mcp.structured(
            mcp.call(server, "docx_find_placeholders", {"template_name": docx_template.name})
        )["result"]
        assert set(found) == {"client_name", "start_date"}

    def test_list_templates_needs_no_arguments(self, server, mcp):
        assert mcp.schema(server, "docx_list_templates").get("required", []) == []
        mcp.structured(mcp.call(server, "docx_list_templates"))


class TestWrites:
    def test_create_writes_into_the_write_root(self, writable, outbox: Path, mcp):
        result = mcp.structured(
            mcp.call(
                writable,
                "docx_create",
                {"output": "memo.docx", "markdown": "# Memo\n\nBody.\n"},
            )
        )
        written = Path(result["output"])
        assert written == outbox.resolve() / "memo.docx"
        assert get_index(written).paragraph_count >= 2

    def test_create_refuses_to_overwrite(self, writable, outbox: Path, mcp):
        (outbox / "memo.docx").write_text("already here", encoding="utf-8")
        result = mcp.call(writable, "docx_create", {"output": "memo.docx", "markdown": "# X\n"})
        assert mcp.error_type(result) == "OutputExistsError"

    def test_create_cannot_write_outside_the_write_root(self, writable, docs: Path, mcp):
        result = mcp.call(
            writable, "docx_create", {"output": str(docs / "memo.docx"), "markdown": "# X\n"}
        )
        assert mcp.error_type(result) == "PathNotAllowedError"

    def test_replace_text_leaves_the_input_untouched(
        self, writable, sample_docx: Path, outbox: Path, mcp
    ):
        """The suite never edits an input in place, and MCP has no way to ask."""
        before = sample_docx.read_bytes()
        result = mcp.structured(
            mcp.call(
                writable,
                "docx_replace_text",
                {
                    "path": sample_docx.name,
                    "replacements": {"Revenue rose": "Revenue held"},
                    "output": "edited.docx",
                },
            )
        )
        assert result["replacements"] == {"Revenue rose": 1}
        assert sample_docx.read_bytes() == before
        texts = [p.text for p in get_text(outbox / "edited.docx")]
        assert "Revenue held" in texts

    def test_append_markdown_writes_a_new_file(
        self, writable, sample_docx: Path, outbox: Path, mcp
    ):
        mcp.structured(
            mcp.call(
                writable,
                "docx_append_markdown",
                {"path": sample_docx.name, "markdown": "## Appendix\n", "output": "more.docx"},
            )
        )
        headings = [h.text for h in get_index(outbox / "more.docx").headings]
        assert "Appendix" in headings

    def test_fill_template_resolves_a_path_under_a_root(
        self, writable, docx_template: Path, outbox: Path, mcp
    ):
        result = mcp.structured(
            mcp.call(
                writable,
                "docx_fill_template",
                {
                    "template_name": docx_template.name,
                    "context": {"client_name": "Acme", "start_date": "2026-01-05"},
                    "output": "letter.docx",
                },
            )
        )
        assert result["unresolved"] == []
        assert "Acme" in "\n".join(p.text for p in get_text(outbox / "letter.docx"))

    def test_fill_template_cannot_reach_a_template_outside_the_roots(
        self, writable, outside: Path, mcp
    ):
        result = mcp.call(
            writable,
            "docx_fill_template",
            {"template_name": str(outside), "context": {}, "output": "letter.docx"},
        )
        assert mcp.error_type(result) == "PathNotAllowedError"

    def test_a_strict_fill_fails_on_a_missing_value(self, writable, docx_template: Path, mcp):
        result = mcp.call(
            writable,
            "docx_fill_template",
            {
                "template_name": docx_template.name,
                "context": {"client_name": "Acme"},
                "output": "letter.docx",
            },
        )
        assert result.is_error
        assert mcp.envelope(result)["error"]["exit_code"] == 1

    def test_set_properties_takes_the_leaf_s_own_model(
        self, writable, sample_docx: Path, outbox: Path, mcp
    ):
        mcp.structured(
            mcp.call(
                writable,
                "docx_set_properties",
                {
                    "path": sample_docx.name,
                    "properties": {"author": "R. Papyro"},
                    "output": "retitled.docx",
                },
            )
        )
        assert get_index(outbox / "retitled.docx").core_properties.author == "R. Papyro"
