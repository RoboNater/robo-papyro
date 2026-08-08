# MCP servers (`rp-mcp`)

`rp-mcp` puts the robo-papyro suite behind the Model Context Protocol, so an MCP
client can read and write PDF, Word, and PowerPoint files as tool calls rather
than as shell commands.

It is one package of the [robo-papyro](../README.md) suite. Everything the tools
do is `rp-pdf`, `rp-docx`, and `rp-pptx` work — same functions, same defaults,
same [exit codes](#errors). What `rp-mcp` adds is the tool definitions, a path
sandbox, and the error bridge.

## Starting a server

```sh
uv run rp-mcp serve --root ~/documents                      # all three, read-only
uv run rp-mcp serve --server docx --root ~/documents \
                    --write-root ~/documents/generated      # Word, read and write
```

One format at a time, which is usually what a client config names:

```sh
rp-pdf-mcp  --root ~/documents
rp-docx-mcp --root ~/documents --write-root ~/documents/out
rp-pptx-mcp --root ~/documents
```

These serve on bare invocation — no subcommand. `rp mcp serve ...` works too,
through the umbrella.

**stdio is the only transport.** `MCPServer` can also serve SSE and streamable
HTTP; neither is offered here, because binding a port would leave a path
allowlist as the only thing between the internet and your documents, and a path
allowlist is not an authentication story. Use `rp_mcp.build_server` and bring
your own front door if you need HTTP.

### Client configuration

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

| Setting | Flag | Environment variable |
|---|---|---|
| Readable directories | `--root DIR` (repeatable) | `RP_MCP_ROOTS` (`os.pathsep`-separated) |
| Writable directory | `--write-root DIR` | `RP_MCP_WRITE_ROOT` |

With neither set, the server reads the current working directory and writes
nothing.

### Seeing the surface without starting a client

```sh
uv run rp-mcp tools --server pdf --root .                        # JSON
uv run rp-mcp tools --server docx --root . --write-root ./out --plain
```

`tools` builds the real server and lists what it registered, so the output
reflects the sandbox: without `--write-root` the file-creating tools are
genuinely absent.

## What the server may touch

- **Reads** are confined to the roots. Containment is checked on the *resolved*
  path, so `..` and symlinks cannot climb out of a root.
- **Writes** need `--write-root` and go only there. Without one the server is
  read-only and the file-creating tools are **not registered at all** — an agent
  sees a shorter tool list rather than tools that always fail.
- **Nothing is overwritten.** Every write tool names an output, and that output
  must not exist. There is no in-place edit over MCP, because there is no
  `--in-place` to opt into.
- The write root is also readable, so an agent can read back what it wrote.
- Relative paths in tool calls resolve against the **first** root.

The reasoning behind each of these rules — and, more importantly, the list of
things the sandbox does **not** protect against — is in
[security-mcp.md](security-mcp.md). Read it before pointing a server at
anything sensitive.

An agent can ask rather than guess:

```json
{"name": "rp_sandbox", "arguments": {}}
→ {"roots": ["/home/me/documents", "/home/me/documents/generated"],
   "write_root": "/home/me/documents/generated", "writable": true}
```

## Tools

Names are `<format>_<operation>` on every server, including the single-format
ones, so what an agent learns against `rp-pdf-mcp` transfers to the combined
server. Arguments and defaults match the CLIs.

### PDF — read only

| Tool | Does |
|---|---|
| `pdf_index` | Page count, page labels, metadata, outline, sizes |
| `pdf_text` | Text per page, with both numbering schemes |
| `pdf_tables` | Tables as rows of cells |
| `pdf_search` | Find text; whitespace-normalized so phrases match across line wraps |
| `pdf_markdown` | Markdown with page provenance delimiters |
| `pdf_images` | Embedded image metadata; extracts to disk given `output_dir` and a write root |

Page specs behave exactly as on the CLI: `all`, `5`, `3-7`, `-4`, `7-`,
`1,3-5,9`, interpreted against the document's page labels unless
`physical: true`. Encrypted files take a `password`.

**Rendering and the AI review pass are not exposed.** A path to an image the
agent cannot see is not useful — that waits for image content blocks — and the
AI pass calls a third-party API with your key, which is not a decision a tool
call should make on your behalf. Both remain on the CLI.

### Word

Read: `docx_index`, `docx_text`, `docx_markdown`, `docx_tables`, `docx_images`,
`docx_comments`, `docx_tracked_changes`, `docx_properties`,
`docx_find_placeholders`, `docx_list_templates`.

Write (needs a write root): `docx_create`, `docx_append_markdown`,
`docx_replace_text`, `docx_fill_template`, `docx_set_properties`,
`docx_accept_changes`, `docx_reject_changes`.

`docx_replace_text` reaches body, tables, text boxes, headers, footers,
footnotes, and endnotes, and across the run splits Word introduces mid-word —
which is why it exists rather than a string replace. It reports a per-key count
and where each hit was.

### PowerPoint

Read: `pptx_index`, `pptx_text`, `pptx_markdown`, `pptx_tables`, `pptx_images`,
`pptx_notes`, `pptx_charts`, `pptx_comments`, `pptx_properties`,
`pptx_list_templates`.

Write (needs a write root): `pptx_create`, `pptx_append_markdown`,
`pptx_replace_text`, `pptx_fill_template`, `pptx_set_notes`,
`pptx_set_properties`, `pptx_delete_slides`, `pptx_reorder_slides`.

`pptx_comments` **fails** on a deck using modern threaded comments rather than
reporting none — rp-pptx cannot read that part yet, and an empty list would be
indistinguishable from a deck with no comments. `pptx_index` stays usable and
reports `comment_count: null`. See [usage-pptx.md](usage-pptx.md#comments).

Slide numbers are presentation order, 1-based. After a delete or a reorder, a
follow-up call must use the *new* file's numbering.

### Templates

`docx_fill_template` and `pptx_fill_template` take either a house-template name
(from `*_list_templates`) or a path to a template under an allowed root. A name
resolves against the server's template directories, which are configuration and
deliberately outside the sandbox; a path does not.

Call `docx_find_placeholders` first — it is the only way to learn what keys the
context needs, and a strict fill fails on a missing one rather than shipping a
document with `{{ client_name }}` still in it.

## Errors

A failed tool call carries the human-readable message, then the suite's error
envelope as the **last line** — the same ordering the CLIs use on stderr:

```
Error executing tool pdf_index: /etc/hostname is outside this server's allowed roots (/docs). Start the server with --root DIR to widen them.
{"error":{"type":"PathNotAllowedError","message":"…","hint":null,"exit_code":1}}
```

| `exit_code` | Meaning |
|---|---|
| `1` | Bad arguments — a path outside the roots, a bad page spec, a missing placeholder value, an output that already exists |
| `2` | A required external binary is absent (`rp-mcp doctor` reports what is installed) |
| `3` | The file is corrupt, encrypted-unreadable, or uses something unsupported |

These are the suite's codes, unchanged. A bug in the server is *not* wrapped —
it arrives as a traceback in the server log rather than as a tidy message that
reads like an expected outcome.

Errors that originate in `rp-mcp` itself are always exit 1:
`PathNotAllowedError`, `OutputExistsError`, `WritesNotEnabledError`,
`NoRootsError`.

## Checking the environment

```sh
uv run rp-mcp doctor          # poppler and LibreOffice, as every other CLI reports them
```

Nothing in the read or write path needs an external binary except PDF text
extraction and rendering (poppler) and Office conversion (LibreOffice).

## Library use

```python
from rp_mcp import Sandbox, build_server

sandbox = Sandbox(roots=["/docs"], write_root="/docs/out")
build_server(sandbox).run(transport="stdio")
```

`build_pdf_server`, `build_docx_server`, and `build_pptx_server` build one suite
each; `build_server(sandbox, ("pdf", "docx"))` builds any combination.

For tests, `mcp.Client` accepts the server object directly and talks to it over
in-memory streams — no subprocess, no sockets:

```python
import anyio
from mcp import Client

async def main():
    async with Client(build_server(sandbox)) as client:
        print(await client.call_tool("pdf_index", {"path": "report.pdf"}))

anyio.run(main)
```

## Skills instead

If your agent has shell access, it does not need an MCP server — the CLIs are
already a stable interface. [`skills/`](../skills) holds one skill per format
teaching that surface directly. Use the servers for a client that has no shell,
and the skills for one that does.
