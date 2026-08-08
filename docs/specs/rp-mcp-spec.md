# rp-mcp Specification

**Version:** 1.0
**Status:** Implemented — suite Phase 2
**Parent:** [`robo-papyro-spec.md`](robo-papyro-spec.md) §9

Written alongside the implementation rather than ahead of it. The parent spec
listed Phase 2's driving doc as `TBD`; this is it, and where it corrects an
expectation the parent or the roadmap recorded, it says so rather than quietly
agreeing.

---

## 1. Purpose

`rp-mcp` exposes `rp-pdf`, `rp-docx`, and `rp-pptx` to agents over the Model
Context Protocol. It is a fourth published distribution, not a module in a leaf
and not an extra.

**It implements no document behaviour.** Every tool is a name, a docstring, and
a call into a leaf. If a tool needs logic, that logic belongs in the leaf, where
the CLI gets it too. The three things this package genuinely owns are:

1. the tool definitions and their agent-facing documentation,
2. the **sandbox** — a path allowlist every argument is resolved through,
3. the **error bridge** — a suite error reaching a client with its envelope and
   exit code intact.

## 2. Why a separate distribution

Parent spec §11.2: putting MCP in its own distribution means "whatever the MCP
SDK drags in stays out of the base install path by construction". That framing
needs one correction, and it is load-bearing.

The license gate computes the base install path from **every workspace member's
runtime dependencies**. Adding `rp-mcp` as a member therefore puts the MCP SDK's
tree *into* the base path — the isolation is real for `rp-pdf`'s dependency
graph (`uv pip install rp-pdf` still pulls nothing MCP-related) but it is not
automatic protection for §7.1.

What makes §7.1 hold is the SDK version. `mcp` 1.x depends on `httpx`, which
depends on **`certifi` (MPL-2.0)**; that is weak copyleft in the base install
path and the gate fails it outright. `mcp` 2.x replaced `httpx` with `httpx2` +
`truststore` and pulls no weak-copyleft package at all. So:

> **`mcp>=2.0.0,<3` is a licensing constraint, not only an API one.** Lowering
> the floor to 1.x re-introduces MPL-2.0 into the base install path and makes
> both `extra:ai` tags in `ci/allowed-packages.toml` stale at the same time.

The cap is separate: the server class is `FastMCP` in 1.x and `MCPServer` in
2.x. The parent spec and `ROADMAP.md` both say "FastMCP", written before 2.0
existed; the class is the same thing under a new name.

## 3. Layout

```
packages/rp-mcp/src/rp_mcp/
    __init__.py     public surface: Sandbox, build_server, the error classes
    sandbox.py      the path allowlist — the only place that decides what is legal
    errors.py       RpMcpError and friends, all InputError (exit 1)
    models.py       SandboxInfo, ServerInfo, ToolSummary — about the server, not a document
    tools.py        the error bridge, the shared argument types, template-path handling
    pdf.py          register(server, sandbox) — the pdf_* tools
    docx.py         register(server, sandbox) — the docx_* tools
    pptx.py         register(server, sandbox) — the pptx_* tools
    server.py       build_server(sandbox, suites) and the per-suite builders
    cli.py          the launchers
```

`register(server, sandbox)` per format, not a module-level server object: the
sandbox is runtime configuration, and a server built before it is known would
have to be mutated afterwards to learn what it may touch — which is how a
read-only server accidentally grows write tools.

## 4. The sandbox

Normative here; the reasoning, the threat model, and the explicit non-goals are
in [`../security-mcp.md`](../security-mcp.md). Anything this section requires,
that document explains — and anything it deliberately does not cover (resource
limits, authentication, prompt injection, TOCTOU) is enumerated there rather
than left to inference.

### 4.1 Roots

Readable directories. Precedence: `--root` (repeatable) → `RP_MCP_ROOTS`
(`os.pathsep`-separated) → the current working directory.

A relative path in a tool call resolves against the **first** root, so a client
configured with one root can pass bare filenames.

### 4.2 Containment

Every path is resolved with `Path.resolve()` — collapsing `..` *and following
symlinks* — before it is compared against the roots. A lexical check is not
acceptable: `roots/link → /etc` passes one while looking careful, which is the
"validating a proxy is worse than validating nothing" failure the parent
codebase has already hit once.

`NUL` bytes and other unusable paths become the same refusal, not a traceback.

### 4.3 Existence is not the sandbox's business

`resolve_input` does **not** check that the file exists. A missing file is the
leaf's error, with the leaf's message and exit code. Checking here would make
the sandbox answer "no such file" for paths outside it and "outside the
sandbox" for paths inside it — an existence oracle for the whole filesystem,
one call at a time.

### 4.4 Writes

A separate grant: `--write-root` / `RP_MCP_WRITE_ROOT`, one directory. Without
it the server is read-only.

- Write tools are **not registered** on a read-only server. A tool that exists
  and always fails teaches a model to retry; a tool that is absent teaches it to
  ask.
- Every output path must be **new**. An existing file, an existing directory,
  or a symlink at the named path is refused. `Path.resolve()` follows a link, so
  a dangling one looks free while a write through it lands somewhere the caller
  never named — the *spelled* path is checked with `lstat` before the resolved
  one is checked for existence.
- Parent directories are created, inside the write root only.
- The write root is added to the readable roots, so an agent can read back what
  it wrote.

**There is no in-place edit over MCP.** The leaf functions all accept
`output=None` meaning "edit in place"; no tool here passes it. The suite's rule
is "never overwrite an input without `--in-place`" (parent §10), and MCP has no
`--in-place` to opt into.

### 4.5 Template arguments

A template argument may be a house-template *name* or a *path*. Names are passed
through for the leaf to resolve against its own template directories — those are
server-side configuration, deliberately outside the roots, exactly like the
bundled default. Path forms go through `resolve_input`.

The "is this a path" rule (a suffix, or a separator) is restated in
`rp_mcp.tools` rather than imported from a leaf, because here it decides
*whether the sandbox applies*, and a security boundary resting on another
package's private helper is one refactor from silently widening. The invariant
tests assert the three agree by exercising the leaves, not by reading them.

## 5. Tools

### 5.1 Naming

`<format>_<operation>`, in every server including the single-format ones, plus
`rp_sandbox` everywhere. An agent that learns `pdf_search` against `rp-pdf-mcp`
calls the same tool through the combined server, and a client connected to two
of them has no collisions to resolve.

### 5.2 Surface

Reads (always registered):

| PDF | Word | PowerPoint |
|---|---|---|
| `pdf_index`, `pdf_text`, `pdf_tables`, `pdf_search`, `pdf_markdown`, `pdf_images` | `docx_index`, `docx_text`, `docx_markdown`, `docx_tables`, `docx_images`, `docx_comments`, `docx_tracked_changes`, `docx_properties`, `docx_find_placeholders`, `docx_list_templates` | `pptx_index`, `pptx_text`, `pptx_markdown`, `pptx_tables`, `pptx_images`, `pptx_notes`, `pptx_charts`, `pptx_comments`, `pptx_properties`, `pptx_list_templates` |

Writes (registered only with a write root):

| Word | PowerPoint |
|---|---|
| `docx_create`, `docx_append_markdown`, `docx_replace_text`, `docx_fill_template`, `docx_set_properties`, `docx_accept_changes`, `docx_reject_changes` | `pptx_create`, `pptx_append_markdown`, `pptx_replace_text`, `pptx_fill_template`, `pptx_set_notes`, `pptx_set_properties`, `pptx_delete_slides`, `pptx_reorder_slides` |

`rp-pdf` has no write surface at all, so a write root adds nothing to the PDF
server beyond letting `pdf_images` extract to disk.

Arguments and defaults match the CLIs: `--pages 3-7` and `{"pages": "3-7"}` mean
the same thing, page specs follow page labels unless `physical` is true, and all
indices are 1-based.

### 5.3 Deliberate omissions

- **Rendering.** `rp-pdf render` and the Office `render`/`convert` commands write
  image or PDF files. Over MCP a path to an image the agent cannot see is not
  useful. Revisit with image content blocks, per the rp-pdf roadmap — not by
  adding a path-returning tool now.
- **The AI review pass.** `to_markdown(ai=True)` calls a third-party API with the
  user's key. A server started by a client config must not make that call
  because a model asked it to. The switch stays where it is: with the person
  running the CLI.
- **Progress reporting.** `rp_core.Progress` is synchronous and MCP progress
  notifications are not. The no-op reporter is what every tool uses, exactly as
  a non-terminal CLI run does, so nothing is lost that an agent would have seen.
- **Non-stdio transports.** `MCPServer` can serve SSE and streamable HTTP; the
  CLI offers neither. Binding a port would make a path allowlist the only thing
  between the internet and the user's documents, and a path allowlist is not an
  authentication story. `build_server` remains available to a caller who wants
  HTTP and brings their own front door.

### 5.4 Two leaf behaviours an agent will meet

- `pptx_comments` **fails** (exit 3, `UnsupportedFeatureError`) on a deck with
  modern threaded comments rather than returning an empty list — rp-pptx spec §7.
  Surfacing that as a tool error is the right answer for the same reason it is on
  the CLI: a wrong empty result is worse than a loud failure. `pptx_index` stays
  usable and reports `comment_count: null`.
- Style and layout resolution never falls back. A template missing a style or a
  layout fails and names it, rather than producing a document that looks wrong.

## 6. Errors

One shape, the parent spec's (§4.1). A `RoboPapyroError` becomes a `ToolError`
whose text is the human-readable message followed by the `ErrorEnvelope` as its
**last line** — the same ordering `rp_core.clikit.error_handler` writes to
stderr, so an agent that has learned to read the last line of a failed `rp-pdf`
run reads the last line of a failed tool call and finds the same keys.

Exit codes pass through unchanged: **1** bad arguments, **2** a missing external
binary, **3** a corrupt or unsupported file. Errors this package originates are
all exit 1, because they are all about the arguments a caller supplied.

Non-suite exceptions are **not** caught. A `ZeroDivisionError` here is a bug in
this package or a leaf, and a bug should arrive as a traceback in the server log
rather than as a tidy message that reads like an expected outcome.

## 7. CLI

```sh
rp-mcp serve [--server pdf|docx|pptx|all] [--root DIR]... [--write-root DIR]
rp-mcp tools [--server ...] [--root DIR]... [--write-root DIR] [--plain]
rp-mcp doctor [--plain]

rp-pdf-mcp  [--root DIR]... [--write-root DIR]     # serves on bare invocation
rp-docx-mcp [...]
rp-pptx-mcp [...]
```

Also `rp mcp ...` through the umbrella's entry-point discovery.

`tools` is the one command that prints a result, and it follows the suite
conventions exactly: JSON to stdout by default, `--plain` as the human opt-out,
no `--json` flag, errors as an envelope on stderr. It lists the **registered**
surface for the sandbox it was given, so a read-only server genuinely shows
fewer tools — which is also how CI asserts the write gate without starting a
client.

The per-format launchers serve on bare invocation, with no subcommand: an MCP
client config names a command and arguments, and making it name a subcommand too
buys nothing.

## 8. Testing

- Servers are driven **in-process** through `mcp.Client`, which accepts an
  `MCPServer` object over in-memory streams. Real registration, real schema
  validation, real error path, no transport in the way.
- One module drives the installed `rp-pdf-mcp` over **real stdio**, because a
  stray `print` anywhere on the import path corrupts the JSON-RPC stream and
  every in-memory test still passes.
- `TestEveryPathGoesThroughTheSandbox` walks the *registered* tool list, calls
  each tool once per path-shaped argument with a value outside every root, and
  requires a `PathNotAllowedError` every time. A tool added later that forgets
  `resolve_input` fails without anyone remembering to add a test. It is verified
  to fail: removing the sandbox call from one tool reproduces it.
- Documents are generated in `conftest.py`, including the modern-threaded-comment
  deck, which is built by adding the part **and its content type** — detection
  keys on the content type, so a fixture that only added the file would not
  exercise the guard. No binary fixtures in git.

## 9. Skills

`skills/` holds one skill per format, teaching an agent the CLI surface and the
conventions that are easy to get wrong (page labels, 1-based indices, the exit
codes, never overwriting an input). They are for a coding agent with shell
access; the MCP servers are for a client without one. Both describe the same
library, so a claim that changes in one changes in both.

## 10. Open

1. **Image content blocks.** The right way to make rendering useful over MCP.
   Needs a client that displays them and a size policy; neither is settled.
2. **Progress over MCP.** Would need a sync-to-async bridge from
   `rp_core.Progress` onto `ctx.report_progress`, on a worker thread. Worth doing
   when a long tool call is actually reported as hanging.
3. **`rp-xlsx` (Phase 3).** When it lands, `xlsx.py` and one line in
   `server.REGISTRARS` are the whole integration. The invariant tests cover the
   new tools automatically.
