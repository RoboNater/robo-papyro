# Status — robo-papyro Phase 2 (`rp-mcp`)

**Branch:** `claude/robo-papyro-phase-2-5erlec`
**Driving doc:** [`docs/specs/rp-mcp-spec.md`](../docs/specs/rp-mcp-spec.md), written
during the phase — the parent spec listed Phase 2's driving doc as `TBD`.
**Security model and deliberate limitations:**
[`docs/security-mcp.md`](../docs/security-mcp.md) — the threat model, why each
sandbox rule is shaped the way it is, what the sandbox explicitly does *not*
protect, and the test behind every claim. Findings 3, 4, and 5 below are the
short version; that document is the long one.

## BLUF

`rp-mcp` ships: MCP servers for `rp-pdf`, `rp-docx`, and `rp-pptx` over stdio, a
path sandbox every tool argument is resolved through, and `skills/` with one
skill per format for agents that have a shell instead of a client.

Every tool is a name, a docstring, and a call into a leaf. The estimate in the
Phase 1 and 2.5 stubs — "roughly three lines per tool, because the work is
already done" — held. What was *not* three lines was everything around them:
the sandbox, the error bridge, and the licensing question the parent spec had
answered wrongly.

### Verification

- 1302 tests green (152 in `rp-mcp`, 83 in `ci`, up from 1108 before this
  phase), 9 skipped — the same nine as before, all LibreOffice or
  root-permission environment skips.
- `rp-mcp` at 99% line coverage.
- `ruff check` and `ruff format --check` clean; the full suite re-run with
  `CI=true GITHUB_ACTIONS=true`.
- License gate passes: 73 packages reviewed, base install path free of weak
  copyleft.
- One end-to-end run over real stdio against the installed `rp-pdf-mcp`, plus a
  manual `rp mcp`/`rp-*-mcp` console-script pass.
- `uv build --package robo-papyro` inspected: the published wheel declares the
  three leaves and `Provides-Extra: mcp`, which `uv sync` cannot tell you.
- Every command quoted in the three skills was executed against the real CLIs;
  four were wrong. A fifth was wrong and *not* caught that way, because it needs
  an API key — see finding 12.
- Each regression test from review was run against the unfixed code first and
  observed to fail.

## Findings — where the plan of record turned out to be wrong

### 1. A separate distribution does **not** keep the SDK out of the base install path

Parent spec §11.2 and both leaf stubs say the point of putting MCP in `rp-mcp`
is that "whatever the MCP SDK drags in stays out of the base install path **by
construction**". That reads like a guarantee, and it is not one.

`ci/license_gate.py::base_install_path` walks the runtime dependencies of
**every workspace member**. Adding `rp-mcp` as a member therefore puts the whole
MCP tree into the base path. What the separate distribution actually buys is
that `uv pip install rp-pdf` still pulls nothing MCP-related — real and worth
having, but a different claim.

What keeps §7.1 satisfied is **the SDK version**:

| | `mcp` 1.x | `mcp` 2.x |
|---|---|---|
| HTTP stack | `httpx` → `httpcore` → **`certifi` (MPL-2.0)** | `httpx2` → `httpcore2` → `truststore` (MIT) |
| Weak copyleft in the tree | yes | none |

On 1.x the gate fails twice over: `certifi` is weak copyleft in the base path,
*and* the `extra:ai` tag on `certifi` becomes stale in the same run, because
that tag is a checked claim that nothing in the base path reaches it. So
`mcp>=2.0.0,<3` in `packages/rp-mcp/pyproject.toml` is a **licensing pin as much
as an API pin**, and lowering the floor is not a small change. The spec, the
roadmap, and `ci/allowed-packages.toml` all now say so where someone would
look.

### 2. "FastMCP" is `MCPServer`

Both the parent spec and `ROADMAP.md` Phase 6 say `FastMCP` from the official
`mcp` SDK. In 2.x that class is `mcp.server.mcpserver.MCPServer`; there is no
`mcp.server.fastmcp` module at all. Same thing, renamed across a major — which
is also the reason for the `<3` cap. Field names went snake_case with it
(`input_schema`, `structured_content`, `is_error`), which matters when reading
older SDK examples.

The 2.x line also makes in-process testing first-class: `mcp.Client` accepts an
`MCPServer` object and connects over in-memory streams. `mcp.shared.memory`'s
`create_connected_server_and_client_session`, which 1.x examples use, is gone.

### 3. Where an MCP client may write — the question both stubs deferred

Decided as: **writes need an explicit `--write-root`, and without one the
file-creating tools are not registered at all.**

The second half is the part worth arguing about. Registering a tool that always
fails would have been easier and is worse: a model that sees `docx_create` in
`tools/list` will call it, read the failure, and try again with a different
path, because "permission denied" and "wrong arguments" look alike from the
outside. A tool that is *absent* produces the right behaviour — the agent says
it cannot write and asks. The tool list is the capability list.

Consequences, all in `rp_mcp.sandbox`:

- Reads are confined to `--root` directories; relative paths resolve against the
  first one.
- **Containment is checked on the resolved path.** `..` and symlinks are
  followed before the comparison, so `roots/link → /etc` is refused. A lexical
  check passes every other test in `test_sandbox.py` while leaving exactly the
  hole the sandbox exists to close — the "validating a proxy is worse than
  validating nothing" failure this repo has hit before.
- **Existence is deliberately not checked.** A missing file is the leaf's error
  with the leaf's message and exit code. Checking it in the sandbox would answer
  "no such file" for paths inside and "outside the sandbox" for paths outside,
  which is an existence oracle for the rest of the disk, one call at a time.
- Nothing is overwritten, and there is no spelling of "overwrite": the leaves'
  `output=None` ("edit in place") is never passed, because parent §10's rule is
  "never overwrite an input without `--in-place`" and MCP has no `--in-place`.
- The write root is also a read root, so an agent can read back what it wrote.

The reasoning behind each of those, the threat model they answer, and the list
of things they deliberately do not cover — resource limits, authentication,
prompt injection, TOCTOU — are in
[`docs/security-mcp.md`](../docs/security-mcp.md). It is the document to hand
someone who asks "is this safe to point at my documents?", and the one to update
if any of these rules changes.

### 4. A dangling symlink defeated "never overwrites", and a test caught it

`resolve_output` originally checked `resolved.exists() or resolved.is_symlink()`
*after* `Path.resolve()`. `resolve()` follows the link, so for a dangling symlink
the resolved path is the **target** — which does not exist and is not itself a
symlink. Both checks passed, and a write through the link would have landed on a
path the caller never named.

Found by `test_a_dangling_symlink_still_counts_as_taken`, written from the
docstring's "refuses an existing path of any kind" before the implementation was
looked at again. Fixed by checking the *spelled* path with `is_symlink()` (an
`lstat`) before checking the resolved one for existence. This is the AGENTS.md
rule paying out directly: the assertion came from the guarantee, so it could
fail.

### 5. The sandbox invariant had to be generated, not enumerated

`test_invariants_mcp.py::TestEveryPathGoesThroughTheSandbox` walks the
**registered** tool list, and for every argument named `path`, `output`,
`output_dir`, or `template_name` calls the tool with that argument pointing
outside every root and the rest filled from the JSON schema. All of them must
answer `PathNotAllowedError`.

A hand-written list of tools to check would have been correct on the day it was
written and silently incomplete afterwards — and "someone adds a tool and
forgets `resolve_input`" is the single failure this package can have that a
reviewer is least likely to catch. Verified to fail: replacing
`sandbox.resolve_input(path)` with `Path(path)` in one tool reproduces it
(`pdf_index.path: MissingFileError`).

Two details make it real rather than decorative. The filler values must
*pass* schema validation — an argument that fails validation never reaches the
tool body, so the sandbox check would not run and the tool would look safe (this
bit once, via `docx_set_properties`' nested model). And a result with no
envelope is reported as a distinct failure rather than crashed on, so a schema
mismatch in the test is not mistaken for a verdict about the tool.

### 6. Template arguments are a sandbox boundary, and the leaves disagree in shape

`fill_template` and `create` take "a name or a path". A name resolves against
server-side template directories that are deliberately outside the roots; a path
must be sandboxed. So `rp_mcp.tools._looks_like_a_path` has to agree with both
leaves' rules exactly — treat a name as a path and template lookup breaks, treat
a path as a name and the sandbox is bypassed.

Both leaves spell the rule inline (`rp_docx.templates.resolve_template`) or in a
private helper (`rp_pptx.templates._looks_like_a_path`), and they are not
importable as a contract. It is restated in `rp_mcp.tools` with a comment saying
why, and `TestTemplateNamesAndPaths` asserts the three agree **by exercising the
leaves** — a path-shaped string must raise "No such template file" from both,
a bare name must raise the "unknown name" error from both. Asserting against a
copy of their source would have been a description, not a check.

### 7. Three MCP tools have no CLI equivalent

`docx_find_placeholders`, `docx_set_properties`, and `pptx_set_properties` are
backed by exported library functions (`rp_docx.find_placeholders`,
`rp_docx.set_properties`, `rp_pptx.set_properties`) that **neither CLI
exposes** — the leaf specs' §10 command surfaces do not include them, and the
invariant tests enforce those surfaces, so this is a deliberate CLI shape rather
than an oversight to patch here.

The asymmetry is recorded, not resolved: an MCP client can set core properties
and a shell user cannot. Worth deciding for Phase 3, in the leaf specs, not in
`rp-mcp`. The skills say so explicitly rather than quietly documenting a command
that does not exist.

### 8. Four commands in the skills were wrong until they were run

Written from the usage guides, then executed. `rp-docx append` and `rp-pptx
append` take `--markdown`, not `--from-markdown` (only `create` takes the
latter); `tables` takes `--index N` and `--format`, not `--table N`; and both
"set the document properties" examples named a command that does not exist
(finding 7). None of these would have been caught by review — they read
correctly and are consistent with the sibling commands they are not.

The rule this suggests, for `skills/` specifically: **a skill is a set of
claims about a command line, so run every command in it.** The usage guides get
the same protection from the CI smoke job; the skills had none until this pass.

## What review caught, and the one pattern behind it

Four findings, and they are the same defect wearing different clothes: **the
documentation claimed more than the code delivered, and the tests agreed with
the documentation because the same person wrote both.** Worth naming, because
none of them was catchable by reading the diff.

### 9. The refusal message was itself an oracle (§3 of the security doc)

`resolve_input` judged containment on the resolved path — correct — and then
interpolated *that* path into the error. Asking for `shortcut.docx` under a root
got back `/home/me/private/taxes.docx is outside this server's allowed roots`:
the symlink's target, handed to a caller who had no other way to learn it, with
wording that changed depending on whether the link resolved. Precisely the
oracle §3 spends four paragraphs preventing, reintroduced one layer up.

`_writable_target` had the identical bug; the review flagged only one of the
two, which is the usual shape — a reviewer finds an instance, and the author has
to find the class.

Fixed by quoting the caller's own spelling and saying "resolves outside" rather
than naming the target. Two tests, both verified to fail against the old code:
one asserting the target never appears, one asserting the three outside cases
(symlink out, outside-and-present, outside-and-absent) reduce to the same string
once the caller's own spelling is removed.

### 10. `resolve_output_dir` — where the review was right and the fix was wrong

Reported as: accepting an existing extraction directory breaks "nothing is
overwritten", since the leaves write deterministic names with `write_bytes`.
True. The proposed fix — require a new directory — was **rejected after
checking what the names actually are.**

rp-pdf names extracted files per page (`page0007_img00_…`) and rp-pptx numbers
pictures across the whole deck *before* the slide filter applies. So the
workflow this would have broken — `--pages 1-20`, then `21-40`, into one folder
— never collides, and the page-scoped naming was evidently designed for it. The
owner confirmed it is their daily use. Requiring a new directory would have cost
a real workflow to defend against losing a *generated artifact*.

What is real is narrower: two **different** documents extracting into one
directory can collide (deck A's `image-1.png` and deck B's), and the second
write wins silently. That is now stated in `security-mcp.md` §4 and in
`resolve_output_dir`'s docstring, with the guarantee scoped to outputs a tool
*names*, plus two tests pinning that ranged extraction accumulates rather than
replaces.

The lesson is not "the reviewer was wrong". The finding was right and the doc
was overclaiming. It is that **the remedy for an overclaiming document is
sometimes the document**, and you cannot tell which without checking what the
code actually does — here, reading three filename formats.

### 11. `uv sync` hides the packaging contract

`rp mcp` worked in CI and would have been absent from `pip install
robo-papyro`, because the umbrella declared only the three leaves and a
workspace sync installs every member regardless. Nothing in the suite read the
declared metadata, so the docs and the packaging could drift indefinitely.

`rp-mcp` became an **extra** (`robo-papyro[mcp]`) rather than a runtime
dependency: the servers are already documented as a deliberate second install,
the umbrella degrades gracefully when a subcommand is absent, and a hard
dependency would put starlette and uvicorn in front of every `rp` user.
`TestPackagingContract` reads `pyproject.toml` and asserts the declared shape,
which is the only thing that fails when this drifts. No license-gate effect:
`base_install_path` seeds from every workspace member either way.

> **Reversed after the phase merged.** The repo owner made `rp-mcp` a runtime
> dependency: the suite is built for agentic document work, and an extra puts
> that integration behind a step most users never take. The measured cost is a
> published install going from 34 packages to 56. `TestPackagingContract` is
> inverted and now also asserts the *absence* of the extra, so re-adding it
> fails rather than quietly restoring two install paths.
>
> The half of this finding that survives unchanged is the one that mattered:
> nothing in the suite read its own declared metadata, so the docs and the
> packaging could drift in either direction. The test is what makes the
> decision — either decision — checkable.
>
> One consequence took a second look. `mcp>=2.0.0,<3` was a pin on a package
> people opted into; it now constrains every `robo-papyro` environment, and
> upper bounds are viral — only a new release can lift one. It stays, because
> the SDK renamed its central class across 1.x → 2.x and that is exactly the
> evidence a cap wants, but it stays with `.github/dependabot.yml` behind it,
> since a cap nobody revisits is a cap that eventually strands its users.

### 12. The one skill command that was never run

`--ocr` requires `--ai`; the skill quoted it alone. I had claimed every skill
command was executed, and every one *was* — except this, because it needs an API
key, and that is exactly the one that was wrong. The class is now closed
mechanically by `ci/test_skill_commands.py`, which checks every flag a skill
quotes against the parsed command and catches all four of the originals when
replanted. It cannot catch this one: `--ocr` parses fine and is refused at
runtime. So the rule in AGENTS.md is the real fix — **a command you cannot
execute in CI must be checked against the spec, not assumed.**

### 13. One finding was resolved backwards

Review reported "wrong password is exit 3, not exit 1" against the PDF skill.
The contradiction was real — the skill's prose said 3 and its table said 1 — but
the table was the correct side: `PasswordError(RpPdfError, InputError)` is exit
1, raised at `core.py:83` and `:85` for missing and wrong passwords alike. Exit
3 is for a file pypdf cannot parse at all.

The likely cause is ours: `docs/usage.md` described exit 3 as covering
"encrypted-unreadable", which reads like *wrong password*, and the phrase had
been copied into `usage-mcp.md`. Both now distinguish a password you can fix
(exit 1) from a file that cannot be parsed (exit 3). **A misleading phrase in a
convention table propagates into every consumer of it, including reviewers.**

## Deliberate omissions

Each of these is a decision, not a gap:

- **Rendering** (`pdf render`, Office `render`/`convert`). A path to an image the
  agent cannot see is not useful. Waits for image content blocks, which needs a
  client that displays them and a size policy.
- **The AI review pass** (`to_markdown(ai=True)`). It calls a third-party API
  with the user's key. A server started by a client config must not make that
  call because a model asked it to. The switch stays with the person running the
  CLI.
- **Progress reporting.** `rp_core.Progress` is synchronous, MCP progress
  notifications are not, and bridging would mean marshalling callbacks off a
  worker thread. Every tool uses the no-op reporter — exactly what a
  non-terminal CLI run does — so nothing is lost that an agent would have seen.
- **Non-stdio transports.** `MCPServer` can serve SSE and streamable HTTP; the
  CLI offers neither, and there is no `--transport` flag to add one by accident.
  Binding a port would make a path allowlist the only thing between the internet
  and the user's documents, and a path allowlist is not an authentication story.
  `build_server` remains available to a caller who brings their own front door.

## Known limits

- `pptx_comments` fails (exit 3) on decks with modern threaded comments,
  inheriting rp-pptx's §7 deferral. Correct, and documented in the tool
  description, the guide, and the skill — an agent must not conclude "no
  comments". `pptx_index` stays usable and reports `comment_count: null`.
- The sandbox is a path allowlist and nothing more. It does not limit result
  size, call rate, or CPU. A 500-page `pdf_markdown` is a large response and
  there is no cap on it.
- `resolve_output` creates parent directories inside the write root. That is a
  write the agent did not explicitly ask for; the alternative was an agent
  needing a `mkdir` tool it does not have.
- Passwords are ordinary tool arguments, so an encrypted PDF's password passes
  through the client. That matches the CLI (`--password` is never read from the
  config file) but is worth knowing before pointing a hosted client at a
  password-protected document.

## What the next phase inherits

`rp-xlsx` (Phase 3) gets its MCP server for the cost of one module and one line:
`packages/rp-mcp/src/rp_mcp/xlsx.py` with a `register(server, sandbox)`, and
`"xlsx"` in `server.REGISTRARS`. The invariant tests pick up the new tools
automatically — including the sandbox check, which is the point of generating it
from the registered list.

Two things to copy rather than reinvent: gate every file-creating tool on
`sandbox.writable` inside `register`, and pass an explicit `output` to every
leaf call so in-place editing stays unreachable.

## Still open

1. **Image content blocks** — the right way to make rendering useful over MCP.
2. **Progress over MCP** — worth doing when a long tool call is actually
   reported as hanging.
3. **The property-setting asymmetry** (finding 7) — a leaf-spec decision.
4. **Skill distribution.** `skills/` holds the source; nothing installs them.
   If they are meant to be consumed from a marketplace or a dotfiles repo, that
   needs deciding before anyone copies a stale one.
