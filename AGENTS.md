# AGENTS.md — context for AI development sessions

`robo-papyro` is a document tooling suite giving agentic coding tools a stable,
scriptable interface to PDF and Office formats. It is **one repository holding
several independently versioned Python distributions**, managed as a uv
workspace.

| Distribution | Import | CLI | Purpose |
|---|---|---|---|
| `rp-core` | `rp_core` | — | Shared infrastructure: errors and exit codes, external-binary discovery, rendering, range specs, generic OOXML/Markdown mechanics, CLI conventions |
| `rp-pdf` | `rp_pdf` | `rp-pdf` | PDF read/extract/render (the former `pdfx`) |
| `rp-docx` | `rp_docx` | `rp-docx` | Word documents — read, create, edit, template |
| `rp-pptx` | `rp_pptx` | `rp-pptx` | PowerPoint decks — read, create, edit, template, slide operations |
| `rp-mcp` | `rp_mcp` | `rp-mcp` | MCP servers exposing the three leaves to agents |
| `robo-papyro` | `robo_papyro` | `rp` | Meta-distribution and umbrella dispatcher |

## Layout

```
packages/rp-core/src/rp_core/     errors, models, ranges, binaries, render, doctor, clikit, progress, markdown, ooxml
packages/rp-pdf/src/rp_pdf/       core, markdown, ocr, vlm_utils, models, config, describe, cli
packages/rp-docx/src/rp_docx/     ooxml, templates, models, errors, cli, docx/{read,write,runs,template}
packages/rp-pptx/src/rp_pptx/     ooxml, templates, models, errors, cli, pptx/{read,write,runs,slides,template}
packages/rp-mcp/src/rp_mcp/       sandbox, tools, errors, models, {pdf,docx,pptx}, server, cli
packages/robo-papyro/src/robo_papyro/   cli.py — the `rp` dispatcher
docs/specs/                       the governing specifications
dev-notes/                        investigation write-ups and phase status notes
skills/                           agent skills for the three CLIs, one directory each
templates/                        house .dotx/.docx and .potx/.pptx templates; templates/local/ is gitignored
```

Each package has its own `pyproject.toml` and its own `tests/`. Shared dev
dependencies, ruff config, and pytest config live in the **root**
`pyproject.toml`; no code lives at the root.

## The four rules that matter most

1. **One-way dependencies.** `rp-core` imports no leaf package, ever. Leaf
   packages (`rp-pdf`, `rp-docx`, …) never import each other. `robo-papyro`
   depends on leaves and reaches them through entry-point discovery rather than
   imports. **`rp-mcp` is the one distribution that imports leaves** — it is a
   consumer sitting above them, not a peer, and nothing imports `rp_mcp` back.
   It reaches only their public library surface: never a leaf's `cli` or
   `config`, which is asserted by
   `packages/rp-mcp/tests/test_invariants_mcp.py`.
2. **Import from `rp-core`, don't reimplement.** Range-spec parsing, binary
   discovery, rasterization, error envelopes, exit codes, generic OPC/OOXML zip
   mechanics, and the shared Markdown block/inline parser have exactly one
   implementation. If you are about to write `shutil.which`, a page-range
   parser, an exception with an exit code, a zip repack, or a Markdown parser,
   look in `rp_core` first.
3. **Core logic never prints and never imports typer.** Library functions
   return pydantic models; CLI modules do all formatting. (`rp_core.clikit` is
   the deliberate exception — it *is* the shared CLI layer.) Progress reporting
   does not bend this: a long-running function takes a
   `progress: Progress | None` and *calls* it, defaulting to the no-op reporter,
   and only the CLI decides that means writing to stderr.
4. **Permissive licenses only.** See below. If a forbidden dependency seems
   necessary, stop and ask rather than adding it.

Also: all user-facing indices are 1-based (pages, paragraphs, tables,
sections); never overwrite an input file unless `--in-place` is passed; no
external binary is required for any core read/write path.

## Commands

```sh
uv sync                              # whole workspace, editable
uv sync --all-extras                 # adds the optional VLM deps

uv run pytest                        # every package
uv run pytest packages/rp-pdf        # one package
uv run pytest packages/rp-core -q

uv run ruff check packages
uv run ruff format packages          # line length 100
```

`uv build --package rp-pdf` produces a wheel with a normal version-pinned
`rp-core` requirement.

**External binaries** are optional and subprocess-only. `rp doctor` (or
`rp-pdf doctor`) reports what is installed.

| Binary | Needed for | Install |
|---|---|---|
| `pdftotext`/`pdftoppm`/`pdfinfo` | default text engine, rendering | `apt install poppler-utils` |
| `soffice` | Office → PDF conversion, Office rendering | LibreOffice |

Tests needing poppler carry `@pytest.mark.requires_poppler` and skip when it is
absent; tests needing LibreOffice carry `@pytest.mark.requires_soffice` and skip
unless it is present *and demonstrably working*. **No test may require
LibreOffice to pass** — mock the subprocess, or mark it and let it skip.

### Make sure poppler is installed before trusting a test run

`uv sync` is not the whole setup. **77 tests carry `requires_poppler`** and skip
*silently* without it, and they are not incidental ones: page rendering, the
default text engine, and the entire AI/OCR path go untested — which is where the
interesting bugs live. A green run without poppler proves much less than it
looks like, and a skip count is easy to read past.

So the invariant is: **check first, install if missing, using whatever package
manager the machine has.**

```sh
uv run rp doctor          # or: command -v pdftotext pdftoppm
```

If it reports them missing, install poppler the way the table above describes
for your platform — `brew install poppler` on macOS, `winget install
oschwartz10612.Poppler` on Windows, your distribution's package on Linux. On the
root-owned Debian container these sessions usually get, that is:

```sh
apt-get update -q && apt-get install -y -q poppler-utils    # prefix with sudo if not root
```

The `update` matters *there* because that image ships an index stale enough for
the install to 404; on a maintained machine it is unnecessary. An ephemeral
container also starts fresh every session, so expect to repeat this; a
workstation needs it once.

LibreOffice is heavier and its tests are allowed to skip by policy, so leave it
alone unless you are working on conversion.

### Adding a package to the workspace

1. `packages/<dist>/` with `pyproject.toml`, `src/<import_name>/`, `tests/`.
2. Declare `rp-core` in `dependencies` *and* add
   `[tool.uv.sources] rp-core = { workspace = true }`. Members do not inherit.
3. Register the CLI twice: `[project.scripts]` for the standalone command, and
   `[project.entry-points."robo_papyro.commands"]` pointing at the **typer app
   object** so `rp <name>` finds it. Nothing in `robo_papyro` needs changing.
4. Share test helpers through `conftest.py` **fixtures**, not by importing one
   test module from another — pytest runs in importlib import mode, so a test
   file's directory is not on `sys.path` and `from conftest import X` fails.
   Distinct test-module basenames are still good style but no longer
   load-bearing.

### Workspace invariants — run these, don't memorize them

Three rules the workspace enforces with tests rather than prose. Read the test
if you trip one; each explains what breaks and why.

| Rule | Test |
|---|---|
| Every typer command is in `COMMAND_NAMES`, or it parses as a filename | `packages/rp-pdf/tests/test_invariants.py` |
| `rp-docx`'s command surface matches the one its spec §10 specifies | `packages/rp-docx/tests/test_invariants.py` |
| `rp-pptx`'s command surface matches the one its spec §10 specifies | `packages/rp-pptx/tests/test_invariants.py` |
| Every `rp-mcp` tool resolves its path arguments through the sandbox | `packages/rp-mcp/tests/test_invariants_mcp.py` |
| No leaf imports `rp_mcp`, and `rp_mcp` imports no leaf's CLI layer | `packages/rp-mcp/tests/test_invariants_mcp.py` |
| `robo_papyro/cli.py` imports no leaf package | `packages/robo-papyro/tests/test_umbrella_cli.py::TestNoLeafImports` |
| Test modules are imported by path, so same-named ones cannot collide | `ci/test_workspace_invariants.py` |
| `rp_core` holds no page-label logic and imports no leaf | `ci/test_workspace_invariants.py` |

## Package notes

### rp-core

- `errors.py` — `RoboPapyroError` and its exit codes: **0** success, **1** user
  or input error, **2** missing external dependency, **3** corrupt or
  unsupported file. Every error carries `.to_envelope()`.
- `binaries.py` — `find_binary` / `require_binary` / `run_binary` /
  `soffice_convert`. `soffice_convert` must keep its per-invocation
  `-env:UserInstallation` profile (a shared one makes parallel calls exit zero
  and write nothing), its output-file verification (a zero exit code is not
  evidence of success), and its timeout.
- **No subprocess runs unbounded.** `run_binary(timeout=None)` means "the suite
  default" — `RP_SUBPROCESS_TIMEOUT` or 600s — not "wait forever"; there is no
  way to spell forever. Expiry raises `SubprocessTimeout` (exit 3), never
  `subprocess.TimeoutExpired`.
- `render.py` — `rasterize` is the primitive: one PDF, one contiguous physical
  page range, caller-supplied file naming. `render_pages` is the convenience
  wrapper that also routes non-PDF sources through LibreOffice. rp-core has no
  concept of a page *label*; a caller that has them resolves them first.
- `clikit.py` — `error_handler`/`handle_errors`, `emit`, `plain_option`,
  `doctor_command`. Two shapes are fixed suite-wide and take no argument
  selecting an alternative: results are JSON unless `--plain`, and errors are an
  `ErrorEnvelope` on stderr, written *after* the human-readable message so the
  envelope is always the final line. **There is no `--json` flag** anywhere —
  `packages/rp-pdf/tests/test_cli.py::test_no_json_flag_on_any_command`
  enforces that.
  Also here: `progress_option`/`describe_option`, `display_enabled` (flag → env
  → config → `stderr.isatty()`), `job`, and `parse_bool`. **typer 0.27 accepts
  `is_flag`/`flag_value` and forwards neither to click** — `typer.main` never
  mentions them — so an optional-value option (`--save-config` with no argument)
  cannot be spelled. Check before designing an option shape around one.
- `progress.py` — `Progress`/`Step`, whose base implementation does nothing, and
  `StderrProgress`, which does. **Never on by default**: `NULL` is what every
  library function substitutes for `progress=None`, and a CLI only swaps in the
  real one when stderr is a terminal or a flag said so, so nothing an agent sees
  changes. Its display thread is what makes an indeterminate step useful — the
  elapsed clock has to advance while the caller is blocked, or "stuck" and
  "slow" look the same. Everything goes to stderr; stdout is results.
  Note the identifier ban: `label` means *page label* in this suite and
  `ci/test_workspace_invariants.py` fails on it in rp-core, so a step's display
  string is its `name`.
- `ooxml.py` — generic OPC/OOXML package mechanics shared by every OOXML leaf:
  zip read/repack (`part_names`, `read_part`, `parse_part`, `repack`),
  relationship target resolution (`resolve_target`), content-type reading and
  rewriting (`override_content_types`, `content_type_from`, `retype`), and the
  compiled-`etree.XPath` helper (`compiled_xpath`) that both python-docx and
  python-pptx need because each overrides `_Element.xpath` with an incomplete
  namespace map of its own. **No format-specific identifier lives here** —
  namespace maps and content-type strings are always arguments, never
  constants, and a missing/malformed part is `None`/`ValueError` rather than a
  leaf-specific exception. `rp_docx.ooxml` and `rp_pptx.ooxml` wrap this with
  their own namespace maps, content-type strings, and error classes.
- `markdown.py` — the shared Markdown block/inline parser (`parse_markdown`,
  `parse_inline`), promoted out of `rp-docx` once `rp-pptx` needed the same
  grammar. Format-agnostic: it produces a `Block`/`Span` AST, and each leaf
  supplies its own renderer over that AST. Not a CommonMark implementation —
  headings, paragraphs, lists, GFM pipe tables, fenced code, thematic breaks,
  HTML comment blocks, and a small set of inline spans, and no more.

### rp-pdf

- `core.py` is pure extraction; `cli.py` is a typer wrapper only; `config.py` is
  CLI-layer only (`core` never imports it).
- Every per-page result carries both `physical_page` (1-based position) and
  `labeled_page` (the PDF's display label, `null` when unlabeled). Page specs
  are interpreted against page labels by default; `--physical` / `physical=True`
  opts out. New features must preserve this.
- Default text engine is poppler's `pdftotext`, because in-process extractors
  run words together on PDFs that encode gaps as glyph kerning (issue #1).
  Don't quietly switch engines.
- **rp-pdf's CLI shape is the suite default**: JSON to stdout by *default* with
  `--plain`/`--csv` opt-outs, and errors as an `ErrorEnvelope` on **stderr**.
  All of it goes through `rp_core.clikit`; new packages do the same.
- CLI options must stay config-overridable: booleans are paired
  `--flag/--no-flag` defaulting to `None`, and every option is read through
  `config.resolve(...)` so flag → env → config → default holds. A bare
  `rp-pdf FILE` runs the `[default].command` (else `index`); new subcommands
  must be registered in `COMMAND_NAMES` — see the invariants table above.
  Secrets (API key, `--password`) are never read from the config file — nor
  written by `--save-config`, which persists the options a run was *given*,
  after it succeeds (per-command keys to `[command]`, shared VLM keys to
  `[vlm]`). Explicitly-passed flags only: a saved built-in default freezes
  today's default into the user's file, and `cli.NEVER_SAVED` additionally drops
  `markdown -o`, which names this document's output rather than the next one's.
- Each job command resolves its options through **one `Options` object**, which
  records the resolved value (what runs, and what `describe.py` reports) and
  whether a flag supplied it (what `--save-config` writes). One call per option,
  so the run, the description, and the saved file cannot drift apart; a new
  option goes through it, not around it.
- `--describe`/`--progress` resolve through `clikit.display_enabled` (flag →
  `RP_PDF_*` → config → `stderr.isatty()`) rather than `config.resolve`, which
  cannot express "no fixed default". `[ui]` backs them like `[vlm]` backs the
  model settings.
- Heavy/optional deps are imported lazily — `openai` must never be imported
  unless the AI pass runs.
- Errors subclass `rp_pdf.errors.RpPdfError`, which is parented onto
  `rp_core.errors`; that is what gives each one its exit code and the `type` its
  envelope reports. Nothing raises a bare builtin: a missing file is
  `MissingFileError`, which is also a `FileNotFoundError` for library callers.

### rp-docx

- **`ooxml.py` is the only place that knows WordprocessingML** — the namespace
  map, the two content-type strings, and part names like `word/comments.xml`.
  The generic package mechanics underneath (zip read/repack, content-type
  rewriting, the compiled-XPath helper) live in `rp_core.ooxml` and are shared
  with `rp-pptx`; `rp_docx.ooxml` wraps them and adds Word-specific errors.
  python-docx covers none of comments, tracked changes, or `.dotx`.
- **python-docx does not open a `.dotx` at all.** It reads
  `[Content_Types].xml`, sees the template content type, and raises
  `ValueError`. House templates are the normal path here, so use
  `ooxml.opened(path)` — never `docx.Document(path)` — and `ooxml.save` on the
  way out, which retypes when the output is named `.dotx`. Asserted by
  `tests/test_ooxml.py::TestContentTypes`.
- **`ooxml.xpath` compiles through `etree.XPath`, deliberately.** python-docx
  subclasses `_Element` and overrides `xpath` with a single-argument version
  binding *its* namespace map, which omits several namespaces this package
  needs. Do not call `element.xpath(...)` directly.
- **`docx/runs.py` is the highest-risk code; read its docstring before editing
  anything that replaces text.** Word splits a logical string across `w:r` runs
  arbitrarily, so a naive `run.text.replace()` finds nothing *and reports
  success*. Every text edit goes through it, and every text edit walks
  `write.revisable_parts()` — body, table cells, text boxes, headers, footers,
  footnotes, endnotes. Body-only replacement is the classic silent bug.
- **Style resolution never falls back.** `templates.require_style` raises,
  naming the missing style and listing what the template has. It is called at
  the point of use rather than eagerly over the whole `StyleMap`, because Word
  defines no code style and an eager check rejects python-docx's own default
  template. `StyleMap.code` is the one optional role, for that reason.
- **`TemplateManifest` carries no content, and that is a correctness property.**
  No document text, no image bytes, no author names, no path beyond the
  basename — enforced by `tests/test_templates.py::TestManifest`. It is what
  lets a confidential template be regression-tested from committed JSON. A new
  field that would break the assertion does not belong in the model.
- Fixtures are generated in `conftest.py`, including the tracked-changes and
  comments documents python-docx cannot produce — those are written as XML.
  **No binary templates in git.** `@pytest.mark.requires_soffice` probes whether
  LibreOffice can actually *convert*, not merely whether the binary exists: some
  containers ship a `soffice` that fails every conversion.

### rp-pptx

- **`.potx` needs the same retyping `.dotx` does.** python-pptx doesn't open a
  `.potx` at all (`Presentation()` raises `ValueError`), and `save()` always
  writes the *presentation* content type — verified against python-pptx 1.0.2,
  not assumed. Every entry point goes through `ooxml.opened(path)` and
  `ooxml.save(...)`, exactly like `rp-docx`'s `.dotx` handling.
- **Slide order is `p:sldIdLst`, never part filenames.** `reorder_slides`
  rewrites the `p:sldId` sequence while leaving every part where it is, so
  `slide3.xml` is not slide 3 after a reorder or a delete. Classic-comment and
  modern-comment attribution both walk `p:sldIdLst` → relationship → part —
  never a filename pattern — for the same reason.
- **Text replacement reaches slide shapes, tables, grouped shapes (recursively),
  and notes slides — never layouts or masters.** Layout/master text is design
  furniture; editing it from a content operation would be a surprise. Where two
  placeholder matches overlap, the longer one wins, so results never depend on
  dict ordering.
- **Modern threaded comments are deferred, not silently dropped.** No
  PowerPoint-authored reference deck was available to verify the part schema
  against, so a deck carrying modern comment parts (detected by content type,
  never by filename) makes `get_comments` raise `UnsupportedFeatureError`
  (exit 3) rather than return an empty list indistinguishable from "no
  comments." `get_index` stays total and reports `comment_count: null` in that
  case. Classic comments are unaffected and fully supported. See
  `dev-notes/status-robo-papyro-phase-2.5.md`.
- **Template synthesis uses raw OOXML, not python-pptx.** python-pptx can read
  and rename a layout but cannot author one, and cannot add a master at all —
  `ooxml.rebuild_masters` does the zip-level surgery (copying the master's
  colour map/theme link, authoring layout parts, rewriting
  `p:sldMasterIdLst`/rels/content-types together) that the public API has no
  path to.
- `shape.shape_type` raises `NotImplementedError` for shapes python-pptx can't
  classify (SmartArt, ink, hand-authored shapes), so classification keys on the
  element tag (`p:pic`, `p:grpSp`, …) instead, which cannot raise.

### rp-mcp

- **A tool is a name, a docstring, and a call.** Every leaf function already
  returns a pydantic model, so the model *is* the structured content and its
  annotations *are* the JSON schema. Nothing here reformats a result or
  implements a document operation; if a tool needs logic, that logic belongs in
  the leaf, where the CLI gets it too.
- **Every path argument goes through `sandbox.resolve_input` /
  `resolve_output` before a leaf sees it.** Containment is checked on the
  *resolved* path, so `..` and symlinks cannot climb out. Existence is
  deliberately not checked — a missing file is the leaf's error, and checking it
  here would make the sandbox an existence oracle for the rest of the disk.
- **The write tools are registered only when `sandbox.writable`.** A tool that
  exists and always fails teaches a model to retry; an absent tool teaches it to
  ask. No tool ever passes `output=None` to a leaf, so in-place editing is
  unreachable — there is no `--in-place` over MCP to opt into.
- `guarded` sits *under* `@server.tool()` so the schema is still generated from
  the wrapped signature. It catches `RoboPapyroError` only: a foreign exception
  is a bug and should arrive as a traceback, not as a tidy expected-looking
  message. The tool error's text is the message, then the `ErrorEnvelope` as the
  **last line** — the same ordering `clikit.error_handler` uses on stderr.
- **stdio is the only transport the CLI offers**, and there is no `--transport`
  flag to add one by accident. Binding a port would leave a path allowlist as
  the only thing between the internet and the user's documents.
- Tests drive real servers through `mcp.Client` over in-memory streams; one
  module drives the installed console script over real stdio, because a stray
  `print` on the import path corrupts JSON-RPC and every in-memory test still
  passes.

### robo-papyro

`cli.py` reaches leaves through entry-point discovery only — see the
invariants table above. `rp <name>` gets whatever the leaf registered as its
typer app, which means argv preprocessing done by a leaf's console script
(rp-pdf's `[default].command` rewriting) does not apply to `rp pdf FILE.pdf`.

## Licensing

**Approved:** python-docx (MIT), lxml (BSD-3), mammoth (BSD-2), pypdf (BSD-3),
pdfplumber (MIT), pdf2image (MIT), openpyxl (MIT), python-pptx (MIT), XlsxWriter
(BSD-2, transitive via python-pptx), typer (MIT), pydantic (MIT), Pillow
(MIT-CMU), pytest/ruff (MIT), `mcp` 2.x (MIT) and its tree.

**`mcp` is floored at 2.0 for licensing, not only for its API.** 1.x depends on
`httpx` → `certifi` (MPL-2.0); `rp-mcp` is a published distribution, so that
lands in the base install path and fails §7.1 — *and* invalidates the
`extra:ai` tags on `certifi` and `tqdm` in the same run. 2.x uses `httpx2` +
`truststore` and pulls no weak copyleft. Do not lower the floor.

**Forbidden — these are blockers, not preferences:** `docxtpl` (LGPL-2.1-only),
`pandoc` (GPL), `PyMuPDF`/`fitz` (AGPL), Aspose/Spire (commercial).

LibreOffice (MPL-2.0) and poppler (GPL-2.0) are fine because they are only ever
invoked as subprocesses — no linkage, no license propagation.

`ci/license_gate.py` fails the build on four things: a forbidden package
anywhere in `uv.lock`; a package not in `ci/allowed-packages.toml`; **weak
copyleft (MPL and friends) anywhere in the base install path**; and an
allowlist entry tagged `extra:<name>` that turns out to be reachable from the
base path anyway. The *base install path* is the runtime dependencies of the
published distributions with no extras and no dev group — what `uv pip install
rp-core rp-pdf` gives you.

That last check is why tags are written `tag = "extra:ai"` in a table rather
than as a comment: a tag is a claim about the dependency graph, and the graph
moves. Don't add one you haven't verified — the gate will, and it will fail.

## Testing notes

### Test the behavior you want, not the behavior you wrote

**This is the rule that has caught the most real bugs here, by being broken.**
Write each assertion from the docstring, the spec, or the bug report — then make
it pass. A test written by reading the implementation and asserting what it does
is a description, not a check: it passes on the day you write it and every day
after, including the days the behavior is wrong.

Defects have shipped here with green suites for exactly this reason, more than
once. Two are worth knowing by shape, because both looked *self-consistent*: the
code did what the tests said, the tests said what the code did, and only the
docstring disagreed — and nothing checks a docstring.

- `to_markdown`'s docstring promised progress reporting on a hung file read.
  Every progress test opened a step first, so not one of them could have
  noticed that the reporter's thread starts *after* the file is opened. The
  feature missed the only scenario it existed for.
- `save_command_options`' docstring promised a mid-write failure could not lose
  a section. No test ever failed a write, and `write_text` truncates the target,
  so any interruption destroyed the file.

The tell in both: **a test that would have to be edited before it could fail.**
If catching the bug means changing the test rather than just running it, the
test was written from the code.

Two habits that follow:

- **A guarantee in a docstring is a claim, and a claim needs a test.** If you
  write "cannot", "always", or "never" in prose, add the assertion in the same
  commit or delete the word.
- **Reproduce a reported bug before fixing it**, and keep the reproduction as
  the test. Every review finding on PRs #7 and #9 was reproduced first; two
  turned out to be worse than reported, which the fix would have missed.

### Fixtures, fakes, and environment traps

- Fixture PDFs are generated at run time with reportlab in
  `packages/rp-pdf/tests/conftest.py`; every docx fixture and template is
  built in `packages/rp-docx/tests/conftest.py`; every pptx fixture and
  template is built in `packages/rp-pptx/tests/conftest.py` — never commit
  binary fixtures. A committed `.dotx`/`.potx` is a licensing question, an
  opaque diff, and a debugging hazard at once: when a test fails you cannot
  tell whether the code or the template changed. Fixtures python-docx/
  python-pptx cannot themselves produce (tracked changes, comments) are still
  generated, not committed — by writing the XML parts by hand onto an
  otherwise-generated package in `conftest.py`.
- VLM tests run against a fake OpenAI-compatible HTTP server on a local thread
  (`FakeVlm`) — no network, no real keys. VLM env vars (`RP_PDF_VLM_*`,
  `OPENAI_API_KEY`) are cleared via the `vlm_env` fixture; always pass
  `cache_dir=tmp_path` in AI tests so `~/.cache/rp-pdf` is untouched.
- AI-pass responses are cached keyed on file hash + page + model +
  `PROMPT_VERSION` (+ dpi + outline context). Bump `PROMPT_VERSION` in
  `markdown.py` whenever the prompt or request shape changes.
- ruff is **pinned to an exact version** in the root dev group, and its lint
  `select` is stated explicitly (`E, F, W, I, UP, B`). Both are deliberate: a
  `>=` floor lets the gate change what it enforces whenever a release widens
  ruff's implicit default, which is what forced the Phase 0 workaround. Bump the
  pin in its own commit, with the resulting fixes.
- **Don't test option registration through rendered `--help`.** rich detects
  `CI`/`GITHUB_ACTIONS` and colorizes, and its option highlighter emits an
  option's leading hyphen as its own span, so the literal `--describe` is in the
  output locally and absent on CI. Read the parsed command instead:
  `typer.main.get_command(app).commands[name].params`, unioning `.opts` and
  `.secondary_opts`. (Rendered output is the right representation when help
  *rendering itself* is what you are testing — then normalize the ANSI first.)

  **A negative check is the dangerous direction, not the safe one.**
  `"--json" not in help_text` is true on CI whether or not the flag exists, so
  it passes for the wrong reason precisely where the merge gate runs.
  `test_no_json_flag_on_any_command` had that shape: planting a real `--json` on
  `text` failed it locally and *passed* it under CI rendering, which means the
  suite's "no `--json` anywhere" invariant was unenforced on the only run that
  gates a merge. Fixed to read parameters. Any absence assertion needs a
  representation where the thing could actually have appeared.
- **Run the suite once as CI sees it** before pushing anything that touches
  output: `CI=true GITHUB_ACTIONS=true uv run pytest -q`.
- **The dev container runs as root, so file permissions do not deny it
  anything.** A test that expects `PermissionError` from a `0o500` directory
  fails with "DID NOT RAISE" here and passes on CI. Guard it —
  `@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, ...)` — rather
  than deleting it; CI runs as a normal user and will exercise it.
- Tests that need a terminal (progress rendering, `isatty` behavior) can get one
  with `pty.fork`; `subprocess` with `capture_output` never will. A helper that
  applies carriage-return semantics to the captured bytes lets a test assert on
  what a terminal would *display* rather than on the escape sequence soup —
  see `rendered()` in `packages/rp-core/tests/test_progress.py`.

## Failure modes this repo has already hit

Each of these was a real defect found in review, generalized. They recur because
each one is locally reasonable; the specific fixes are in the package notes
above and the dev-notes.

- **A part's filename is not its position, and our own commands are what make
  that unsafe.** `reorder_slides` deliberately rewrites `p:sldIdLst` and leaves
  every part where it was, so `comment3.xml` is not slide 3's — a filename
  assumption elsewhere in the same package became a reachable data-corruption
  path (comments reported against inverted slides). Scanning `slideN.xml` until
  a gap has the same root cause: deletion leaves numbering non-contiguous. When
  one operation deliberately breaks an invariant, audit every reader of it.
- **Validating a proxy is worse than validating nothing**, because it looks like
  validation. Checking that a layout *name* exists and then dropping content
  into a layout with no matching placeholder produced exactly the silent wrong
  output the name check was there to prevent. Validate the thing you actually
  need, at the point you need it.
- **"The first one that looks right" is not a selector.** `_body_placeholder`
  took the first placeholder with a text frame and put bullets into the
  *picture* placeholder of PowerPoint's Picture-with-Caption layout. Match an
  allowlist of expected types.
- **Presence and placement are different questions with different
  reliability.** When deferring a feature (§7 modern comments), key the guard on
  what you can detect for certain — a content type is in the package — not on
  what you cannot — which slide it belongs to. A part that cannot be attributed
  is still unreadable, and must still fail loudly.
- **A suite-wide claim is a claim about every command.** The docs had
  `convert`/`render` writing artifacts *instead of* JSON when they do both, and
  named `markdown` the stdout exception without saying that its `-o` form
  behaves three different ways across the three packages. Conventions are
  written once and then hold for a dozen commands nobody re-checked. The claim
  also appeared in six files — `README.md`, three `docs/usage*.md`, and two
  package READMEs — so correcting one was not correcting it. Grep for the copies.
- **Sibling packages that look symmetric often are not.** Still true today:
  `RP_DOCX_TEMPLATE_DIR` splits on `os.pathsep` and searches ancestor repo
  roots, while `RP_PPTX_TEMPLATE_DIR` takes a single directory and looks only at
  `./templates`. Read both before documenting either as "the same".
- **A documentation change records a code gap; it does not fix it.** The
  asymmetry above was written up in `templates/README.md` as a known gap rather
  than patched inside a docs-only PR. Keep the scopes apart.
- **`Path.resolve()` follows symlinks, so a check *after* it is a check on the
  target, not on what the caller named.** `resolve_output` refused an existing
  path and a symlink — but only after resolving, so a *dangling* link passed
  both tests (the target does not exist and is not itself a link) and a write
  through it would have landed on a path nobody named. When a rule is about the
  name the caller used, check the name with `lstat` before you resolve it.
- **An enumerated invariant is complete on the day it is written and never
  again.** `rp-mcp`'s sandbox check walks the *registered* tool list rather than
  a list of tools to check, so a tool added later that forgets to resolve a path
  fails without anyone remembering. Two things make that real: the synthesized
  arguments must *pass* schema validation, or the call never reaches the body
  being tested, and a result the check cannot interpret must be reported as its
  own failure rather than crashed on.
- **A skill is a set of claims about a command line, so run every command in
  it.** Four commands in `skills/` were wrong on the first pass — written from
  the usage guides, consistent with their sibling commands, and non-existent.
  Review does not catch these; execution does.
- **Writes to a user's persistent file are all-or-nothing.** `Path.write_text`
  truncates before writing, so a failure part-way leaves a config that is empty
  or half-written — and worse when the caller merged the user's existing
  sections into what it is writing. Use `config._write_atomically`'s shape:
  complete temporary file in the same directory, fsync, one rename.

## Workflow

- Each phase (and any sizeable change) lands on its own feature branch, fully
  tested, then merges to `main` via PR.
- Run the full suite and both ruff commands before committing; keep
  `README.md`, `docs/usage.md`, and `ROADMAP.md` in sync with behavior in the
  same commit. A behavior claim usually lives in more than one of those, plus
  `docs/usage-docx.md`, `docs/usage-pptx.md`, `docs/usage-mcp.md`, the three
  `skills/*/SKILL.md`, and the package READMEs — grep the claim, don't just fix
  the file you were looking at. **A changed CLI flag or command name is a
  `skills/` change**, and the skills quote commands verbatim, so run them.
- A feature is: core/library function returning pydantic models + CLI wrapper +
  tests + `docs/usage.md` update.
- A phase or a batch of related work also gets a status note in `dev-notes/`,
  written for whoever picks it up next: what was asked, what shipped, and
  **every decision that went the other way first**. The corrections are the
  valuable part — `status-cli-ux-progress-and-config.md` is the current model.
  Link it from the `ROADMAP.md` entry.
