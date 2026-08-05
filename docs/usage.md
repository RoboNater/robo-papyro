# rp-pdf Usage Guide

`rp-pdf` extracts structured information from PDF files. It is JSON-first: every
command prints JSON to stdout by default so output can be piped into other tools.
The same functionality is available as a Python library (`rp_pdf.core`).

`rp-pdf` is one package of the [robo-papyro](../README.md) suite; its commands
are also reachable as `rp pdf ...`. Shared behavior — page-spec parsing, exit
codes, external-binary discovery, rasterization — comes from `rp-core` and is
identical across the suite.

## Conventions

- **`--pages`** accepts:

  | Spec        | Meaning                          |
  |-------------|----------------------------------|
  | `all`       | every page (default)             |
  | `5`         | page 5                           |
  | `3-7`       | pages 3 through 7, inclusive     |
  | `1,3-5,9`   | mixed list; deduplicated, sorted |

- **Page numbering follows the document's page labels when it has them** (see
  [Page labels](#page-labels) below); otherwise pages are numbered 1-based from
  the first physical page. `--physical` forces 1-based physical numbering either way.

- **Errors** print a human-readable message to stderr and `{"error": "..."}` to
  stdout, so scripted callers always get parseable JSON. The exit code says what
  kind of failure it was:

  | Code | Meaning |
  |---|---|
  | `0` | success |
  | `1` | user or input error — bad page spec, bad option, missing file |
  | `2` | a required external binary is absent (run `rp-pdf doctor`) |
  | `3` | the file is corrupt, encrypted-unreadable, or not a PDF |

  These codes are shared across the whole robo-papyro suite.
- **Encrypted PDFs**: pass `--password PW` (library: `password="PW"`). Missing or
  wrong passwords produce a clear error.

## CLI

Run via `uv run rp-pdf ...` from the project directory (or just `rp-pdf ...` inside an
activated environment). `rp-pdf --help` and `rp-pdf COMMAND --help` show full options.

A [config file](#configuration-file) can supply defaults for any option, and lets
`rp-pdf FILE.pdf` (no subcommand) run a prescribed action.

Every command is also reachable through the suite's umbrella CLI as
`rp pdf COMMAND ...` — the same code path, byte-identical output. The one
exception is the no-subcommand shortcut: `rp-pdf FILE.pdf` runs the config's
default command, but `rp pdf FILE.pdf` does not, because that rewriting lives in
the `rp-pdf` console script rather than in the command group `rp` discovers.

### `rp-pdf doctor` — check external tools

```sh
uv run rp-pdf doctor            # table of poppler tools, versions, and paths
uv run rp-pdf doctor --json     # list[Capability] for programmatic callers
```

Reports whether each optional external binary is installed, its version, and
where it was found; anything missing gets install instructions on stderr. `rp
doctor` does the same across every installed package, and additionally reports
on LibreOffice.

### `rp-pdf index` — document overview

```sh
uv run rp-pdf index report.pdf
```

Returns page count, metadata (title, author, dates), the bookmark/outline tree, and
a per-page summary:

```json
{
  "path": "book.pdf",
  "page_count": 38,
  "has_page_labels": true,
  "metadata": { "title": "Quarterly Report", "author": "...", ... },
  "outline": [
    { "title": "Chapter 1", "physical_page": 28, "labeled_page": "1", "children": [] },
    ...
  ],
  "pages": [
    { "physical_page": 1, "labeled_page": "cover", "width": 612.0, "height": 792.0,
      "rotation": 0, "has_text": true },
    ...
  ]
}
```

`has_text: false` usually means a scanned/image-only page. Such pages can be
transcribed using OCR (see `rp-pdf markdown --ocr` below).
When the document defines page labels, `has_page_labels` is `true` and each page
summary includes its `label` — handy for seeing how labels map to physical positions.

### `rp-pdf text` — extract text

```sh
uv run rp-pdf text report.pdf --pages 3-7            # JSON: [{physical_page, labeled_page,
                                                   #         text, has_text}, ...]
uv run rp-pdf text report.pdf --pages 1 --plain      # raw text only
uv run rp-pdf text report.pdf --pages all --layout   # preserve columns/indentation
uv run rp-pdf text report.pdf --engine pypdf         # in-process extractor (see below)
```

The default extractor shells out to poppler's `pdftotext` (see
[Poppler](#poppler) below), because it is the only widely available extractor
that reliably segments words on PDFs that encode word gaps as glyph positioning
instead of space characters — on such files pure-Python extractors silently run
words together (`Whetheryouarelooking...`), which poisons search and any
downstream text processing.

`--engine pypdf` or `--engine pdfplumber` (library: `engine="pypdf"`) select an
in-process extractor instead: faster (no subprocess) and poppler-free, but only
safe when you know your PDFs encode spaces conventionally, or when approximate
text is acceptable.

`--layout` preserves horizontal positioning (columns, indentation) and works
with every engine — useful for multi-column pages or when reading order matters.

### `rp-pdf tables` — extract tables

```sh
uv run rp-pdf tables report.pdf --pages all            # JSON: [{physical_page, labeled_page,
                                                     #         index, rows}, ...]
uv run rp-pdf tables report.pdf --pages 2 --csv out/   # one CSV file per table
```

`rows` is a list of rows of cell strings; empty cells are `null` in JSON. With
`--csv`, one file is written per table and the JSON output lists the written paths.
Detection works best on ruled (lined) tables.

### `rp-pdf search` — find text

```sh
uv run rp-pdf search book.pdf "gradient descent"              # JSON hits
uv run rp-pdf search book.pdf "gradient descent" --plain      # page 141 (pp 168): …[match]…
uv run rp-pdf search book.pdf "loss function" --pages 1-50    # restrict to labeled pages
uv run rp-pdf search book.pdf "chapter \d+" --regex           # regex on raw page text
```

Each hit reports `physical_page`, `labeled_page`, the exact `match`, and
`before`/`after` context (default 80 characters each side, `--context` to adjust).
Plain queries are matched with whitespace normalized, so phrases match across line
breaks in the extracted text; `--regex` matches the raw text instead. Matching is
case-insensitive unless `--case-sensitive`. Results are capped at `--max` hits
(default 100) with a notice on stderr when the cap is reached. No matches is an
empty list, not an error. Search reads page text through the same engines as
`rp-pdf text` (`--engine`, default poppler) — with a mis-segmenting engine, phrase
queries can silently miss text whose spaces were dropped.

### `rp-pdf images` — embedded images

```sh
uv run rp-pdf images report.pdf --pages all             # metadata only
uv run rp-pdf images report.pdf --pages all --out imgs/ # also save the image files
```

Reports name, page, pixel size, and format for each embedded image. With `--out`,
files are saved and `saved_path` is filled in.

### `rp-pdf markdown` — convert to Markdown

```sh
uv run rp-pdf markdown report.pdf                        # Markdown on stdout
uv run rp-pdf markdown report.pdf -o report.md           # write a file
uv run rp-pdf markdown report.pdf -o report.md --images-dir media
uv run rp-pdf markdown report.pdf --json                 # full MarkdownResult as JSON
uv run rp-pdf markdown report.pdf -o report.md --ai --model gpt-4o-mini
uv run rp-pdf markdown report.pdf --ai --ocr --model gpt-4o-mini  # with OCR for scanned pages
```

Converts pages to Markdown in up to three stages.

**Stage 1 (always runs)** assembles each page programmatically: prose text via
the same engines as `rp-pdf text` (`--engine`, default poppler), tables as
GitHub-flavored pipe tables placed in flow position (table content is cropped
out of the prose by bounding box, so nothing appears twice), and — with
`--images-dir DIR` — embedded images extracted there and referenced with links
relative to the directory's parent, so put it next to your output file. Pages
are joined with provenance comments (`<!-- page 30 (pp 38) -->`), and pages
with no text layer become `<!-- page N: no text layer -->` placeholders.

**Stage 2 (`--ai`)** sends each page's draft plus the rendered page image to a
vision-language model over any OpenAI-compatible API (OpenAI, OpenRouter,
Ollama, LM Studio, vLLM, ...), which fixes structure: reading order, heading
levels, table shape, split/merged words. The draft's characters are treated as
ground truth — the model restructures, it does not re-transcribe, which
prevents hallucinated "corrections" to numbers and names. Responses are
validated (code fences stripped, suspiciously short output rejected); any
per-page failure keeps the programmatic draft, sets `ai_refined: false`, and
prints a warning to stderr.

**Stage 3 (`--ai --ocr`)** transcribes pages without a text layer using the
same VLM. Scanned pages are rendered and sent for OCR with a
transcription-focused prompt (the image is the only source here, so the model
is told to transcribe exactly and mark illegible passages rather than guess).
Successful transcriptions replace the `no text layer` placeholder and set
`ocr_transcribed: true` on the page in JSON output; failures keep the
placeholder and print a warning to stderr. Configuration, response validation,
and the response cache are shared with Stage 2, and each stage only renders
its own pages (refinement renders pages with text, OCR renders pages
without). Run `rp-pdf validate-vlm-ocr` first to check that your model handles
OCR well.

**Outline-aware headings (opt-in).** Heading levels are otherwise page-local:
stage 1 emits no headings, and the AI pass judges levels from the single page
image, so a mid-document `##` section can come out as `#`. Two options anchor
levels to the document's outline (PDF bookmarks); both are no-ops on documents
without one:

- `--outline-headings` (stage 1, no AI needed) promotes lines that match an
  outline title on their destination page to headings leveled by outline depth
  (top level = `#`). Matching is conservative — normalized-exact or
  near-exact — so prose is never accidentally promoted; titles that don't
  appear as on-page text are left alone.
- `--outline-context` (requires `--ai`) tells the model each page's position
  in the outline (section path plus any entries pointing at the page) so the
  levels it assigns follow the document hierarchy instead of the page's visual
  scale. Changes the cache key, so toggling it never reuses stale responses.

Both are currently opt-in while we evaluate whether they should become default
behavior.

Configuration:

- `--model` or `RP_PDF_VLM_MODEL` — the model name (required with `--ai`).
- `--base-url` or `RP_PDF_VLM_BASE_URL` — the endpoint; omit for OpenAI itself.
- API key from `RP_PDF_VLM_API_KEY`, falling back to `OPENAI_API_KEY`. With a
  `--base-url` set, a missing key is allowed (local servers ignore it).
- `--organization` or `RP_PDF_VLM_ORG` — API organization ID, sent only when set.
  For OpenAI-hosted accounts scoped to a specific org; leave unset for
  local/third-party servers.
- `--jobs N` runs N VLM requests concurrently; `--dpi` sets the review image
  resolution (default 150).
- Accepted responses are cached (default `~/.cache/rp-pdf`, `--cache-dir` or
  `RP_PDF_CACHE_DIR` to move it, `--no-cache` to skip) keyed on file hash, page,
  model, and prompt version — an interrupted run on a large document resumes
  without re-billing.

The AI pass requires poppler (page rendering) and the optional `ai` dependency
group: `uv sync --extra ai` (or `pip install rp-pdf[ai]`).

### `rp-pdf validate-vlm-ocr` — test your OCR setup

```sh
uv run rp-pdf validate-vlm-ocr --model gpt-4o-mini
uv run rp-pdf validate-vlm-ocr --model qwen2.5-vl --base-url http://localhost:11434/v1
```

Checks that your VLM configuration can actually OCR before you spend money on
a real document. The command generates a three-page synthetic PDF — page 1
with a normal text layer (OCR must skip it), pages 2 and 3 with known text
present only as embedded images (prose with digits and punctuation, then a
heading/bullets/table layout) — runs the real OCR path against your model,
and scores each transcription against the known text:

```json
{
  "model": "gpt-4o-mini",
  "dpi": 150,
  "pages": [
    { "physical_page": 1, "status": "skipped",
      "detail": "has a text layer; OCR correctly not attempted" },
    { "physical_page": 2, "status": "ok", "similarity": 98.7, "threshold": 80,
      "expected_chars": 228, "transcribed_chars": 226,
      "detail": "transcription of the prose page" },
    { "physical_page": 3, "status": "ok", "similarity": 91.2, "threshold": 70,
      "expected_chars": 141, "transcribed_chars": 149,
      "detail": "transcription of the bullets and table page" }
  ],
  "warnings": [],
  "overall_status": "pass"
}
```

`similarity` is a whitespace-insensitive percentage against the expected text.
Scores below the per-page threshold report `warn` (the model may struggle with
your documents); a page with no transcription at all reports `fail`, and the
command then exits nonzero. Uses the same model/endpoint/key configuration as
`rp-pdf markdown --ai` and requires poppler plus the `ai` optional dependencies;
the synthetic PDF is generated with reportlab (a dev dependency of this repo —
`uv sync` installs it).

### `rp-pdf render` — rasterize pages

```sh
uv run rp-pdf render report.pdf --pages 1-3 --out renders/ --dpi 200 --format png
```

Writes one image per page into `--out` and reports the pixel dimensions of each
file. Requires poppler (see below).

### Output file naming

Files produced by `tables --csv`, `images --out`, and `render` are named by page
label first (what you see in your PDF reader), with the physical position as a
`pp` suffix for disambiguation; numeric parts are zero-padded to 4 digits:

| Document      | render            | images                    | tables --csv               |
|---------------|-------------------|---------------------------|----------------------------|
| with labels   | `page0030_pp0038.png` | `page0030_pp0038_img00_Im1.png` | `table_page0030_pp0038_00.csv` |
| without labels| `page0038.png`    | `page0038_img00_Im1.png`  | `table_page0038_00.csv`    |

## Configuration file

Any option can be given a persistent default in an optional TOML config file, so
you don't have to repeat flags or export environment variables. With one in
place, a bare `rp-pdf FILE.pdf` — just the PDF path, no subcommand — finds the
config and runs the action it prescribes.

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

[vlm]                         # shared VLM settings for --ai / --ocr / validate-vlm-ocr
model = "gpt-4o-mini"
base_url = "https://openrouter.ai/api/v1"
organization = "org-abc123"
cache_dir = "~/.cache/rp-pdf"
# the API key is never read from the config file (see "Secrets" below).
```

### Precedence

Every option resolves as **flag → environment variable → config file → built-in
default**. The config sits below flags and the `RP_PDF_*` env vars, above rp-pdf's
built-in defaults. Those env vars are unchanged; the config file is a strictly
additional, lower-priority layer.

Since flags win, boolean options are **paired** — every `--flag` has a matching
`--no-flag`, and both default to unset so an omitted flag falls through to the
config rather than forcing the option off. This is what lets you disable a
config-enabled feature on the command line:

```sh
# config sets [markdown] ai = true; run this one file without the AI pass:
rp-pdf report.pdf --no-ai
```

A VLM key placed in a command section (e.g. `[markdown] model`) overrides the
same key in the shared `[vlm]` section for that command.

### Discovery

The file is located, first match wins:

1. an explicit `--config PATH` (or the `$RP_PDF_CONFIG` env var);
2. the nearest `rp-pdf.toml` walking up from the current directory (project-local);
3. `~/.config/rp-pdf/config.toml` (user-level).

When both a project and a user file exist they are merged per key, with the
project file winning. A missing auto-discovered file is simply ignored; a
missing `--config`/`$RP_PDF_CONFIG` file, or a malformed file, reports a clear
error (not a traceback).

### Secrets

The config file supports every setting **except** the API key. The key stays in
the environment (`RP_PDF_VLM_API_KEY`, falling back to `OPENAI_API_KEY`) — reading
a key from a file on disk is a footgun rp-pdf deliberately avoids. Passwords for
encrypted PDFs are likewise flag/`--password`-only and never read from config.

## Page labels

Books and reports often number their pages the way print does: a cover, front
matter like `FM1`-`FM6` or `i`-`xx`, then content starting over at `1`. PDFs encode
this as *page labels* (`/PageLabels`), and PDF readers display them — the "page 1"
your reader shows is usually not the first physical page.

rp-pdf follows the same convention: **when a document defines page labels, `--pages`
is interpreted against them** and a notice is printed to stderr:

```sh
uv run rp-pdf text book.pdf --pages 1-30      # content pages labeled 1-30
uv run rp-pdf text book.pdf --pages i-xx      # roman-numeral front matter
uv run rp-pdf text book.pdf --pages cover,FM2 # any label works, mixed freely
```

Notes:

- Ranges may span labeling schemes (`FM3-ii`) and cover the physical span between
  their endpoints. Matching is exact first, then case-insensitive.
- Pass `--physical` (library: `physical=True`) to force plain 1-based physical
  numbering.
- Documents without page labels behave exactly as before; `--physical` is then a
  no-op.
- `rp-pdf index` shows every page's label alongside its physical number, and
  `core.get_page_labels(path)` returns the full label list (or `None`).
- Every per-page JSON result carries both schemes: `physical_page` (1-based
  position in the file) and `labeled_page` (the display label, `null` when the
  document has no labels), so output is unambiguous regardless of how pages
  were selected.

## Library

All core functions accept a path plus parameters and return pydantic models —
serialize with `.model_dump()` / `.model_dump_json()`.

```python
from rp_pdf import core

index = core.get_index("report.pdf")
print(index.page_count, index.metadata.title)

for page_text in core.get_text("report.pdf", "1-3", layout=False):
    print(page_text.page, page_text.text[:80])

for table in core.get_tables("report.pdf", "all"):
    print(f"page {table.page}, table {table.index}: {len(table.rows)} rows")

images = core.get_images("report.pdf", "all", out_dir=None)   # metadata only
rendered = core.render_pages("report.pdf", "1", "out/", dpi=200)

# Encrypted files
text = core.get_text("locked.pdf", "all", password="secret")

# Markdown conversion (rp_pdf.markdown, not core)
from rp_pdf.markdown import to_markdown

result = to_markdown("report.pdf", images_dir="media")        # stage 1 only
result = to_markdown("report.pdf", ai=True, model="gpt-4o-mini", jobs=4)
result = to_markdown("report.pdf", ai=True, ocr=True, model="gpt-4o-mini")  # with OCR
# model/base_url/organization also fall back to RP_PDF_VLM_MODEL/RP_PDF_VLM_BASE_URL/RP_PDF_VLM_ORG
result = to_markdown("report.pdf", ai=True, model="gpt-4o", organization="org-abc123")
print(result.markdown)                                        # joined document
for page in result.pages:                                     # per-page bodies
    print(page.physical_page, page.ai_refined, page.ocr_transcribed, page.markdown[:60])
print(result.warnings)                                        # AI/OCR fallbacks, if any

# Standalone OCR of scanned pages (rp-pdf.ocr, requires the ai dependencies).
# Returns one PageText per page *without* a text layer; pages that already
# have text are skipped (use core.get_text for those).
from rp_pdf.ocr import transcribe_pages

warnings: list[str] = []
for page in transcribe_pages("scanned.pdf", model="gpt-4o-mini", warnings=warnings):
    if page.has_text:
        print(f"page {page.physical_page}: {len(page.text)} chars transcribed")
print(warnings)                                               # per-page OCR failures
```

Errors raise `FileNotFoundError`, `rp-pdf.PageSpecError`, or subclasses of
`rp_pdf.core.PdfxError` (`InvalidPdfError`, `PasswordError`, `PopplerNotFoundError`).

## Poppler

`rp-pdf text` and `rp-pdf search` shell out to poppler's `pdftotext` by default,
and `rp-pdf render` shells out to poppler via pdf2image; `rp-pdf markdown` uses
`pdftotext` for pages without tables and page rendering for its `--ai` and
`--ocr` passes, and `rp-pdf validate-vlm-ocr` renders its test pages the same
way. `index`, `tables`, and `images` work without poppler, as do
`text`/`search`/`markdown` with `--engine pypdf` or `--engine pdfplumber`.

- Linux: `apt install poppler-utils`
- macOS: `brew install poppler`
- Windows: `winget install oschwartz10612.Poppler`

If poppler is not on `PATH` (common on Windows), point at its `bin` directory with
`--poppler-path DIR` or the `RP_POPPLER_PATH` environment variable.
