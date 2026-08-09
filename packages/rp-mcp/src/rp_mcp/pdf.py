"""The rp-pdf tool surface.

Read-only, and not because PDF writing is unimplemented — rp-pdf has no write
surface at all (its spec's "out of scope"). So there is nothing here gated on a
write root except image extraction, which produces files.

Two omissions are deliberate rather than pending:

* **No rendering.** ``render`` exists in the CLI and writes PNGs; over MCP a
  path to an image an agent cannot see is not useful. Revisit with image content
  blocks, per the rp-pdf roadmap, rather than by adding a path-returning tool.
* **No AI pass.** ``to_markdown(ai=True)`` calls a third-party API with the
  user's key. A server started by a client config must not make that call
  because a model asked it to — the switch belongs to the person running the
  CLI, where it already is.

Everything else maps one-to-one onto ``rp_pdf.core``, with the same defaults, so
an agent that knows the CLI knows these.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from rp_mcp.sandbox import Sandbox
from rp_mcp.tools import (
    OutputDirArg,
    PagesArg,
    PasswordArg,
    PathArg,
    PhysicalArg,
    guarded,
)
from rp_pdf import core, markdown
from rp_pdf.models import (
    DocumentIndex,
    ImageInfo,
    MarkdownResult,
    PageText,
    SearchHit,
    Table,
)

#: The engines rp-pdf's ``get_text`` accepts. ``poppler`` is the default here
#: exactly as it is there — the in-process extractors run words together on PDFs
#: that encode gaps as kerning (issue #1), and an MCP caller has even less
#: chance of noticing that than a human does.
EngineArg = Annotated[
    Literal["poppler", "pypdf", "pdfplumber"],
    Field(
        description="Text extraction engine. 'poppler' (default) needs pdftotext on PATH "
        "and is the most accurate; 'pypdf' and 'pdfplumber' are in-process fallbacks that "
        "can run words together."
    ),
]


def register(server: MCPServer, sandbox: Sandbox) -> None:
    """Add the `pdf_*` tools to `server`."""

    @server.tool(name="pdf_index")
    @guarded
    def pdf_index(path: PathArg, password: PasswordArg = None) -> DocumentIndex:
        """Summarize a PDF: page count, page labels, metadata, outline, sizes.

        The cheapest first call on an unfamiliar document — it says how many
        pages there are and what the document calls them, which is what every
        other tool's page spec is interpreted against.
        """
        return core.get_index(sandbox.resolve_input(path), password=password)

    @server.tool(name="pdf_text")
    @guarded
    def pdf_text(
        path: PathArg,
        pages: PagesArg = "all",
        layout: Annotated[
            bool, Field(description="Preserve the page's visual layout with spacing.")
        ] = False,
        engine: EngineArg = "poppler",
        physical: PhysicalArg = False,
        password: PasswordArg = None,
    ) -> list[PageText]:
        """Extract text, one result per page.

        Each result carries both `physical_page` (1-based position) and
        `labeled_page` (what the document prints on it, null when unlabeled),
        so a citation can be given in the reader's numbering.
        """
        return core.get_text(
            sandbox.resolve_input(path),
            pages=pages,
            layout=layout,
            engine=engine,
            password=password,
            physical=physical,
        )

    @server.tool(name="pdf_tables")
    @guarded
    def pdf_tables(
        path: PathArg,
        pages: PagesArg = "all",
        physical: PhysicalArg = False,
        password: PasswordArg = None,
    ) -> list[Table]:
        """Extract tables as rows of cells, with the page each came from."""
        return core.get_tables(
            sandbox.resolve_input(path), pages=pages, password=password, physical=physical
        )

    @server.tool(name="pdf_search")
    @guarded
    def pdf_search(
        path: PathArg,
        query: Annotated[str, Field(description="Text to find, or a regex when regex is true.")],
        pages: PagesArg = "all",
        regex: Annotated[bool, Field(description="Treat query as a regular expression.")] = False,
        ignore_case: bool = True,
        context: Annotated[
            int, Field(description="Characters of surrounding text to include either side.")
        ] = 80,
        max_hits: Annotated[int, Field(description="Stop after this many hits.")] = 100,
        engine: EngineArg = "poppler",
        physical: PhysicalArg = False,
        password: PasswordArg = None,
    ) -> list[SearchHit]:
        """Find text and report where it is, in both numbering schemes.

        Prefer this to extracting a whole document and searching it: a plain
        (non-regex) query matches with whitespace normalized, so a phrase is
        found across the line wraps that extraction introduces.
        """
        return core.search(
            sandbox.resolve_input(path),
            query,
            pages=pages,
            regex=regex,
            ignore_case=ignore_case,
            context=context,
            max_hits=max_hits,
            engine=engine,
            password=password,
            physical=physical,
        )

    @server.tool(name="pdf_markdown")
    @guarded
    def pdf_markdown(
        path: PathArg,
        pages: PagesArg = "all",
        engine: EngineArg = "poppler",
        outline_headings: Annotated[
            bool, Field(description="Promote outline entries to Markdown headings.")
        ] = False,
        physical: PhysicalArg = False,
        password: PasswordArg = None,
    ) -> MarkdownResult:
        """Convert a PDF to Markdown, with page provenance delimiters.

        Text and tables only. The optional AI review pass the CLI offers is not
        available here — it calls a third-party API, which is not a decision a
        tool call should make on the user's behalf.
        """
        return markdown.to_markdown(
            sandbox.resolve_input(path),
            pages=pages,
            engine=engine,
            outline_headings=outline_headings,
            password=password,
            physical=physical,
        )

    @server.tool(name="pdf_images")
    @guarded
    def pdf_images(
        path: PathArg,
        pages: PagesArg = "all",
        output_dir: OutputDirArg = None,
        physical: PhysicalArg = False,
        password: PasswordArg = None,
    ) -> list[ImageInfo]:
        """List the images embedded in a PDF: page, size, and format.

        With no `output_dir` this reports metadata and writes nothing, which
        works on a read-only server. With one, each image is written there and
        its path is reported — that needs a server started with a write root.
        """
        target = sandbox.resolve_output_dir(output_dir) if output_dir else None
        return core.get_images(
            sandbox.resolve_input(path),
            pages=pages,
            out_dir=target,
            password=password,
            physical=physical,
        )


__all__ = ["register"]
