"""Typer launchers for the servers. Parses args, builds a sandbox, serves.

This is a launcher, not a JSON-first command surface, so most of the suite's CLI
conventions have nothing to bite on: there is one command that prints anything
at all. That one — ``tools`` — follows them exactly, through
``rp_core.clikit``: JSON to stdout by default, ``--plain`` as the human opt-out,
errors as an ``ErrorEnvelope`` on stderr with the suite's exit codes.

**stdio is the only transport.** ``MCPServer`` can also serve SSE and streamable
HTTP, and neither is offered here: binding a port makes the sandbox the *only*
thing standing between the internet and the user's documents, and a sandbox is a
path allowlist, not an authentication story. A caller who wants HTTP has
:func:`rp_mcp.build_server` and can make that decision explicitly, with its own
front door. Being unable to spell it by accident is the point.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Annotated

import anyio
import typer

from rp_core import clikit
from rp_mcp.models import ServerInfo, ToolSummary
from rp_mcp.sandbox import ROOTS_ENV, WRITE_ROOT_ENV, Sandbox
from rp_mcp.server import ALL_SUITES, build_server, server_name


class Suite(str, enum.Enum):
    """Which servers a launcher builds."""

    pdf = "pdf"
    docx = "docx"
    pptx = "pptx"
    all = "all"


RootOption = Annotated[
    list[Path] | None,
    typer.Option(
        "--root",
        help="A directory the server may read from. Repeatable. "
        f"Defaults to {ROOTS_ENV}, then the current directory.",
    ),
]

WriteRootOption = Annotated[
    Path | None,
    typer.Option(
        "--write-root",
        help="The one directory the server may write into. Without it the server is "
        f"read-only and the file-creating tools are not registered. Defaults to {WRITE_ROOT_ENV}.",
    ),
]

ServerOption = Annotated[
    Suite,
    typer.Option("--server", help="Which format's tools to expose."),
]


def _suites(choice: Suite) -> tuple[str, ...]:
    return ALL_SUITES if choice is Suite.all else (choice.value,)


def _sandbox(roots: list[Path] | None, write_root: Path | None) -> Sandbox:
    return Sandbox.from_settings(roots=roots or None, write_root=write_root)


def _serve(suites: tuple[str, ...], roots: list[Path] | None, write_root: Path | None) -> None:
    """Build the server and hand the process to it. Blocks until the client goes."""
    build_server(_sandbox(roots, write_root), suites).run(transport="stdio")


def _summaries(suites: tuple[str, ...], sandbox: Sandbox) -> ServerInfo:
    """What ``tools`` reports: the registered surface for this exact sandbox."""
    server = build_server(sandbox, suites)
    # ``list_tools`` is the async protocol handler; there is no sync accessor
    # for the registered surface, so this drives one turn of an event loop
    # rather than reaching into the tool manager's internals.
    listed = anyio.run(server.list_tools)
    return ServerInfo(
        name=server_name(suites),
        version=server.version,
        sandbox=sandbox.info(),
        tools=sorted(
            (
                ToolSummary(name=tool.name, description=(tool.description or "").strip())
                for tool in listed
            ),
            key=lambda summary: summary.name,
        ),
    )


app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rp-mcp — MCP servers exposing rp-pdf, rp-docx, and rp-pptx to agents.",
)


@app.command()
@clikit.handle_errors()
def serve(
    server: ServerOption = Suite.all,
    root: RootOption = None,
    write_root: WriteRootOption = None,
) -> None:
    """Serve the tools over stdio. Blocks; an MCP client is the other end."""
    _serve(_suites(server), root, write_root)


@app.command()
@clikit.handle_errors()
def tools(
    server: ServerOption = Suite.all,
    root: RootOption = None,
    write_root: WriteRootOption = None,
    plain: clikit.plain_option = False,
) -> None:
    """List the tools a server would expose, without starting it.

    The list depends on the sandbox: without ``--write-root`` the tools that
    create files are not registered, and are genuinely absent here too.
    """
    clikit.emit(_summaries(_suites(server), _sandbox(root, write_root)), plain=plain)


app.command("doctor")(clikit.doctor_command("pdftotext", "pdftoppm", "pdfinfo", "soffice"))


def _suite_app(suite: str) -> typer.Typer:
    """A launcher that serves exactly one format's tools on bare invocation.

    A callback with no subcommands, so ``rp-pdf-mcp --root /docs`` starts the
    server — an MCP client config names a command and arguments, and making it
    name a subcommand too is a step that buys nothing.
    """
    single = typer.Typer(
        add_completion=False,
        help=f"MCP server exposing rp-{suite}'s tools over stdio.",
    )

    @single.callback(
        invoke_without_command=True,
        help=f"Serve rp-{suite}'s tools over stdio. Blocks; an MCP client is the other end.",
    )
    @clikit.handle_errors()
    def main(root: RootOption = None, write_root: WriteRootOption = None) -> None:
        _serve((suite,), root, write_root)

    return single


pdf_app = _suite_app("pdf")
docx_app = _suite_app("docx")
pptx_app = _suite_app("pptx")


__all__ = ["app", "docx_app", "pdf_app", "pptx_app"]
