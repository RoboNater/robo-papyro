"""Models rp-mcp adds on top of the leaves'.

Every document-shaped result an MCP tool returns is a leaf package's model,
unchanged — that is the point of the design, and why a tool is three lines. The
two models here describe the *server* rather than a document: what it may touch,
and what it exposes.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class SandboxInfo(BaseModel):
    """Where a running server may read and write.

    Returned by the ``rp_sandbox`` tool so an agent can ask rather than guess.
    Knowing the roots up front is the difference between one failed call and a
    search of the filesystem by trial and error.
    """

    #: Directories the server will read from, resolved and deduplicated. A
    #: relative path in a tool call is taken against the first of these.
    roots: list[Path]

    #: The one directory the server will write into, or ``None`` when the
    #: server is read-only. Always also a member of ``roots``.
    write_root: Path | None = None

    #: Whether the write tools are registered at all.
    writable: bool = False


class ToolSummary(BaseModel):
    """One tool as an agent sees it in ``tools/list``."""

    name: str
    description: str


class ServerInfo(BaseModel):
    """What ``rp-mcp tools`` reports: a server's identity, sandbox, and surface.

    The tool list is the *registered* one, so it reflects the sandbox it was
    built with — a read-only server genuinely has fewer tools, and this is how
    you see that without starting a client.
    """

    name: str
    version: str
    sandbox: SandboxInfo
    tools: list[ToolSummary]


__all__ = ["SandboxInfo", "ServerInfo", "ToolSummary"]
