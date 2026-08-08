"""The rp-pptx tool surface.

Same shape as :mod:`rp_mcp.docx`: reads always, writes only with a write root,
and every write names a new output because there is no ``--in-place`` over MCP.

One rp-pptx behaviour is worth knowing before an agent meets it.
``pptx_comments`` **fails** on a deck carrying modern threaded comments rather
than returning an empty list, because rp-pptx cannot read that part yet and an
empty list is indistinguishable from "no comments" (rp-pptx spec section 7).
That surfaces here as a tool error with ``exit_code`` 3 in its envelope, which
is the right answer for the same reason it is on the CLI: a wrong empty result
is worse than a loud failure. ``pptx_index`` stays usable on such a deck and
reports ``comment_count: null``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from rp_mcp.sandbox import Sandbox
from rp_mcp.tools import (
    OutputArg,
    OutputDirArg,
    PathArg,
    SlidesArg,
    guarded,
    sandboxed_template,
)
from rp_pptx import templates as templates_module
from rp_pptx.models import (
    ChartRef,
    Comment,
    CoreProperties,
    EmbeddedImage,
    FillResult,
    PresentationIndex,
    ReplaceResult,
    SlideOpResult,
    SlideText,
    SpeakerNotes,
    Table,
    TemplateInfo,
    WriteResult,
)
from rp_pptx.pptx import read, write
from rp_pptx.pptx import slides as slides_module
from rp_pptx.pptx import template as template_module

MarkdownArg = Annotated[
    str,
    Field(
        description="Markdown source. A level-1 or level-2 heading starts a slide; "
        "bullets, pipe tables, and fenced code become slide content."
    ),
]

TemplateArg = Annotated[
    str | None,
    Field(
        description="Template to build on: a name from pptx_list_templates, or a path to a "
        "'.potx'/'.pptx' under an allowed root. Omit for the built-in default."
    ),
]

RequiredTemplateArg = Annotated[
    str,
    Field(
        description="Template to use: a name from pptx_list_templates, or a path to a "
        "'.potx'/'.pptx' under an allowed root."
    ),
]

SlideNumberArg = Annotated[int, Field(description="1-based slide number.")]


def register(server: MCPServer, sandbox: Sandbox) -> None:
    """Add the `pptx_*` tools to `server`, gating the write half on the sandbox."""

    @server.tool(name="pptx_index")
    @guarded
    def pptx_index(path: PathArg) -> PresentationIndex:
        """Summarize a deck: slide count, aspect ratio, layouts, per-slide titles.

        The cheapest first call on an unfamiliar deck. `comment_count` is null
        when the deck uses modern threaded comments, which rp-pptx cannot read.
        """
        return read.get_index(sandbox.resolve_input(path))

    @server.tool(name="pptx_text")
    @guarded
    def pptx_text(
        path: PathArg,
        slides: SlidesArg = "all",
        runs: Annotated[
            bool,
            Field(description="Include per-run formatting (bold, italic, font, size, colour)."),
        ] = False,
    ) -> list[SlideText]:
        """Extract slide text: one result per slide, with its layout and title.

        Reaches grouped shapes recursively. Layout and master text is design
        furniture and is deliberately not included.
        """
        return read.get_text(sandbox.resolve_input(path), slides=slides, runs=runs)

    @server.tool(name="pptx_markdown")
    @guarded
    def pptx_markdown(
        path: PathArg,
        slides: SlidesArg = "all",
        notes: Annotated[bool, Field(description="Include speaker notes.")] = True,
    ) -> str:
        """Convert a deck to Markdown, one section per slide."""
        return read.get_markdown(sandbox.resolve_input(path), slides=slides, notes=notes)

    @server.tool(name="pptx_tables")
    @guarded
    def pptx_tables(
        path: PathArg,
        slides: SlidesArg = "all",
        table_index: Annotated[
            int | None,
            Field(description="1-based index of a single table. Omit for all of them."),
        ] = None,
    ) -> list[Table]:
        """Extract tables as rows of cells, with merged-cell spans."""
        return read.get_tables(sandbox.resolve_input(path), slides=slides, table_index=table_index)

    @server.tool(name="pptx_images")
    @guarded
    def pptx_images(
        path: PathArg, slides: SlidesArg = "all", output_dir: OutputDirArg = None
    ) -> list[EmbeddedImage]:
        """List the images in a deck: slide, size, type, and alt text.

        With no `output_dir` this reports metadata and writes nothing. With
        one, each image is written there — that needs a write root.
        """
        target = sandbox.resolve_output_dir(output_dir) if output_dir else None
        return read.get_images(sandbox.resolve_input(path), slides=slides, output_dir=target)

    @server.tool(name="pptx_notes")
    @guarded
    def pptx_notes(path: PathArg, slides: SlidesArg = "all") -> list[SpeakerNotes]:
        """Read the speaker notes, one result per slide that has any."""
        return read.get_notes(sandbox.resolve_input(path), slides=slides)

    @server.tool(name="pptx_charts")
    @guarded
    def pptx_charts(path: PathArg, slides: SlidesArg = "all") -> list[ChartRef]:
        """Read the charts: type, title, categories, and series values."""
        return read.get_charts(sandbox.resolve_input(path), slides=slides)

    @server.tool(name="pptx_comments")
    @guarded
    def pptx_comments(path: PathArg, slides: SlidesArg = "all") -> list[Comment]:
        """Read the classic comments: author, date, text, and the slide each is on.

        Fails with exit code 3 on a deck using modern threaded comments — that
        part is not readable yet, and an empty list would be indistinguishable
        from a deck with no comments at all.
        """
        return read.get_comments(sandbox.resolve_input(path), slides=slides)

    @server.tool(name="pptx_properties")
    @guarded
    def pptx_properties(path: PathArg) -> CoreProperties:
        """Read the core deck properties: title, author, dates, keywords."""
        return read.get_properties(sandbox.resolve_input(path))

    @server.tool(name="pptx_list_templates")
    @guarded
    def pptx_list_templates() -> list[TemplateInfo]:
        """List the house templates this installation can resolve by name.

        Reports each template's layouts and their placeholders, which is what
        `pptx_create` needs in order to pick one.
        """
        return templates_module.list_templates()

    if not sandbox.writable:
        return

    @server.tool(name="pptx_create")
    @guarded
    def pptx_create(
        output: OutputArg,
        markdown: MarkdownArg | None = None,
        template_name: TemplateArg = None,
        aspect: Literal["16:9", "4:3"] = "16:9",
    ) -> WriteResult:
        """Create a deck, optionally from Markdown, on a template.

        Layout resolution never falls back: if the template has no layout with
        the placeholders the content needs, this fails and says which, rather
        than dropping bullets into a picture placeholder.
        """
        return WriteResult(
            output=write.create(
                sandbox.resolve_output(output),
                markdown=markdown,
                template=sandboxed_template(sandbox, template_name),
                aspect=aspect,
            )
        )

    @server.tool(name="pptx_append_markdown")
    @guarded
    def pptx_append_markdown(
        path: PathArg, markdown: MarkdownArg, output: OutputArg
    ) -> WriteResult:
        """Append Markdown as new slides, writing a new file."""
        return WriteResult(
            output=write.append_markdown(
                sandbox.resolve_input(path), markdown, output=sandbox.resolve_output(output)
            )
        )

    @server.tool(name="pptx_replace_text")
    @guarded
    def pptx_replace_text(
        path: PathArg,
        replacements: Annotated[
            dict[str, str],
            Field(description="Map of literal text to find to the text to put in its place."),
        ],
        output: OutputArg,
        match_case: bool = True,
        preserve_formatting: Annotated[
            bool,
            Field(description="Keep the formatting of the text being replaced."),
        ] = True,
    ) -> ReplaceResult:
        """Replace literal text across slides, tables, groups, and notes.

        Never touches layouts or masters — that is design furniture, and editing
        it from a content operation would be a surprise. Where two keys overlap,
        the longer match wins, so the result does not depend on key ordering.
        """
        return write.replace_text(
            sandbox.resolve_input(path),
            replacements,
            output=sandbox.resolve_output(output),
            match_case=match_case,
            preserve_formatting=preserve_formatting,
        )

    @server.tool(name="pptx_fill_template")
    @guarded
    def pptx_fill_template(
        template_name: RequiredTemplateArg,
        context: Annotated[
            dict[str, str],
            Field(description="Placeholder name to value, without the braces."),
        ],
        output: OutputArg,
        strict: Annotated[
            bool,
            Field(description="Fail when a placeholder in the template has no value."),
        ] = True,
    ) -> FillResult:
        """Fill a `{{ placeholder }}` deck template and write the result."""
        return template_module.fill_template(
            sandboxed_template(sandbox, template_name),
            context,
            sandbox.resolve_output(output),
            strict=strict,
        )

    @server.tool(name="pptx_set_notes")
    @guarded
    def pptx_set_notes(
        path: PathArg,
        slide: SlideNumberArg,
        text: Annotated[str, Field(description="Notes text, replacing whatever is there.")],
        output: OutputArg,
    ) -> WriteResult:
        """Set one slide's speaker notes, writing a new file."""
        return WriteResult(
            output=write.set_notes(
                sandbox.resolve_input(path), slide, text, output=sandbox.resolve_output(output)
            )
        )

    @server.tool(name="pptx_set_properties")
    @guarded
    def pptx_set_properties(
        path: PathArg, properties: CoreProperties, output: OutputArg
    ) -> WriteResult:
        """Set core deck properties, writing a new file.

        Only the fields given are changed; the rest keep their current values.
        """
        return WriteResult(
            output=write.set_properties(
                sandbox.resolve_input(path), properties, output=sandbox.resolve_output(output)
            )
        )

    @server.tool(name="pptx_delete_slides")
    @guarded
    def pptx_delete_slides(path: PathArg, slides: SlidesArg, output: OutputArg) -> SlideOpResult:
        """Delete slides by 1-based number, writing a new file.

        Slide numbers refer to presentation order, not to part filenames — the
        parts stay where they are, so a later call must be made against the new
        file's own numbering rather than the original's.
        """
        return slides_module.delete_slides(
            sandbox.resolve_input(path), slides, output=sandbox.resolve_output(output)
        )

    @server.tool(name="pptx_reorder_slides")
    @guarded
    def pptx_reorder_slides(
        path: PathArg,
        order: Annotated[
            list[int],
            Field(
                description="Every slide's 1-based number, in the order wanted. "
                "Must be a permutation of 1..slide_count."
            ),
        ],
        output: OutputArg,
    ) -> SlideOpResult:
        """Reorder slides, writing a new file."""
        return slides_module.reorder_slides(
            sandbox.resolve_input(path), order, output=sandbox.resolve_output(output)
        )


__all__ = ["register"]
