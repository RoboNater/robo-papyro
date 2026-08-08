"""The rp-pdf tool surface, driven through an in-process MCP client.

These do not re-test extraction — rp-pdf's own suite does that. They test the
wiring: that a tool is registered under the name the documentation promises,
that its arguments reach the library with the meaning the CLI gives them, that
its result arrives as structured content, and that a failure arrives as an
envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rp_mcp.sandbox import Sandbox
from rp_mcp.server import build_pdf_server

READ_TOOLS = {
    "pdf_index",
    "pdf_text",
    "pdf_tables",
    "pdf_search",
    "pdf_markdown",
    "pdf_images",
}


@pytest.fixture
def server(read_sandbox: Sandbox):
    return build_pdf_server(read_sandbox)


class TestSurface:
    def test_the_documented_tools_are_registered(self, server, mcp):
        assert READ_TOOLS <= mcp.names(server)

    def test_the_sandbox_tool_is_present_on_every_server(self, server, mcp):
        assert "rp_sandbox" in mcp.names(server)

    def test_no_docx_or_pptx_tools_leak_into_the_pdf_server(self, server, mcp):
        assert not [name for name in mcp.names(server) if name.startswith(("docx_", "pptx_"))]

    def test_rp_pdf_has_no_write_tools_even_with_a_write_root(self, docs: Path, outbox: Path, mcp):
        """rp-pdf has no write surface at all, so a write root adds nothing."""
        writable = build_pdf_server(Sandbox([docs], write_root=outbox))
        assert mcp.names(writable) == mcp.names(build_pdf_server(Sandbox([docs])))

    def test_the_page_spec_argument_is_documented_for_the_agent(self, server, mcp):
        """A page spec an agent cannot guess is a page spec it will get wrong."""
        description = mcp.schema(server, "pdf_text")["properties"]["pages"]["description"]
        assert "3-7" in description and "page labels" in description

    def test_the_schema_is_generated_from_the_signature_through_the_guard(self, server, mcp):
        """`guarded` claims the wrapper does not hide the signature. This is that."""
        schema = mcp.schema(server, "pdf_search")
        assert schema["required"] == ["path", "query"]
        assert schema["properties"]["max_hits"]["default"] == 100


class TestReads:
    def test_index_reports_the_page_count(self, server, sample_pdf: Path, mcp):
        result = mcp.structured(mcp.call(server, "pdf_index", {"path": sample_pdf.name}))
        assert result["page_count"] == 3

    def test_an_absolute_path_inside_a_root_works_too(self, server, sample_pdf: Path, mcp):
        result = mcp.structured(mcp.call(server, "pdf_index", {"path": str(sample_pdf)}))
        assert result["page_count"] == 3

    @pytest.mark.requires_poppler
    def test_text_honours_the_page_spec(self, server, sample_pdf: Path, mcp):
        result = mcp.structured(
            mcp.call(server, "pdf_text", {"path": sample_pdf.name, "pages": "2"})
        )
        pages = result["result"]
        assert [page["physical_page"] for page in pages] == [2]
        assert "Beta" in pages[0]["text"]

    @pytest.mark.requires_poppler
    def test_search_reports_both_numbering_schemes(self, server, sample_pdf: Path, mcp):
        result = mcp.structured(
            mcp.call(server, "pdf_search", {"path": sample_pdf.name, "query": "Gamma"})
        )
        hits = result["result"]
        assert len(hits) == 1
        assert hits[0]["physical_page"] == 3
        assert "labeled_page" in hits[0]

    @pytest.mark.requires_poppler
    def test_markdown_returns_the_whole_result_not_just_a_string(
        self, server, sample_pdf: Path, mcp
    ):
        result = mcp.structured(mcp.call(server, "pdf_markdown", {"path": sample_pdf.name}))
        assert "Alpha page one" in result["markdown"]
        assert len(result["pages"]) == 3

    def test_images_report_metadata_without_a_write_root(self, server, sample_pdf: Path, mcp):
        result = mcp.structured(mcp.call(server, "pdf_images", {"path": sample_pdf.name}))
        assert result["result"] == []

    def test_the_sandbox_tool_reports_the_roots(self, server, docs: Path, mcp):
        result = mcp.structured(mcp.call(server, "rp_sandbox"))
        assert result["roots"] == [str(docs.resolve())]
        assert result["writable"] is False


class TestFailures:
    def test_a_path_outside_the_roots_is_refused(self, server, outside: Path, mcp):
        result = mcp.call(server, "pdf_index", {"path": str(outside)})
        envelope = mcp.envelope(result)
        assert envelope["error"]["type"] == "PathNotAllowedError"
        assert envelope["error"]["exit_code"] == 1

    def test_a_missing_file_inside_a_root_is_the_leaf_s_error(self, server, mcp):
        """The sandbox lets it through so rp-pdf can say what is actually wrong."""
        assert mcp.error_type(mcp.call(server, "pdf_index", {"path": "absent.pdf"})) == (
            "MissingFileError"
        )

    def test_a_corrupt_file_keeps_its_exit_code(self, server, docs: Path, mcp):
        (docs / "broken.pdf").write_text("not a pdf at all", encoding="utf-8")
        envelope = mcp.envelope(mcp.call(server, "pdf_index", {"path": "broken.pdf"}))
        assert envelope["error"]["exit_code"] == 3

    def test_a_bad_page_spec_is_an_input_error(self, server, sample_pdf: Path, mcp):
        envelope = mcp.envelope(
            mcp.call(server, "pdf_text", {"path": sample_pdf.name, "pages": "nonsense"})
        )
        assert envelope["error"]["exit_code"] == 1

    def test_extracting_images_needs_a_write_root(self, server, sample_pdf: Path, mcp):
        result = mcp.call(server, "pdf_images", {"path": sample_pdf.name, "output_dir": "images"})
        assert mcp.error_type(result) == "WritesNotEnabledError"

    def test_the_human_message_comes_before_the_envelope(self, server, outside: Path, mcp):
        """The ordering the CLIs use on stderr, kept here so one habit works for both."""
        lines = mcp.text(mcp.call(server, "pdf_index", {"path": str(outside)})).splitlines()
        assert len(lines) >= 2
        assert not lines[0].endswith("}")
        assert lines[-1].startswith("{")


class TestWithAWriteRoot:
    @pytest.fixture
    def server(self, write_sandbox: Sandbox):
        return build_pdf_server(write_sandbox)

    def test_images_can_be_extracted_into_the_write_root(
        self, server, sample_pdf: Path, outbox: Path, mcp
    ):
        result = mcp.call(server, "pdf_images", {"path": sample_pdf.name, "output_dir": "shots"})
        mcp.structured(result)
        assert (outbox / "shots").is_dir()

    def test_extraction_outside_the_write_root_is_refused(
        self, server, sample_pdf: Path, docs: Path, mcp
    ):
        result = mcp.call(
            server, "pdf_images", {"path": sample_pdf.name, "output_dir": str(docs / "shots")}
        )
        assert mcp.error_type(result) == "PathNotAllowedError"
