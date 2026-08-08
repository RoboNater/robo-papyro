# rp-mcp

MCP servers exposing the [robo-papyro](../../README.md) suite to agents:
`rp-pdf`, `rp-docx`, and `rp-pptx` as tools an MCP client can call, over stdio.

Everything the tools do is a leaf package's work. This distribution supplies
three things the leaves deliberately do not: the tool definitions, a **path
sandbox** every argument is resolved through, and the bridge that turns a suite
error into a tool error with its [error envelope](../../docs/usage.md) intact.

## Why a separate distribution

Parent spec §9 puts the MCP servers here rather than in each leaf, so whatever
the MCP SDK drags in stays out of a leaf's dependency graph. `uv pip install
rp-pdf` gets you a PDF toolkit and nothing else; the agent integration is a
deliberate second install.

## Install and run

```sh
uv sync                                   # in the workspace
uv run rp-mcp tools --root .              # what a server would expose, as JSON
uv run rp-mcp serve --root ~/documents    # all three servers, read-only, stdio
```

One format at a time, which is what an MCP client config usually names:

```sh
rp-pdf-mcp  --root ~/documents
rp-docx-mcp --root ~/documents --write-root ~/documents/out
rp-pptx-mcp --root ~/documents
```

A client config entry looks like this:

```json
{
  "mcpServers": {
    "robo-papyro": {
      "command": "rp-mcp",
      "args": ["serve", "--root", "/home/me/documents",
               "--write-root", "/home/me/documents/generated"]
    }
  }
}
```

`--root` is repeatable and also readable as `RP_MCP_ROOTS` (an `os.pathsep`
-separated list); `--write-root` is also `RP_MCP_WRITE_ROOT`.

## The sandbox

- **Reads** are confined to the roots. Containment is checked on the
  *resolved* path, so `..` and symlinks cannot climb out. With no roots given
  the current directory is used.
- **Writes** need `--write-root`, and go only there. Without one the server is
  read-only and **the file-creating tools are not registered at all** — an
  agent sees a smaller tool list rather than tools that always fail.
- **Nothing is overwritten.** Every write tool names an output that must not
  exist. There is no in-place edit over MCP, because there is no `--in-place`
  to opt into. `output_dir` on the `*_images` tools is the deliberate
  exception: an existing directory is accepted so ranged extraction can
  accumulate in one folder.
- The write root is also readable, so an agent can read back what it wrote.
- `rp_sandbox` is a tool: an agent can ask where it may read and write rather
  than discovering it by failing.

## Tools

Read tools are always registered. Write tools (marked ✎) need a write root.

| PDF | Word | PowerPoint |
|---|---|---|
| `pdf_index` | `docx_index` | `pptx_index` |
| `pdf_text` | `docx_text` | `pptx_text` |
| `pdf_tables` | `docx_tables` | `pptx_tables` |
| `pdf_search` | `docx_markdown` | `pptx_markdown` |
| `pdf_markdown` | `docx_images` | `pptx_images` |
| `pdf_images` | `docx_comments` | `pptx_notes` |
| | `docx_tracked_changes` | `pptx_charts` |
| | `docx_properties` | `pptx_comments` |
| | `docx_find_placeholders` | `pptx_properties` |
| | `docx_list_templates` | `pptx_list_templates` |
| | ✎ `docx_create` | ✎ `pptx_create` |
| | ✎ `docx_append_markdown` | ✎ `pptx_append_markdown` |
| | ✎ `docx_replace_text` | ✎ `pptx_replace_text` |
| | ✎ `docx_fill_template` | ✎ `pptx_fill_template` |
| | ✎ `docx_set_properties` | ✎ `pptx_set_properties` |
| | ✎ `docx_accept_changes` | ✎ `pptx_set_notes` |
| | ✎ `docx_reject_changes` | ✎ `pptx_delete_slides` |
| | | ✎ `pptx_reorder_slides` |

`rp_sandbox` is on every server. Arguments and defaults match the CLIs, so
`--pages 3-7` and `{"pages": "3-7"}` mean the same thing.

Two omissions in the PDF server are deliberate, not pending: **rendering**
(a path to an image the agent cannot see is not useful — revisit with image
content blocks) and the **AI review pass** (it calls a third-party API with the
user's key, which is not a decision a tool call should make).

## Errors

A failed call carries the human-readable message, then the suite's error
envelope as the **last line** — the same ordering the CLIs use on stderr:

```
Error executing tool pdf_index: /etc/hostname is outside this server's allowed roots (/docs).
{"error":{"type":"PathNotAllowedError","message":"…","hint":null,"exit_code":1}}
```

`exit_code` means what it means everywhere else in the suite: **1** bad
arguments, **2** a missing external binary (poppler, LibreOffice), **3** a
corrupt or unsupported file.

## Library use

```python
from rp_mcp import Sandbox, build_server

server = build_server(Sandbox(roots=["/docs"], write_root="/docs/out"))
server.run(transport="stdio")
```

`build_pdf_server`, `build_docx_server`, and `build_pptx_server` build one
suite each. **stdio is the only transport the CLI offers**; `MCPServer` can
serve SSE and streamable HTTP, and a caller who wants either should reach for
`build_server` and bring an authentication story — a path allowlist is not one.

Full guide: [docs/usage-mcp.md](../../docs/usage-mcp.md). Security model and
deliberate limitations: [docs/security-mcp.md](../../docs/security-mcp.md).
Specification: [docs/specs/rp-mcp-spec.md](../../docs/specs/rp-mcp-spec.md).
