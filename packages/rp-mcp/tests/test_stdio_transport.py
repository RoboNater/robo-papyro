"""One end-to-end run over the real transport, against the installed script.

Everything else in this suite drives an `MCPServer` object in memory, which is
the right level for behaviour but proves nothing about the thing a client
config actually names: a console script that has to start, speak stdio, and
keep stdout clean. A stray `print` anywhere on the import path corrupts the
JSON-RPC stream and every in-memory test still passes.

Skipped rather than failed when the console script is not installed, because
that means the package was not installed — an environment fact, not a defect.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(
    shutil.which("rp-pdf-mcp") is None,
    reason="rp-pdf-mcp console script is not on PATH; install the workspace first",
)

TIMEOUT_SECONDS = 60


def _session(docs: Path, work):
    """Run `work(session)` against `rp-pdf-mcp` rooted at `docs`."""
    params = StdioServerParameters(command="rp-pdf-mcp", args=["--root", str(docs)])

    async def main():
        with anyio.fail_after(TIMEOUT_SECONDS):
            async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
                await s.initialize()
                return await work(s)

    return anyio.run(main)


def test_the_console_script_serves_over_stdio(sample_pdf: Path, docs: Path):
    async def work(session):
        tools = await session.list_tools()
        result = await session.call_tool("pdf_index", {"path": sample_pdf.name})
        return sorted(tool.name for tool in tools.tools), result

    names, result = _session(docs, work)
    assert "pdf_index" in names
    assert result.structured_content["page_count"] == 3


def test_the_sandbox_holds_across_the_real_transport(docs: Path):
    """The refusal is the server's, not an artefact of the in-memory harness."""

    async def work(session):
        return await session.call_tool("pdf_index", {"path": "/etc/hostname"})

    result = _session(docs, work)
    assert result.is_error
    envelope = json.loads(result.content[0].text.splitlines()[-1])
    assert envelope["error"]["type"] == "PathNotAllowedError"


def test_the_server_reports_its_own_sandbox(docs: Path):
    async def work(session):
        return await session.call_tool("rp_sandbox", {})

    result = _session(docs, work)
    assert result.structured_content == {
        "roots": [str(docs.resolve())],
        "write_root": None,
        "writable": False,
    }
