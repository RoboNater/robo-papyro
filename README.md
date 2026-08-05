# robo-papyro

A document tooling suite giving agentic coding tools a stable, scriptable
interface to PDF and Office document formats. JSON-first: every read command
emits a complete pydantic model, so a tool with no native document capability
can operate on files through a plain CLI.

One repository, several independently versioned distributions:

| Distribution | Import | CLI | Status |
|---|---|---|---|
| [`rp-core`](packages/rp-core) | `rp_core` | — | Shared infrastructure |
| [`rp-pdf`](packages/rp-pdf) | `rp_pdf` | `rp-pdf`, `rp pdf` | PDF read/extract/render |
| `rp-docx` | `rp_docx` | `rp-docx`, `rp docx` | Phase 1 — not built yet |
| [`robo-papyro`](packages/robo-papyro) | `robo_papyro` | `rp` | Umbrella dispatcher |

Dependency direction is strictly one-way: `rp-core` knows nothing about PDF or
OOXML, leaf packages never import each other, and `robo-papyro` reaches the
leaves through entry-point discovery. Permissive licenses only — no
PyMuPDF/AGPL, no `docxtpl`/LGPL, no pandoc/GPL. External binaries (LibreOffice,
poppler) are optional and invoked only as subprocesses.

See [docs/usage.md](docs/usage.md) for the full usage guide with examples, and
[docs/specs/](docs/specs) for the governing specifications.

## Setup

Managed with [uv](https://docs.astral.sh/uv/):

```sh
uv sync                  # installs every package in the workspace, editable
uv sync --all-extras     # adds the optional VLM dependencies
```

Text extraction (default engine) and page rendering additionally require
[poppler](https://poppler.freedesktop.org/):

- Linux: `apt install poppler-utils`
- macOS: `brew install poppler`
- Windows: `winget install oschwartz10612.Poppler`

If poppler is not on `PATH`, point `RP_POPPLER_PATH` (or `--poppler-path`) at its
`bin` directory. LibreOffice (`soffice`) is needed only for Office-format
conversion and rendering; `RP_SOFFICE_PATH` locates it if it is not on `PATH`.

No external tool runs unbounded: every invocation is killed after
`RP_SUBPROCESS_TIMEOUT` seconds, or 600 if it is unset, and reports exit **3**.
Raise it for genuinely large documents.

```sh
uv run rp doctor         # what is installed, and how to install what is not
```

## The `rp` umbrella

`rp` dispatches to whichever packages are installed:

```sh
uv run rp --help                 # lists only what is installed
uv run rp doctor                 # capability report across the suite
uv run rp pdf index FILE         # identical to `rp-pdf index FILE`
```

Installing a new package (say `rp-xlsx`) makes it appear under `rp`
automatically; nothing in `robo-papyro` changes.

## rp-pdf

`--pages` accepts `all`, `5`, `3-7`, or `1,3-5,9`. When the PDF defines page labels
(ebook-style `cover`, `i`-`xx`, restarting at `1` for content), specs are interpreted
against those labels — matching what PDF readers display; pass `--physical` for
plain 1-based physical numbering.
Output is JSON on stdout by default; errors put a message and then an error
envelope — `{"error": {"type", "message", "hint", "exit_code"}}` — on stderr, and
exit **1** for an input error, **2** for a missing external binary, **3** for an
unreadable PDF. Encrypted PDFs take `--password`.

```sh
uv run rp-pdf index  FILE                          # document index as JSON
uv run rp-pdf text   FILE --pages 3-7 [--layout]   # text; --plain for raw, --engine to pick extractor
uv run rp-pdf search FILE "query" [--regex]        # find text; hits with page context
uv run rp-pdf tables FILE --pages all [--csv DIR]  # tables as JSON, or one CSV per table
uv run rp-pdf images FILE --pages all --out DIR    # extract embedded images
uv run rp-pdf render FILE --pages 1-3 --out DIR --dpi 200 --format png
uv run rp-pdf markdown FILE -o out.md [--images-dir media] [--ai]  # Markdown conversion
uv run rp-pdf doctor                               # poppler capability report
```

Text extraction defaults to poppler's `pdftotext` because it segments words
correctly on PDFs that encode word gaps as glyph positioning rather than space
characters; `--engine pypdf` / `--engine pdfplumber` select in-process
extractors that avoid the subprocess but can run words together on such files.

`markdown` converts pages to Markdown (prose, pipe tables, image links, with
page-provenance comments). `--ai` adds a review pass where a vision-language
model — any OpenAI-compatible API — checks each page's draft against the
rendered page image and fixes structure. `--outline-headings` and
`--outline-context` (with `--ai`) use the PDF's outline to get heading levels
right on pages extracted mid-document; see
[docs/usage.md](docs/usage.md#rp-pdf-markdown--convert-to-markdown) for
configuration. The AI pass needs the optional dependencies:
`uv sync --extra ai`.

### Configuration file

Any `rp-pdf` option can be given a persistent default in an optional TOML config
file, so a bare `rp-pdf FILE.pdf` (just the PDF path, no subcommand) finds the
config and runs the action it prescribes:

```toml
[default]
command = "markdown"          # what `rp-pdf FILE.pdf` runs; omit → "index"

[markdown]                    # per-command defaults
ai = true
engine = "pypdf"
outline_headings = true

[text]
engine = "pypdf"
layout = true

[vlm]                         # shared VLM settings (model / base_url / ...)
model = "gpt-4o-mini"
base_url = "https://openrouter.ai/api/v1"
organization = "org-abc123"
cache_dir = "~/.cache/rp-pdf"
# the API key is never read from the config file — it stays in the environment
# (RP_PDF_VLM_API_KEY / OPENAI_API_KEY).
```

Every option resolves by precedence **flag → environment variable → config file
→ built-in default**. Because flags win, boolean options are paired so you can
turn a config-enabled feature back off on the command line — e.g. `--no-ai`
overrides `[markdown] ai = true`, and every `--flag` has a matching `--no-flag`.
VLM keys set in a command section (say `[markdown] model`) override the same key
in `[vlm]` for that command.

The file is discovered, in order: an explicit `--config PATH` (or
`$RP_PDF_CONFIG`); the nearest `rp-pdf.toml` walking up from the current
directory; then `~/.config/rp-pdf/config.toml`. When both a project and a user
file are found they merge per key with the project file winning. A malformed
file reports a clear error rather than a traceback.

The default-command shortcut lives in the `rp-pdf` console script, so it applies
to `rp-pdf FILE.pdf` but not to `rp pdf FILE.pdf`, which needs an explicit
subcommand.

## Library

```python
from rp_pdf import core

index = core.get_index("doc.pdf")            # DocumentIndex
texts = core.get_text("doc.pdf", "1-3")      # list[PageText]
tables = core.get_tables("doc.pdf", "all")   # list[Table]
images = core.get_images("doc.pdf", "all", out_dir=None)  # list[ImageInfo]
rendered = core.render_pages("doc.pdf", "1", "out/", dpi=200)  # list[RenderedPage]

from rp_pdf.markdown import to_markdown
result = to_markdown("doc.pdf", images_dir="media")  # MarkdownResult
```

Core functions return pydantic models; serialize with `.model_dump_json()`. The
libraries never print and never import typer — CLI modules do all formatting.

## Development

```sh
uv run pytest                        # every package
uv run pytest packages/rp-pdf        # one package
uv run ruff check packages
uv run ruff format packages
```

Test PDFs are generated at run time; no binary fixtures are committed. Tests
that need poppler skip automatically when it is not installed, and no test ever
requires LibreOffice — the subprocess is mocked.

See [AGENTS.md](AGENTS.md) for the conventions that govern changes here.
