# rp-pdf Usage Guide

`rp-pdf` extracts structured information from PDF files. It is JSON-first:
structured read commands (`index`, `text`, `tables`, `search`, `images`)
print JSON to stdout by default so output can be piped into other tools.
`render` writes image files to disk and, like the read commands, reports JSON
metadata about them (page, path) to stdout by default. `markdown` is the one
command whose stdout differs by design: with no `-o`/`--out` it prints
Markdown itself, not JSON; given `-o` it writes the file and prints a plain
`Wrote <path>` note to *stderr* rather than JSON (`--full` always emits the
whole result as JSON regardless of `-o`). The same functionality is available
as a Python library (`rp_pdf.core`).

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
  | `-4`        | everything up to page 4          |
  | `7-`        | page 7 through the end           |
  | `1,3-5,9`   | mixed list; deduplicated, sorted |

  An omitted endpoint takes the document's. A bare `-` is rejected rather than
  read as "everything" — `all` already says that, and a lone hyphen is far more
  likely a typo. Open-ended forms work against page labels too, so `--pages 7-`
  means the same thing whether or not the PDF is labelled.

- **Page numbering follows the document's page labels when it has them** (see
  [Page labels](#page-labels) below); otherwise pages are numbered 1-based from
  the first physical page. `--physical` forces 1-based physical numbering either way.

- **Errors** go to stderr: a human-readable message, then an *error envelope* as
  the last line, so stdout stays clean for results and scripted callers always
  have one line of parseable JSON to read.

  ```json
  {"error": {"type": "PopplerNotFoundError", "message": "…", "hint": "apt install poppler-utils", "exit_code": 2}}
  ```

  Every CLI in the suite emits exactly this shape — there is no second form.
  The exit code says what kind of failure it was:

  | Code | Meaning |
  |---|---|
  | `0` | success |
  | `1` | user or input error — bad page spec, bad option, missing file |
  | `2` | a required external binary is absent (run `rp-pdf doctor`) |
  | `3` | the file is corrupt, encrypted-unreadable, or not a PDF |

  These codes are shared across the whole robo-papyro suite.
- **Encrypted PDFs**: pass `--password PW` (library: `password="PW"`). Missing or
  wrong passwords produce a clear error.
- **Long runs describe themselves and report progress** — on stderr, and only
  when a person is watching. See [Watching a long run](#watching-a-long-run).

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
uv run rp-pdf doctor            # list[Capability] as JSON — the default everywhere
uv run rp-pdf doctor --plain    # table of poppler tools, versions, and paths
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
summary includes its `labeled_page` alongside `physical_page` — handy for seeing
how labels map to physical positions.

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
uv run rp-pdf markdown report.pdf --full                 # whole MarkdownResult as JSON
uv run rp-pdf markdown report.pdf -o report.md --ai --model gpt-4o-mini
uv run rp-pdf markdown report.pdf --ai --ocr --model gpt-4o-mini  # with OCR for scanned pages
```

This is the command most likely to run for minutes, so it is also the one
[`--describe` and `--progress`](#watching-a-long-run) were written for: check
the model and the flags before it starts, and watch the page count move while
it runs. Both are automatic on a terminal.

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

## Watching a long run

`rp-pdf markdown --ai` on a few hundred pages is minutes of work, most of it
spent waiting on a remote model. Two options make that wait legible, and a third
records the options that produced it. All three are available on `text`,
`tables`, `search`, `images`, `markdown`, and `render` — the commands with a job
worth describing.

**Nothing here touches stdout.** The description and the progress line are
written to stderr, and both default to *on only when stderr is a terminal*, so a
pipeline, a script, or an agent sees exactly the output it saw before.

Each resolves as **flag → environment variable → config file → is stderr a
terminal**: `--describe`/`--no-describe` and `--progress`/`--no-progress`,
then `RP_PDF_DESCRIBE` / `RP_PDF_PROGRESS` (`1`/`true`/`yes`/`on` and their
opposites), then `[ui]` — or a per-command section — in the config file.

### `--describe` — what is about to happen

Prints the resolved options — flags, environment variables, and config file all
folded together — before the work starts:

```console
$ rp-pdf markdown report.pdf --ai --jobs 4 -o report.md
rp-pdf markdown — report.pdf
  pages      all
  engine     poppler (needs pdftotext installed)
  images     skipped (--images-dir DIR to extract and link them)
  AI review  on, model gpt-4o-mini at https://openrouter.ai/api/v1; 4 concurrent, pages rendered at 150 dpi
  OCR        off — pages with no text layer stay empty (--ocr to transcribe them)
  outline    not used (--outline-headings, --outline-context; no-ops without bookmarks)
  cache      on — responses reused from ~/.cache/rp-pdf
  output     report.md
```

Options that are **off** name the flag that turns them on, because that is the
half worth checking: the description is there to answer "did I remember
`--ocr`?" and "is it really using the model I meant?" before the bill, not
after. `--no-describe` suppresses it; `--describe` forces it on when stderr is
not a terminal (useful in a log).

### `--progress` — proof it is still moving

A single line on stderr, rewritten in place, with a spinner, a count, and an
elapsed clock:

```
⠹ AI review 27/142 [1m48s]
```

The clock is driven by a background thread rather than by the work, so it keeps
ticking while a page render or an API call is blocked — a stalled network read
looks different from a slow one, which is the entire point. **Opening the file
is itself a reported stage**, so a document on a share that stopped answering
shows a ticking `Opening report.pdf` rather than nothing; the whole job is one
outer step, so no phase happens in silence. Each stage leaves a completed line
behind:

```
✔ Opening report.pdf [0s]
✔ Finding tables 142/142 [3s]
✔ Extracting text (poppler) 130/130 [11s]
✔ Rendering pages 142/142 [1m02s]
⠹ AI review 27/142 [1m48s]
```

Redirected to a file or a CI log, where there is no line to rewrite, it switches
to one line per stage boundary plus a "still working" line every 15 seconds:

```
AI review: started (142)
AI review: still working 12/142 [15s]
AI review: still working 31/142 [30s]
AI review: done 142/142 [4m07s]
```

Progress **never** appears without a terminal unless you ask for it with
`--progress`, `RP_PDF_PROGRESS=1`, or `[ui] progress = true` in the config.

### `--save-config` — keep the options that worked

Writes the options you passed to a TOML file, so the next document does not need
the command line again:

```console
$ rp-pdf markdown report.pdf --ai --model gpt-4o-mini --jobs 4 --engine pypdf \
    -o report.md --save-config rp-pdf.toml
Saved the options you passed to /work/rp-pdf.toml as [markdown].
'out' was not saved: it names this document's output, and reusing it would overwrite this run's result on the next document.
It will be picked up automatically on the next run.

$ cat rp-pdf.toml
[markdown]
ai = true
jobs = 4
engine = "pypdf"

[vlm]
model = "gpt-4o-mini"

$ rp-pdf markdown other.pdf -o other.md   # same AI pass, same model, same engine
```

What it does and does not record:

- **Only the options you actually passed.** Not every resolved value: writing
  back a built-in default would freeze today's default into your file, and the
  file is meant to record a decision, not take a snapshot.
- Values that came from the **environment** or from an **existing config file**
  are not copied in either. They already live somewhere that outlasts the run.
- **`markdown -o FILE` is never saved**, even though you passed it: it names
  *this* document's output, and persisting it would make the next document
  silently overwrite this one's result. Directory options (`images --out`,
  `render --out`, `tables --csv`) are saved — a directory is reusable.
- It writes **after the run succeeds**, so what gets recorded is a command line
  known to have worked, not one that was merely typed.
- Per-command options land in `[markdown]` (or `[text]`, `[render]`, …); the
  shared settings land in the shared sections — `model`, `base_url`,
  `organization`, `cache_dir` in `[vlm]`, and `--describe`/`--progress` in
  `[ui]` — where every command can see them, which is also where they are read
  back from. That is the layout a hand-written file uses, and `--save-config` is
  a decent way to learn it. The message names the sections it wrote.
- Writing the file can fail (a directory in the way, a read-only parent). That
  is reported as an ordinary rp-pdf error — message plus error envelope on
  stderr, exit 1 — not a traceback.
- The **API key is never written**, and neither is `--password`. Secrets stay in
  the environment.
- An existing file is *merged*: other sections and other keys survive. But it is
  rewritten from its parsed contents, so **comments and formatting in it are
  lost** — the command says so when that applies. The replacement is atomic (a
  complete temporary file, then one rename), so a failure part-way through
  leaves your existing config exactly as it was rather than truncated.
- `rp-pdf.toml` in the current directory (or any parent) is found automatically
  next time. Saving anywhere else works, and the command tells you that you will
  need `--config PATH` to read it back.

## Configuration file

Any option can be given a persistent default in an optional TOML config file, so
you don't have to repeat flags or export environment variables. With one in
place, a bare `rp-pdf FILE.pdf` — just the PDF path, no subcommand — finds the
config and runs the action it prescribes.

**Where does it go, and what is it called?** Two fixed locations, both optional:

| | Path | Use it for |
|---|---|---|
| **Project** | `rp-pdf.toml` — in the current directory, or any parent | settings for one repository or one batch of documents |
| **User** | `~/.config/rp-pdf/config.toml` | your personal defaults, everywhere |

Both names are fixed: a project file is called `rp-pdf.toml` and nothing else,
and the user file lives at exactly that path. **They are not alternatives — both
apply at once**, merged per key with the project file winning, so a repository
can override one of your personal defaults without restating the rest. There can
be at most one of each; rp-pdf does not read several project files, only the
nearest one walking up from where you are.

`--config PATH` (or `$RP_PDF_CONFIG`) is the escape hatch: it names *any* file,
anywhere, with any name — and when you use it, that file is the **only** one
read. Neither the project nor the user file applies.

Not sure which files are in play? `--describe` shows the options that actually
resolved, from all sources at once, which is usually the question behind the
question.

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

[ui]                          # shared human-output settings (see "Watching a long run")
progress = true               # default: on only when stderr is a terminal
describe = false
```

You don't have to write this by hand: `--save-config rp-pdf.toml` on any run
produces it from the options that run used.

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
same key in the shared `[vlm]` section for that command. The two `[ui]` keys
work the same way.

### Discovery

In order:

1. `--config PATH` (or `$RP_PDF_CONFIG`). If given, **this file and no other**
   is read — discovery stops here.
2. Otherwise both of the following, merged per key with the project file
   winning:
   - the nearest **`rp-pdf.toml`** walking up from the current directory;
   - **`~/.config/rp-pdf/config.toml`**.

A missing auto-discovered file is simply ignored — having neither is normal, and
every option falls through to its built-in default. A missing
`--config`/`$RP_PDF_CONFIG` file is an error, because you named it explicitly. A
malformed file is always an error, reported clearly rather than as a traceback,
so a typo surfaces instead of being silently skipped.

### Secrets

The config file supports every setting **except** the API key. The key stays in
the environment (`RP_PDF_VLM_API_KEY`, falling back to `OPENAI_API_KEY`) — reading
a key from a file on disk is a footgun rp-pdf deliberately avoids. Passwords for
encrypted PDFs are likewise flag/`--password`-only and never read from config.
`--save-config` honors the same rule: neither is ever written out.

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
    print(page_text.physical_page, page_text.text[:80])

for table in core.get_tables("report.pdf", "all"):
    print(f"page {table.physical_page}, table {table.index}: {len(table.rows)} rows")

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

# Progress, for a caller with a UI of its own. Library functions never print;
# they call the reporter you pass, and the default one does nothing.
from rp_core.progress import StderrProgress

with StderrProgress() as reporter:                            # or your own Progress
    result = to_markdown("report.pdf", ai=True, model="gpt-4o-mini", progress=reporter)
```

Errors raise subclasses of `rp_pdf.errors.RpPdfError`, which is parented onto
`rp_core.errors` and carries the exit code and `type` the error envelope
reports: `MissingFileError` (also a `FileNotFoundError`, exit 1),
`InvalidPdfError` (exit 3), `PasswordError` (exit 1), `PopplerNotFoundError`
(exit 2), and `QueryError` (exit 1, a bad search query). No bare builtin
exception reaches the caller.

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

`pdftotext` runs with a time limit — `RP_SUBPROCESS_TIMEOUT` seconds, 600 by
default. The limit is generous because a few-hundred-page PDF can legitimately
take minutes; it exists because poppler can hang outright on malformed input,
and a hung subprocess behind an agent's tool call gives no signal at all.
Exceeding it exits **3** with a `SubprocessTimeout`.
