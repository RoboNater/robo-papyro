"""rp-mcp — MCP servers exposing the robo-papyro suite to agents.

```python
from rp_mcp import Sandbox, build_server

server = build_server(Sandbox(roots=["/docs"], write_root="/docs/out"))
server.run(transport="stdio")
```

**Why this is a separate distribution.** Parent spec section 9 puts the MCP
servers here rather than in each leaf, so whatever the MCP SDK drags in stays
out of a leaf's dependency graph. `uv pip install rp-pdf` gets you a PDF
toolkit and nothing else. The boundary is about the leaves: the `robo-papyro`
umbrella depends on this package unconditionally, so a suite install has the
servers.

**Why the tools are three lines each.** Every function in `rp_pdf`, `rp_docx`,
and `rp_pptx` already returns a pydantic model, so a tool is a name, a
docstring, and a call — the model becomes the structured content an MCP client
receives, with a JSON schema generated from the same annotations. Nothing here
reformats a result, and nothing here implements a document operation. If a tool
needs logic, that logic belongs in the leaf, where the CLI gets it too.

The one thing this package does add is the :class:`~rp_mcp.sandbox.Sandbox`:
every path in every tool call is resolved through it before a leaf sees it,
because an MCP server takes paths from a model rather than from the person at
the keyboard.
"""

from __future__ import annotations

from rp_mcp.errors import (
    NoRootsError,
    OutputExistsError,
    PathNotAllowedError,
    RpMcpError,
    WritesNotEnabledError,
)
from rp_mcp.models import SandboxInfo, ServerInfo, ToolSummary
from rp_mcp.sandbox import ROOTS_ENV, WRITE_ROOT_ENV, Sandbox
from rp_mcp.server import (
    ALL_SUITES,
    build_docx_server,
    build_pdf_server,
    build_pptx_server,
    build_server,
)

__version__ = "0.1.0"

__all__ = [
    "ALL_SUITES",
    "ROOTS_ENV",
    "WRITE_ROOT_ENV",
    "NoRootsError",
    "OutputExistsError",
    "PathNotAllowedError",
    "RpMcpError",
    "Sandbox",
    "SandboxInfo",
    "ServerInfo",
    "ToolSummary",
    "WritesNotEnabledError",
    "__version__",
    "build_docx_server",
    "build_pdf_server",
    "build_pptx_server",
    "build_server",
]
