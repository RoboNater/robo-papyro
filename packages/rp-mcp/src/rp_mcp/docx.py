"""The rp-docx tool surface.

The read tools are always registered. The write tools are registered **only when
the sandbox has a write root**, so an agent talking to a read-only server does
not see them in ``tools/list`` at all. That is the answer to the question the
Phase 2.5 stub left open — "where is an MCP client allowed to write" — and the
shape of the answer matters: a tool that exists and always fails teaches a model
to retry, while a tool that is absent teaches it to ask.

Every write tool names its output explicitly and that output must not exist. The
leaf functions all accept ``output=None`` meaning "edit in place", and this
module never passes that: the suite's "never overwrite an input without
``--in-place``" rule (parent spec section 10) has no ``--in-place`` to opt into
over MCP, so in-place editing is simply not reachable here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from rp_docx import templates as templates_module
from rp_docx.docx import read, write
from rp_docx.docx import template as template_module
from rp_docx.models import (
    Comment,
    CoreProperties,
    DocumentIndex,
    EmbeddedImage,
    FillResult,
    Paragraph,
    ReplaceResult,
    Table,
    TemplateInfo,
    TrackedChange,
    WriteResult,
)
from rp_mcp.sandbox import Sandbox
from rp_mcp.tools import (
    OutputArg,
    OutputDirArg,
    PathArg,
    guarded,
    sandboxed_template,
)

MarkdownArg = Annotated[
    str,
    Field(
        description="Markdown source. Headings, paragraphs, bullet and numbered lists, "
        "pipe tables, fenced code, and thematic breaks."
    ),
]

TemplateArg = Annotated[
    str | None,
    Field(
        description="Template to build on: a name from docx_list_templates, or a path to a "
        "'.dotx'/'.docx' under an allowed root. Omit for the built-in default."
    ),
]

#: The same argument where a template is required rather than optional.
RequiredTemplateArg = Annotated[
    str,
    Field(
        description="Template to use: a name from docx_list_templates, or a path to a "
        "'.dotx'/'.docx' under an allowed root."
    ),
]

ReplacementsArg = Annotated[
    dict[str, str],
    Field(description="Map of literal text to find to the text to put in its place."),
]

AuthorsArg = Annotated[
    list[str] | None,
    Field(description="Only act on revisions by these authors. Omit for all authors."),
]


def register(server: MCPServer, sandbox: Sandbox) -> None:
    """Add the `docx_*` tools to `server`, gating the write half on the sandbox."""

    @server.tool(name="docx_index")
    @guarded
    def docx_index(path: PathArg) -> DocumentIndex:
        """Summarize a Word document: counts, styles used, headings, properties.

        The cheapest first call on an unfamiliar document. The heading list is
        usually enough to decide which of the other tools to reach for.
        """
        return read.get_index(sandbox.resolve_input(path))

    @server.tool(name="docx_text")
    @guarded
    def docx_text(
        path: PathArg,
        style_filter: Annotated[
            str | None,
            Field(description="Only return paragraphs in this style, e.g. 'Heading 1'."),
        ] = None,
        runs: Annotated[
            bool,
            Field(description="Include per-run formatting (bold, italic, font, size, colour)."),
        ] = False,
    ) -> list[Paragraph]:
        """Extract paragraphs, in document order, with their styles.

        Paragraph indices are 1-based and are what every other tool means by a
        paragraph number.
        """
        return read.get_text(
            sandbox.resolve_input(path), style_filter=style_filter, runs_wanted=runs
        )

    @server.tool(name="docx_markdown")
    @guarded
    def docx_markdown(path: PathArg) -> str:
        """Convert the whole document to Markdown.

        Lossy by nature — it keeps structure (headings, lists, tables, emphasis)
        and drops presentation. Use `docx_text` when style names matter.
        """
        return read.get_markdown(sandbox.resolve_input(path))

    @server.tool(name="docx_tables")
    @guarded
    def docx_tables(
        path: PathArg,
        table_index: Annotated[
            int | None,
            Field(description="1-based index of a single table. Omit for all of them."),
        ] = None,
    ) -> list[Table]:
        """Extract tables as rows of cells."""
        return read.get_tables(sandbox.resolve_input(path), table_index=table_index)

    @server.tool(name="docx_images")
    @guarded
    def docx_images(path: PathArg, output_dir: OutputDirArg = None) -> list[EmbeddedImage]:
        """List the images embedded in a document: size, type, and alt text.

        With no `output_dir` this reports metadata and writes nothing. With
        one, each image is written there — that needs a write root.
        """
        target = sandbox.resolve_output_dir(output_dir) if output_dir else None
        return read.get_images(sandbox.resolve_input(path), output_dir=target)

    @server.tool(name="docx_comments")
    @guarded
    def docx_comments(path: PathArg) -> list[Comment]:
        """Read the comments: author, date, text, and the text each is anchored to."""
        return read.get_comments(sandbox.resolve_input(path))

    @server.tool(name="docx_tracked_changes")
    @guarded
    def docx_tracked_changes(path: PathArg) -> list[TrackedChange]:
        """Read the tracked revisions: insertions, deletions, and format changes."""
        return read.get_tracked_changes(sandbox.resolve_input(path))

    @server.tool(name="docx_properties")
    @guarded
    def docx_properties(path: PathArg) -> CoreProperties:
        """Read the core document properties: title, author, dates, keywords."""
        return read.get_properties(sandbox.resolve_input(path))

    @server.tool(name="docx_find_placeholders")
    @guarded
    def docx_find_placeholders(template_name: RequiredTemplateArg) -> list[str]:
        """List the `{{ placeholder }}` names a template contains.

        Call this before `docx_fill_template` — it is the only way to learn
        what keys the context needs, and a strict fill fails on a missing one.
        Takes a name or a path, exactly like `docx_fill_template`.
        """
        return template_module.find_placeholders(
            templates_module.resolve_template(sandboxed_template(sandbox, template_name))
        )

    @server.tool(name="docx_list_templates")
    @guarded
    def docx_list_templates() -> list[TemplateInfo]:
        """List the house templates this installation can resolve by name.

        Reports each template's styles and page size, which is what a
        `docx_create` call needs in order to pick one.
        """
        return templates_module.list_templates()

    if not sandbox.writable:
        return

    @server.tool(name="docx_create")
    @guarded
    def docx_create(
        output: OutputArg,
        markdown: MarkdownArg | None = None,
        template_name: TemplateArg = None,
        title: Annotated[str | None, Field(description="Document title property.")] = None,
        page_size: Literal["letter", "a4"] = "letter",
    ) -> WriteResult:
        """Create a Word document, optionally from Markdown, on a template.

        Style resolution never falls back: if the chosen template lacks a style
        the Markdown needs, this fails and names it rather than writing a
        document that looks wrong.
        """
        return WriteResult(
            output=write.create(
                sandbox.resolve_output(output),
                markdown=markdown,
                template=sandboxed_template(sandbox, template_name),
                title=title,
                page_size=page_size,
            )
        )

    @server.tool(name="docx_append_markdown")
    @guarded
    def docx_append_markdown(
        path: PathArg, markdown: MarkdownArg, output: OutputArg
    ) -> WriteResult:
        """Append Markdown to an existing document, writing a new file."""
        return WriteResult(
            output=write.append_markdown(
                sandbox.resolve_input(path), markdown, output=sandbox.resolve_output(output)
            )
        )

    @server.tool(name="docx_replace_text")
    @guarded
    def docx_replace_text(
        path: PathArg,
        replacements: ReplacementsArg,
        output: OutputArg,
        match_case: bool = True,
        preserve_formatting: Annotated[
            bool,
            Field(description="Keep the formatting of the text being replaced."),
        ] = True,
    ) -> ReplaceResult:
        """Replace literal text everywhere it appears, writing a new file.

        "Everywhere" means body, tables, text boxes, headers, footers,
        footnotes, and endnotes — and across the arbitrary run splits Word
        introduces mid-word, which is why this exists rather than a string
        replace. The result reports a per-key count and where each hit was.
        """
        return write.replace_text(
            sandbox.resolve_input(path),
            replacements,
            output=sandbox.resolve_output(output),
            match_case=match_case,
            preserve_formatting=preserve_formatting,
        )

    @server.tool(name="docx_fill_template")
    @guarded
    def docx_fill_template(
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
        """Fill a `{{ placeholder }}` template and write the result.

        Run `docx_find_placeholders` first. With `strict` left on, an
        unfilled placeholder is an error rather than a document that ships with
        `{{ client_name }}` still in it.
        """
        return template_module.fill_template(
            sandboxed_template(sandbox, template_name),
            context,
            sandbox.resolve_output(output),
            strict=strict,
        )

    @server.tool(name="docx_set_properties")
    @guarded
    def docx_set_properties(
        path: PathArg, properties: CoreProperties, output: OutputArg
    ) -> WriteResult:
        """Set core document properties, writing a new file.

        Only the fields given are changed; the rest keep their current values.
        """
        return WriteResult(
            output=write.set_properties(
                sandbox.resolve_input(path), properties, output=sandbox.resolve_output(output)
            )
        )

    @server.tool(name="docx_accept_changes")
    @guarded
    def docx_accept_changes(
        path: PathArg, output: OutputArg, authors: AuthorsArg = None
    ) -> WriteResult:
        """Accept tracked changes, writing a new file."""
        return WriteResult(
            output=write.accept_changes(
                sandbox.resolve_input(path),
                output=sandbox.resolve_output(output),
                authors=authors,
            )
        )

    @server.tool(name="docx_reject_changes")
    @guarded
    def docx_reject_changes(
        path: PathArg, output: OutputArg, authors: AuthorsArg = None
    ) -> WriteResult:
        """Reject tracked changes, writing a new file."""
        return WriteResult(
            output=write.reject_changes(
                sandbox.resolve_input(path),
                output=sandbox.resolve_output(output),
                authors=authors,
            )
        )


__all__ = ["register"]
