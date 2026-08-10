"""Assembling a server from a sandbox and a choice of suites.

A server is built, never imported: the sandbox is runtime configuration, and a
module-level server object would have to be mutated after the fact to know what
it may touch — which is how a read-only server accidentally grows write tools.
:func:`build_server` takes the sandbox first and registers accordingly, so the
capability set and the configuration cannot come apart.

The tool names are prefixed by format (``pdf_``, ``docx_``, ``pptx_``, ``xlsx_``)
in every server, including the single-format ones. An agent that learns
``pdf_search`` against ``rp-pdf-mcp`` calls the same tool through the combined
server, and a client that connects to two of them has no name collisions to
resolve.
"""

from __future__ import annotations

from collections.abc import Iterable

from mcp.server.mcpserver import MCPServer

from rp_mcp import docx as docx_tools
from rp_mcp import pdf as pdf_tools
from rp_mcp import pptx as pptx_tools
from rp_mcp import xlsx as xlsx_tools
from rp_mcp.models import SandboxInfo
from rp_mcp.sandbox import Sandbox

#: The registration function for each suite, in the order a combined server
#: lists them.
REGISTRARS = {
    "pdf": pdf_tools.register,
    "docx": docx_tools.register,
    "pptx": pptx_tools.register,
    "xlsx": xlsx_tools.register,
}

#: Every suite, which is what a bare ``rp-mcp serve`` builds.
ALL_SUITES: tuple[str, ...] = tuple(REGISTRARS)

__version__ = "0.1.0"

_INSTRUCTIONS = """\
Document tools for PDF, Word, PowerPoint, and Excel files, from the robo-papyro suite.

Start with the `*_index` tool for the format you are looking at: it is cheap and
tells you what the document contains, which is what the other tools' arguments
are expressed against. All indices are 1-based — pages, paragraphs, tables,
slides. PDF page specs follow the document's own page labels unless you pass
`physical: true`.

Call `rp_sandbox` to learn which directories this server can read and whether it
can write at all. When a tool fails, the last line of the error is a JSON error
envelope with a `type` and an `exit_code`: 1 means the arguments were wrong, 2
means an external program (poppler, LibreOffice) is missing, 3 means the file is
corrupt or uses something unsupported.
"""


def server_name(suites: Iterable[str]) -> str:
    """``robo-papyro`` for the full set, ``robo-papyro-pdf`` for one suite."""
    chosen = tuple(suites)
    return "robo-papyro" if len(chosen) != 1 else f"robo-papyro-{chosen[0]}"


def build_server(sandbox: Sandbox, suites: Iterable[str] = ALL_SUITES) -> MCPServer:
    """An ``MCPServer`` exposing ``suites``, bounded by ``sandbox``.

    Unknown suite names raise ``KeyError`` rather than being skipped: a typo in
    a client config that silently produced a server with fewer tools would be
    diagnosed as "the tool does not exist" somewhere far away.
    """
    chosen = tuple(suites)
    server = MCPServer(
        name=server_name(chosen),
        version=__version__,
        instructions=_INSTRUCTIONS,
    )

    @server.tool(name="rp_sandbox")
    def rp_sandbox() -> SandboxInfo:
        """Report which directories this server may read, and where it may write.

        Paths in tool calls may be absolute, or relative to the first root.
        When `writable` is false the tools that create files are not
        registered at all, and this server can only read.
        """
        return sandbox.info()

    for suite in chosen:
        REGISTRARS[suite](server, sandbox)
    return server


def build_pdf_server(sandbox: Sandbox) -> MCPServer:
    """The `rp-pdf-mcp` server."""
    return build_server(sandbox, ("pdf",))


def build_docx_server(sandbox: Sandbox) -> MCPServer:
    """The `rp-docx-mcp` server."""
    return build_server(sandbox, ("docx",))


def build_pptx_server(sandbox: Sandbox) -> MCPServer:
    """The `rp-pptx-mcp` server."""
    return build_server(sandbox, ("pptx",))


def build_xlsx_server(sandbox: Sandbox) -> MCPServer:
    """The `rp-xlsx-mcp` server."""
    return build_server(sandbox, ("xlsx",))


__all__ = [
    "ALL_SUITES",
    "REGISTRARS",
    "build_docx_server",
    "build_pdf_server",
    "build_pptx_server",
    "build_server",
    "build_xlsx_server",
    "server_name",
]
