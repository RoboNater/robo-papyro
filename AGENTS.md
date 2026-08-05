# AGENTS.md — context for AI development sessions

`robo-papyro` is a document tooling suite giving agentic coding tools a stable,
scriptable interface to PDF and Office formats. It is **one repository holding
several independently versioned Python distributions**, managed as a uv
workspace.

| Distribution | Import | CLI | Purpose |
|---|---|---|---|
| `rp-core` | `rp_core` | — | Shared infrastructure: errors and exit codes, external-binary discovery, rendering, range specs, CLI conventions |
| `rp-pdf` | `rp_pdf` | `rp-pdf` | PDF read/extract/render (the former `pdfx`) |
| `rp-docx` | `rp_docx` | `rp-docx` | Word documents — **Phase 1, not built yet** |
| `robo-papyro` | `robo_papyro` | `rp` | Meta-distribution and umbrella dispatcher |

## Layout

```
packages/rp-core/src/rp_core/     errors, models, ranges, binaries, render, doctor, clikit
packages/rp-pdf/src/rp_pdf/       core, markdown, ocr, vlm_utils, models, config, cli
packages/robo-papyro/src/robo_papyro/   cli.py — the `rp` dispatcher
docs/specs/                       the governing specifications
dev-notes/                        investigation write-ups for fixed issues
templates/                        corporate .dotx/.docx templates (Phase 1)
```

Each package has its own `pyproject.toml` and its own `tests/`. Shared dev
dependencies, ruff config, and pytest config live in the **root**
`pyproject.toml`; no code lives at the root.

## The four rules that matter most

1. **One-way dependencies.** `rp-core` imports no leaf package, ever. Leaf
   packages (`rp-pdf`, `rp-docx`, …) never import each other. Only
   `robo-papyro` depends on leaves, and it reaches them through entry-point
   discovery rather than imports.
2. **Import from `rp-core`, don't reimplement.** Range-spec parsing, binary
   discovery, rasterization, error envelopes, and exit codes have exactly one
   implementation. If you are about to write `shutil.which`, a page-range
   parser, or an exception with an exit code, look in `rp_core` first.
3. **Core logic never prints and never imports typer.** Library functions
   return pydantic models; CLI modules do all formatting. (`rp_core.clikit` is
   the deliberate exception — it *is* the shared CLI layer.)
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
absent. Tests must **never** require LibreOffice — mock the subprocess.

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
  Secrets (API key, `--password`) are never read from the config file.
- Heavy/optional deps are imported lazily — `openai` must never be imported
  unless the AI pass runs.
- Errors subclass `rp_pdf.errors.RpPdfError`, which is parented onto
  `rp_core.errors`; that is what gives each one its exit code and the `type` its
  envelope reports. Nothing raises a bare builtin: a missing file is
  `MissingFileError`, which is also a `FileNotFoundError` for library callers.

### robo-papyro

`cli.py` reaches leaves through entry-point discovery only — see the
invariants table above. `rp <name>` gets whatever the leaf registered as its
typer app, which means argv preprocessing done by a leaf's console script
(rp-pdf's `[default].command` rewriting) does not apply to `rp pdf FILE.pdf`.

## Licensing

**Approved:** python-docx (MIT), lxml (BSD-3), mammoth (BSD-2), pypdf (BSD-3),
pdfplumber (MIT), pdf2image (MIT), openpyxl (MIT), python-pptx (MIT), typer
(MIT), pydantic (MIT), Pillow (MIT-CMU), pytest/ruff (MIT).

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

- Fixture PDFs are generated at run time with reportlab in
  `packages/rp-pdf/tests/conftest.py` — never commit binary fixtures.
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

## Workflow

- Each phase (and any sizeable change) lands on its own feature branch, fully
  tested, then merges to `main` via PR.
- Run the full suite and both ruff commands before committing; keep
  `README.md`, `docs/usage.md`, and `ROADMAP.md` in sync with behavior in the
  same commit.
- A feature is: core/library function returning pydantic models + CLI wrapper +
  tests + `docs/usage.md` update.
