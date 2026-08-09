# robo-papyro

A document tooling suite giving agentic coding tools a stable, scriptable
interface to PDF and Office document formats. JSON-first: structured read
commands emit a complete pydantic model to stdout by default, so a tool with
no native document capability can operate on files through a plain CLI.
`convert` and `render` follow the same convention — they write the requested
artifacts to disk and report JSON metadata (what was written, and where) to
stdout by default. `markdown` is the one command whose stdout differs by
design: with no `-o`/`--out` it prints Markdown itself, not JSON, so it
composes with shell pipelines; given `-o` it writes the file, and what it
prints instead of the Markdown varies by package — see each package's usage
guide.

**Status:** Phases 0, 0.5, 1, 2, and 2.5 are complete — `rp-core`, `rp-pdf`,
`rp-docx`, `rp-pptx`, and `rp-mcp` all ship. `rp-xlsx` (Phase 3) remains future
work. See [ROADMAP.md](ROADMAP.md) for details.

One repository, several independently versioned distributions:

| Distribution | Import | CLI | Status |
|---|---|---|---|
| [`rp-core`](packages/rp-core) | `rp_core` | — | Shared infrastructure |
| [`rp-pdf`](packages/rp-pdf) | `rp_pdf` | `rp-pdf`, `rp pdf` | PDF read/extract/render |
| [`rp-docx`](packages/rp-docx) | `rp_docx` | `rp-docx`, `rp docx` | Word read/create/edit |
| [`rp-pptx`](packages/rp-pptx) | `rp_pptx` | `rp-pptx`, `rp pptx` | PowerPoint read/create/edit |
| [`rp-mcp`](packages/rp-mcp) | `rp_mcp` | `rp-mcp`, `rp mcp` | MCP servers for the three above |
| [`robo-papyro`](packages/robo-papyro) | `robo_papyro` | `rp` | Umbrella dispatcher |

Dependency direction is strictly one-way: leaf packages never import each
other, `robo-papyro` reaches the leaves through entry-point discovery, and
`rp-mcp` sits above all three — it imports them, nothing imports it back.
`rp-core` knows nothing PDF- or format-specific, but it does own the generic,
format-agnostic mechanics every OOXML leaf needs — package zip read/repack,
content-type rewriting, and a shared Markdown block/inline parser
(`rp_core.ooxml`, `rp_core.markdown`); WordprocessingML and PresentationML
knowledge itself stays in `rp-docx` and `rp-pptx`. Permissive licenses only —
no PyMuPDF/AGPL, no `docxtpl`/LGPL, no pandoc/GPL. External binaries
(LibreOffice, poppler) are optional and invoked only as subprocesses.

Full usage guides: [docs/usage.md](docs/usage.md) for `rp-pdf`,
[docs/usage-docx.md](docs/usage-docx.md) for `rp-docx`,
[docs/usage-pptx.md](docs/usage-pptx.md) for `rp-pptx`,
[docs/usage-mcp.md](docs/usage-mcp.md) for `rp-mcp`, whose security model and
deliberate limitations are in [docs/security-mcp.md](docs/security-mcp.md). The
governing specifications are in [docs/specs/](docs/specs). Agent skills for the
three CLIs are in [skills/](skills).

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

`robo-papyro` installs the whole suite, `rp-mcp` included, so `rp mcp` is there
in a plain `pip install robo-papyro`. That does bring the MCP SDK and an ASGI
stack along with the document toolkit — the servers are what the suite is for
when the caller is an agent, and an integration you have to know to ask for is
one most people never find. Installing a server is not running one: stdio is
the only transport, and nothing starts it implicitly. A leaf on its own stays
lean — `uv pip install rp-pdf` still pulls nothing MCP-related.

## rp-pdf

`--pages` accepts `all`, `5`, `3-7`, `-4` (up to 4), `7-` (7 to the end), or
`1,3-5,9`. When the PDF defines page labels
(ebook-style `cover`, `i`-`xx`, restarting at `1` for content), specs are interpreted
against those labels — matching what PDF readers display; pass `--physical` for
plain 1-based physical numbering.
Output is JSON on stdout by default — `render` writes image files and reports
JSON metadata about them, and `markdown` is the exception, printing Markdown
itself when no `-o` is given. Errors put a message and then an error
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

### Watching a long run

A `--ai` conversion of a few hundred pages is minutes of mostly waiting, so the
commands that do real work (`text`, `tables`, `search`, `images`, `markdown`,
`render`) describe themselves and report progress:

```console
$ rp-pdf markdown report.pdf --ai --jobs 4 -o report.md
rp-pdf markdown — report.pdf
  pages      all
  engine     poppler (needs pdftotext installed)
  AI review  on, model gpt-4o-mini at https://openrouter.ai/api/v1; 4 concurrent, pages rendered at 150 dpi
  OCR        off — pages with no text layer stay empty (--ocr to transcribe them)
  cache      on — responses reused from ~/.cache/rp-pdf
  output     report.md
✔ Finding tables 142/142 [3s]
⠹ AI review 27/142 [1m48s]
```

The description checks your flags *before* the bill, naming what is off as well
as what is on; the progress line is ticked by a background thread, so the clock
keeps moving even when the work is blocked on a stalled network read. Both go to
**stderr only** and are on by default *only when stderr is a terminal* — an
agent or a pipeline sees exactly what it saw before. `--describe`/`--progress`
force them on, `--no-describe`/`--no-progress` off, and `[ui]` in the config
file sets them for good. `rp-docx`/`rp-pptx` `convert` and `render` take the
same two options.

### Configuration file

Any `rp-pdf` option can be given a persistent default in an optional TOML config
file, so a bare `rp-pdf FILE.pdf` (just the PDF path, no subcommand) finds the
config and runs the action it prescribes. Two fixed locations, both optional and
both applying at once: a **project** file named `rp-pdf.toml` in the current
directory or any parent, and a **user** file at
`~/.config/rp-pdf/config.toml`.

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

[ui]                          # progress line and job description
progress = true               # default for both: on only when stderr is a terminal
```

You don't have to write it by hand. `--save-config rp-pdf.toml` on any run
writes the options *you passed* — after the run succeeds, so what is recorded is
a command line known to have worked. Built-in defaults, environment values, and
`markdown -o FILE` (this document's output, not the next one's) are left out:

```sh
uv run rp-pdf markdown report.pdf --ai --model gpt-4o-mini --jobs 4 --save-config rp-pdf.toml
uv run rp-pdf markdown other.pdf     # same options, no flags needed
```

Every option resolves by precedence **flag → environment variable → config file
→ built-in default**. Because flags win, boolean options are paired so you can
turn a config-enabled feature back off on the command line — e.g. `--no-ai`
overrides `[markdown] ai = true`, and every `--flag` has a matching `--no-flag`.
VLM keys set in a command section (say `[markdown] model`) override the same key
in `[vlm]` for that command.

Discovery: `--config PATH` (or `$RP_PDF_CONFIG`) names one file and, when given,
is the only file read. Otherwise both auto-discovered files apply — the nearest
`rp-pdf.toml` walking up from the current directory, and
`~/.config/rp-pdf/config.toml` — merged per key with the project file winning.
Having neither is normal. A malformed file reports a clear error rather than a
traceback. Full details in
[docs/usage.md](docs/usage.md#configuration-file).

The default-command shortcut lives in the `rp-pdf` console script, so it applies
to `rp-pdf FILE.pdf` but not to `rp pdf FILE.pdf`, which needs an explicit
subcommand.

## rp-docx

Reads, creates, and edits Word documents. `.docx` and `.dotx` are accepted
everywhere; no external binary is needed for any read or write path.

```sh
uv run rp-docx index report.docx                 # counts, headings, properties
uv run rp-docx text report.docx --runs           # paragraphs with formatting
uv run rp-docx tables report.docx --format csv -o ./tables
uv run rp-docx comments report.docx              # anchors and resolved state
uv run rp-docx changes report.docx               # tracked insertions/deletions

uv run rp-docx create -o out.docx --from-markdown notes.md --template memo
uv run rp-docx replace contract.docx --map ./values.json -o filled.docx
uv run rp-docx template memo --context ./client.json -o letter.docx
uv run rp-docx accept draft.docx -o final.docx
```

Two things it does that a naive implementation gets wrong, quietly:

- **Replacement works across run boundaries.** Word routinely stores
  `{{ client }}` as `{{ cli` + `ent }}` for reasons unrelated to meaning, so a
  plain string replace finds nothing and reports success. It also reaches table
  cells, text boxes, headers, footers, footnotes, and endnotes — body-only
  replacement is the classic silent bug.
- **A missing style is an error, not a fallback.** House templates rename Word's
  styles, so Markdown conversion maps through an optional
  `<template>.stylemap.json`. If a mapped style is absent, `rp-docx` says so and
  lists what the template has — a silent substitution produces documents that
  look wrong in ways nobody notices until review.

Templating is native (`{{ key }}` and `{{ key.subkey }}`, no expression
evaluation and no Jinja) because `docxtpl` is LGPL-2.1-only and therefore a
blocker rather than a preference.

Confidential templates never enter the repository. `rp-docx templates manifest`
describes a template's *shape* — style names, page geometry, presence flags, and
no content whatsoever — and `templates synthesize` rebuilds a structurally
equivalent `.dotx` from that JSON, so CI exercises the real template's shape
while the file itself stays where it is.

Full guide: [docs/usage-docx.md](docs/usage-docx.md).

## rp-pptx

Reads, creates, and edits PowerPoint decks. `.pptx` and `.potx` are accepted
everywhere; no external binary is needed for any read or write path.

```sh
uv run rp-pptx index deck.pptx                   # geometry, counts, layouts, titles
uv run rp-pptx text deck.pptx --slides 1-3       # paragraphs with outline levels
uv run rp-pptx tables deck.pptx --format md      # tables, with their merge spans
uv run rp-pptx notes deck.pptx                   # speaker notes
uv run rp-pptx markdown deck.pptx -o deck.md     # the deck as markdown

uv run rp-pptx create -o out.pptx --from-markdown notes.md --template house
uv run rp-pptx replace deck.pptx --map ./values.json -o filled.pptx
uv run rp-pptx slides reorder deck.pptx --order 3,1,2 -o reordered.pptx
```

Three things it does that a naive implementation gets wrong, quietly:

- **Replacement works across run boundaries**, for the same reason it must in
  Word: DrawingML splits `{{ client }}` across `a:r` runs as arbitrarily as
  WordprocessingML does. It reaches table cells, notes slides, and shapes nested
  inside groups — and where two placeholders overlap, the longer wins, so the
  result never depends on the order the keys happened to arrive in.
- **A missing layout is an error, not a fallback**, checked at the point of use.
  House decks rename PowerPoint's layouts, so Markdown roles map through an
  optional `<template>.layoutmap.json`; a deck with no section breaks does not
  need a section layout to exist, but one that reaches for a missing layout is
  told which, and what the template does have.
- **Markdown maps onto slides deterministically.** A document is a scroll and a
  deck is a sequence: the first `#` is the title slide, later ones are section
  breaks, `##` opens a content slide, `---` breaks one explicitly, and an HTML
  comment becomes speaker notes. `rp-pptx markdown` emits the same dialect, so a
  deck round-trips.

Confidential templates never enter the repository, exactly as with `rp-docx`:
`templates manifest` describes a template's *shape* — layout names, placeholder
inventory, geometry, presence flags, no content — and `templates synthesize`
rebuilds a structurally equivalent `.potx` from that JSON.

Modern threaded comments are not supported yet; a deck carrying them fails
loudly rather than reporting an empty list. Classic comments are read normally.

Full guide: [docs/usage-pptx.md](docs/usage-pptx.md).

## rp-mcp

The same three toolkits as MCP tools, for a client that has no shell. One
server per format, or all three at once, over stdio:

```sh
uv run rp-mcp serve --root ~/documents                    # read-only
uv run rp-mcp serve --root ~/documents --write-root ~/documents/out
uv run rp-pdf-mcp --root ~/documents                      # one format
uv run rp-mcp tools --server docx --root .                # the surface, as JSON
```

Every path in every tool call is resolved through a sandbox before a leaf sees
it: reads are confined to `--root` directories (checked on the resolved path,
so `..` and symlinks cannot climb out), writes need an explicit `--write-root`,
and nothing is ever overwritten — there is no `--in-place` over MCP to opt
into. Without a write root the file-creating tools are **not registered at
all**, so an agent sees a shorter tool list rather than tools that always fail.

Failures carry the suite's error envelope as the last line of the tool error,
with the same exit codes the CLIs use. Rendering, the AI review pass, and every
non-stdio transport are deliberately not exposed.

Full guide: [docs/usage-mcp.md](docs/usage-mcp.md). **Before pointing a server
at anything sensitive**, read
[docs/security-mcp.md](docs/security-mcp.md) — the threat model, and what the
sandbox explicitly does not protect against.

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

```python
from pathlib import Path
from rp_docx import get_index, get_text, create, replace_text, fill_template

index = get_index(Path("report.docx"))                   # DocumentIndex
paras = get_text(Path("report.docx"), runs_wanted=True)  # list[Paragraph]
create(Path("out.docx"), markdown="# Title", template="memo")
result = replace_text(Path("in.docx"), {"{{ k }}": "v"}, output=Path("out.docx"))
filled = fill_template("memo", {"client": {"name": "Ada"}}, Path("letter.docx"))
```

```python
from pathlib import Path
from rp_pptx import get_index, get_text, create, replace_text, reorder_slides

index = get_index(Path("deck.pptx"))                     # PresentationIndex
slides = get_text(Path("deck.pptx"), slides="1-3")       # list[SlideText]
create(Path("out.pptx"), markdown="# Title", template="house")
result = replace_text(Path("in.pptx"), {"{{ k }}": "v"}, output=Path("out.pptx"))
reorder_slides(Path("deck.pptx"), [3, 1, 2], output=Path("out.pptx"))
```

```python
from rp_mcp import Sandbox, build_server

build_server(Sandbox(roots=["/docs"], write_root="/docs/out")).run(transport="stdio")
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

PDF, Word, and PowerPoint test fixtures — including templates — are generated
at run time; no binary fixtures are committed. Tests that need poppler skip
automatically when it is not installed. LibreOffice-dependent tests use a
functional probe (`requires_soffice` checks that `soffice` can actually
*convert*, not merely that the binary exists — some containers ship a
`soffice` that fails every conversion) and skip when it can't; no test ever
requires LibreOffice to pass.

See [AGENTS.md](AGENTS.md) for the conventions that govern changes here.
