"""The rp-pptx tool surface, driven through an in-process MCP client.

Includes the one behaviour an agent meets that the other two servers have no
equivalent of: `pptx_comments` fails loudly on a deck with modern threaded
comments rather than reporting none.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from rp_mcp.sandbox import Sandbox
from rp_mcp.server import build_pptx_server
from rp_pptx import get_index, get_notes, get_text

READ_TOOLS = {
    "pptx_index",
    "pptx_text",
    "pptx_markdown",
    "pptx_tables",
    "pptx_images",
    "pptx_notes",
    "pptx_charts",
    "pptx_comments",
    "pptx_properties",
    "pptx_list_templates",
}

WRITE_TOOLS = {
    "pptx_create",
    "pptx_append_markdown",
    "pptx_replace_text",
    "pptx_fill_template",
    "pptx_set_notes",
    "pptx_set_properties",
    "pptx_delete_slides",
    "pptx_reorder_slides",
}


@pytest.fixture
def server(read_sandbox: Sandbox):
    return build_pptx_server(read_sandbox)


@pytest.fixture
def writable(write_sandbox: Sandbox):
    return build_pptx_server(write_sandbox)


@pytest.fixture
def threaded_deck(sample_pptx: Path, docs: Path) -> Path:
    """A deck carrying a modern threaded-comment part.

    Built by copying the generated deck and adding the part *and its content
    type*: rp-pptx detects modern comments by content type, never by filename,
    so a fixture that only added the file would not exercise the guard.
    """
    modern = docs / "threaded.pptx"
    with (
        zipfile.ZipFile(sample_pptx) as source,
        zipfile.ZipFile(modern, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"</Types>",
                    b'<Override PartName="/ppt/comments/modernComment_1.xml" '
                    b'ContentType="application/vnd.ms-powerpoint.comments+xml"/></Types>',
                )
            target.writestr(item, data)
        target.writestr("ppt/comments/modernComment_1.xml", "<cmLst/>")
    return modern


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

    def test_the_slide_spec_says_it_is_one_based(self, server, mcp):
        description = mcp.schema(server, "pptx_text")["properties"]["slides"]["description"]
        assert "1-based" in description


class TestReads:
    def test_index_reports_the_slides(self, server, sample_pptx: Path, mcp):
        result = mcp.structured(mcp.call(server, "pptx_index", {"path": sample_pptx.name}))
        assert result["slide_count"] == 3
        assert result["aspect_ratio"] == "16:9"

    def test_text_honours_the_slide_spec(self, server, sample_pptx: Path, mcp):
        slides = mcp.structured(
            mcp.call(server, "pptx_text", {"path": sample_pptx.name, "slides": "2"})
        )["result"]
        assert [slide["index"] for slide in slides] == [2]

    def test_markdown_comes_back_as_a_string(self, server, sample_pptx: Path, mcp):
        result = mcp.structured(mcp.call(server, "pptx_markdown", {"path": sample_pptx.name}))
        assert "Findings" in result["result"]

    def test_comments_are_empty_on_a_deck_without_any(self, server, sample_pptx: Path, mcp):
        assert (
            mcp.structured(mcp.call(server, "pptx_comments", {"path": sample_pptx.name}))["result"]
            == []
        )

    def test_modern_threaded_comments_fail_rather_than_report_none(
        self, server, threaded_deck: Path, mcp
    ):
        """rp-pptx spec section 7: unreadable is not the same answer as absent."""
        envelope = mcp.envelope(mcp.call(server, "pptx_comments", {"path": threaded_deck.name}))
        assert envelope["error"]["type"] == "UnsupportedFeatureError"
        assert envelope["error"]["exit_code"] == 3

    def test_index_stays_usable_on_such_a_deck(self, server, threaded_deck: Path, mcp):
        """`get_index` is total; it reports a null comment count instead of failing."""
        result = mcp.structured(mcp.call(server, "pptx_index", {"path": threaded_deck.name}))
        assert result["comment_count"] is None


class TestWrites:
    def test_create_writes_into_the_write_root(self, writable, outbox: Path, mcp):
        result = mcp.structured(
            mcp.call(
                writable,
                "pptx_create",
                {"output": "deck.pptx", "markdown": "# Title\n\n## One\n\n- a\n"},
            )
        )
        assert Path(result["output"]) == outbox.resolve() / "deck.pptx"
        assert get_index(outbox / "deck.pptx").slide_count == 2

    def test_create_refuses_to_overwrite(self, writable, outbox: Path, mcp):
        (outbox / "deck.pptx").write_bytes(b"already here")
        result = mcp.call(writable, "pptx_create", {"output": "deck.pptx", "markdown": "# X\n"})
        assert mcp.error_type(result) == "OutputExistsError"

    def test_set_notes_writes_a_new_file_and_leaves_the_input_alone(
        self, writable, sample_pptx: Path, outbox: Path, mcp
    ):
        before = sample_pptx.read_bytes()
        mcp.structured(
            mcp.call(
                writable,
                "pptx_set_notes",
                {
                    "path": sample_pptx.name,
                    "slide": 2,
                    "text": "Mention the revenue line.",
                    "output": "noted.pptx",
                },
            )
        )
        assert sample_pptx.read_bytes() == before
        notes = {note.slide_index: note.text for note in get_notes(outbox / "noted.pptx")}
        assert notes[2] == "Mention the revenue line."

    def test_delete_slides_reports_the_new_count(
        self, writable, sample_pptx: Path, outbox: Path, mcp
    ):
        result = mcp.structured(
            mcp.call(
                writable,
                "pptx_delete_slides",
                {"path": sample_pptx.name, "slides": "2", "output": "shorter.pptx"},
            )
        )
        assert result["slide_count"] == 2
        assert get_index(outbox / "shorter.pptx").slide_count == 2

    def test_reorder_slides_takes_a_permutation(
        self, writable, sample_pptx: Path, outbox: Path, mcp
    ):
        titles = [slide.title for slide in get_index(sample_pptx).titles]
        mcp.structured(
            mcp.call(
                writable,
                "pptx_reorder_slides",
                {"path": sample_pptx.name, "order": [3, 2, 1], "output": "flipped.pptx"},
            )
        )
        flipped = [slide.title for slide in get_index(outbox / "flipped.pptx").titles]
        assert flipped == list(reversed(titles))

    def test_replace_text_reaches_the_slides(self, writable, sample_pptx: Path, outbox: Path, mcp):
        result = mcp.structured(
            mcp.call(
                writable,
                "pptx_replace_text",
                {
                    "path": sample_pptx.name,
                    "replacements": {"Revenue rose": "Revenue held"},
                    "output": "edited.pptx",
                },
            )
        )
        assert result["replacements"] == {"Revenue rose": 1}
        body = "\n".join(
            paragraph.text
            for slide in get_text(outbox / "edited.pptx")
            for paragraph in slide.paragraphs
        )
        assert "Revenue held" in body

    def test_fill_template_cannot_reach_outside_the_roots(self, writable, tmp_path: Path, mcp):
        stray = tmp_path / "stray" / "deck.pptx"
        stray.parent.mkdir()
        shutil.copy(__file__, stray)
        result = mcp.call(
            writable,
            "pptx_fill_template",
            {"template_name": str(stray), "context": {}, "output": "out.pptx"},
        )
        assert mcp.error_type(result) == "PathNotAllowedError"
