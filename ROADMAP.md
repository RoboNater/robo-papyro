# robo-papyro Roadmap

Two plans live here: the suite's phasing, and `rp-pdf`'s own roadmap, which
predates the suite and continues under it. Each phase lands on its own feature
branch, fully tested and documented, before the next begins.

## Suite phases

Driven by [`docs/specs/robo-papyro-spec.md`](docs/specs/robo-papyro-spec.md) §9.

| Phase | Scope | Driving doc | Status |
|---|---|---|---|
| **0** | Workspace scaffold, `pdfx` → `rp-pdf` rename, extract `rp-core`, `rp` umbrella | robo-papyro-spec §8 | ✅ |
| **0.5** | Contract decisions and extraction cleanup | robo-papyro-spec §8 | ✅ |
| **1** | `rp-docx`: templates, docx read/write/template, CLI | [rp-docx-spec](docs/specs/rp-docx-spec.md) §12 | ✅ |
| **2** | `rp-mcp`: FastMCP servers for `rp-pdf` and `rp-docx`; skills in `skills/` | TBD | next |
| **2.5** | `rp-pptx`: templates, pptx read/write/template, slide operations, CLI | [rp-pptx-spec](docs/specs/rp-pptx-spec.md) §12 | ready |
| **3** | `rp-xlsx` (openpyxl), same core/CLI split | TBD | |

Phase 0 delivered the workspace, `rp-core` (errors and exit codes, binary
discovery, rasterization, range specs, CLI conventions), the `rp-pdf` rename, and
the `rp` dispatcher. `rp-pdf`'s behavior is unchanged apart from the rename and
the CLI exit-code mapping (1 input / 2 missing dependency / 3 corrupt file),
which replaced a flat exit 1.

Phase 0.5 settled the contract decisions Phase 0 surfaced: one error payload
(the `ErrorEnvelope`) rather than two, JSON output by default with `--plain`
rather than a `--json` opt-in, generic range parsing in `rp-core` with PDF page
labels back in `rp-pdf`, a bounded timeout on every subprocess, a pinned ruff
with a wider rule set, the workspace's invariants as tests, and a license gate
that computes the base install path rather than trusting a comment about it.

Phase 1 added `rp-docx`: reading (index, text, tables, images, comments, tracked
changes), writing (create from Markdown, append, replace, set properties, accept
and reject changes), native `{{ placeholder }}` templating, and the template
manifest/synthesis loop that lets CI exercise a confidential template's shape
without ever holding the template. `.dotx` support needed real work — python-docx
does not open one at all.

Phase 1 also corrected two things the spec had wrong in practice: the default
`StyleMap.code` named a style Word does not ship, which made every Markdown
document containing a code block fail on the default template, and
`resolve_template` needed to tell a wrong path from an unknown name. Both, and
everything else §5–§9 got wrong, are recorded in
[dev-notes/status-robo-papyro-phase-1.md](dev-notes/status-robo-papyro-phase-1.md).

Phase 2.5 promotes `rp-pptx` out of the old Phase 3 bundle into its own phase,
now specced ([rp-pptx-spec](docs/specs/rp-pptx-spec.md)): slide decks are part
of the target corpus, python-pptx (MIT) was vetted in §7 from the start, and
Phase 1 built almost everything the package needs — the template
manifest/synthesis loop, the run-spanning replacement algorithm, the
content-type retyping that `.potx` turns out to need exactly as `.dotx` did
(verified: python-pptx refuses a `.potx` outright, python-pptx 1.0.2). It is
independent of Phase 2 and may land before or after it; whichever of the two
lands second wires the pptx FastMCP server into `rp-mcp`. Markdown conversion
is hand-rolled both ways — the existing converters were rejected on
dependencies, not licenses (`pptx2md` drags in `tqdm`, MPL-2.0 AND MIT, which
§7.1 bars from the base install path).

Open from the spec: `templates/README.md` needs an owner and canonical location
per template (§11.2), archiving `w528-pdf-extraction-toolkit` should happen now
that Phase 0 is green (§11.3), and `rp-docx` still needs validating against a
real house template — a separate manual pass, described in
[rp-docx-spec](docs/specs/rp-docx-spec.md) §13.

## rp-pdf phases

Version bumps: 0.2.0 after Phase 1, 0.3.0 after Phase 2, 0.4.0 after Phase 3
(OCR), 0.5.0 after Phase 4 (quality of life), 0.6.0 after Phase 5 (RAG), 0.7.0
after Phase 6 (MCP). Phase 6 below is superseded by suite Phase 2, which covers
MCP servers for every package rather than `rp-pdf` alone.

### Phase 1 — Search ✅ (shipped in 0.2.0)

A `rp-pdf search` command so finding content in a large document doesn't require
extracting text and grepping it manually — with results reported in both
numbering schemes, closing the loop with page labels.

**Core** (`core.search`):

```python
def search(path, query, pages="all", regex=False, ignore_case=True,
           context=80, max_hits=100, password=None, physical=False) -> list[SearchHit]
```

- `SearchHit` model: `physical_page`, `labeled_page`, `snippet` (match with
  ~`context` characters either side, match delimited so callers can highlight),
  `match` (the exact matched text).
- Plain (non-regex) queries match with whitespace normalized — runs of
  spaces/newlines collapse to single spaces — so phrases match across line
  wraps in extracted text. `--regex` searches the raw page text.
- `max_hits` caps result size (JSON-first tool; a common word in a 500-page
  ebook shouldn't produce megabytes).

**CLI:**

```sh
rp-pdf search FILE QUERY [--pages SPEC] [--regex] [--case-sensitive]
                       [--context N] [--max N] [--plain] [--password PW] [--physical]
```

JSON by default; `--plain` prints one line per hit (`page 12 (pp 39): ...snippet...`)
for interactive use.

**Tests:** hits with correct pages/labels, multi-hit pages, phrase across a line
break, regex mode, case sensitivity, max cap, no-match returns `[]` not an error.

Landed as designed. Also fixed along the way: text extraction now defaults to
`pdftotext` for correct word spacing (issue #1), and CLI stdout/stderr are
forced to UTF-8 on Windows.

### Phase 2 — Markdown conversion ✅ (shipped in 0.3.0)

A `rp-pdf markdown` command that turns a PDF (or page range) into clean Markdown,
in two stages: a fast programmatic pass built from the existing extractors, and
an optional AI pass where a vision-language model reviews each page's draft
Markdown against the rendered page image and corrects it.

**Stage 1 — programmatic pass** (`markdown.py`, pure assembly over `core`):

```python
def to_markdown(path, pages="all", images_dir=None, ai=False, model=None,
                base_url=None, jobs=1, dpi=150, password=None,
                physical=False) -> MarkdownResult
```

- Text via `get_text` (pdftotext layout), tables via `get_tables` rendered as
  GitHub-flavored pipe tables, images extracted to `images_dir` and referenced
  with relative links (skipped when `images_dir` is `None`).
- **Table/text dedup is the hard part, design it first:** table content appears
  twice — as garbled whitespace-aligned rows in the prose text and again in the
  pipe table. Use pdfplumber's table bounding boxes to crop table regions out
  of the prose before assembling the page, so each table appears exactly once,
  in flow position.
- Pages with no text layer emit a placeholder (`<!-- page N: no text layer -->`)
  rather than silent emptiness, in both stages.
- Per-page output joined with an HTML-comment delimiter carrying provenance
  (`<!-- page 12 (pp 39) -->`), labels-first like everything else.
- Models: `MarkdownPage` (`physical_page`, `labeled_page`, `markdown`,
  `ai_refined: bool`), `MarkdownResult` (pages + joined `markdown`).

**Stage 2 — AI review pass** (opt-in via `ai=True` / `--ai`):

- Each page is rendered to an image (`render_pages`, requires poppler) and sent
  with its draft Markdown to a vision-language model, which returns corrected
  Markdown: fixes reading order, merged/split words, table structure, missing
  headings, and content the programmatic pass dropped or garbled.
- **The draft is ground truth for characters; the image is ground truth for
  structure.** VLMs hallucinate when transcribing — swapped digits, "fixed"
  serial numbers. The prompt instructs the model to rearrange, restructure, and
  re-tag the draft, preferring the draft's literal characters over its own
  reading of the image. This prompt decision is the difference between an AI
  pass that improves quality and one that quietly corrupts data.
- **Output validation before accepting a response:** strip a wrapping code
  fence, reject responses whose length is wildly off from the draft (e.g.
  under 50%), then fall back to the programmatic draft with
  `ai_refined: false` — the same path as API errors. Per-page failure never
  sinks the document.
- **Cost controls:** pages are independent, so bounded concurrency via
  `--jobs N`; and a per-page response cache keyed on file hash + page + model
  + prompt version (under the images/output dir or a cache dir), so an
  interrupted run on a 300-page document resumes instead of re-billing.
- **OpenAI-compatible API only** — works against OpenAI, OpenRouter, Ollama,
  LM Studio, vLLM, etc. Configuration: `--model`/`RP_PDF_VLM_MODEL`,
  `--base-url`/`RP_PDF_VLM_BASE_URL`, key from `RP_PDF_VLM_API_KEY` falling back to
  `OPENAI_API_KEY`. Clear error when model or key is missing.
- The `openai` client lives in an optional dependency group (`uv sync --extra
  ai`); the base install stays light and stage 1 never imports it.
- No-text-layer pages are **not** sent for transcription — that would be OCR
  through the back door (out of scope at the time). They keep their
  placeholder. (Phase 3 later added exactly this, deliberately, via `--ocr`.)

**CLI:**

```sh
rp-pdf markdown FILE [-o OUT.md] [--pages SPEC] [--images-dir DIR]
                   [--ai] [--model NAME] [--base-url URL] [--jobs N] [--dpi N]
                   [--password PW] [--physical]
```

Markdown to stdout by default (`-o` writes a file); `--full` emits the whole
`MarkdownResult` as JSON for programmatic callers. (It was `--json` until Phase
0.5, which reserved that spelling: JSON is the suite default, so no `--json`
flag exists anywhere.)

**Tests:** stage 1 on existing fixtures — headings/paragraph text, a table
rendered as a valid pipe table with its rows absent from the surrounding prose
(the dedup), image links pointing at extracted files, page delimiters with
correct labels, no-text-layer placeholder. Stage 2 against a faked
OpenAI-compatible endpoint (no network in CI): request carries image + draft,
response replaces the page, wrapping code fence stripped, too-short response
rejected, API error falls back to the draft with `ai_refined: false`, second
run served from cache.

**Later, not in this phase:** a `--describe-images` flag (vector charts and
figures don't come out via `get_images`; the VLM could write alt text), and
feeding this output into Phase 5 — markdown with page delimiters is a better
chunking input than raw text, so `chunk_document` may eventually consume it.

**Post-ship additions (0.3.x, opt-in pending evaluation):** heading levels are
otherwise page-local, so two outline-aware options anchor them to the PDF's
bookmark tree: `--outline-headings` promotes outline titles found on their
destination pages to headings by outline depth (stage 1, no AI), and
`--outline-context` feeds each page's outline path into the VLM prompt so the
AI pass assigns levels matching the document hierarchy. Both are no-ops on
documents without an outline. **Open decision:** evaluate on real documents,
then promote one or both to default-on.

### Phase 3 — OCR for scanned pages (in progress)

The line the "out of scope" note said Phase 2 would make nearly free, now
crossed deliberately: the VLM that reviews pages also transcribes the scanned
ones. VLM-only — no tesseract or other local OCR engine, so there are no new
dependencies and one set of configuration, validation, and cost controls.

**Core** (`ocr.py`, sharing client/cache plumbing with `markdown.py` via
`vlm_utils.py`):

```python
def transcribe_pages(path, pages="all", model=None, base_url=None, jobs=1,
                     dpi=150, password=None, physical=False, poppler_path=None,
                     cache_dir=None, use_cache=True, warnings=None) -> list[PageText]
```

- Only pages without a text layer are rendered and sent; one `PageText` per
  scanned page comes back (`has_text=True` on success, `False` with empty text
  on failure — failures append to `warnings` and never raise).
- The prompt inverts the Phase 2 ground-truth rule: there is no draft, so the
  image is the only source and the model transcribes exactly, marking
  `[illegible]` rather than guessing. Responses are validated (fence stripped,
  too-short responses rejected as likely refusals) and cached under an
  OCR-specific key (file hash + page + model + prompt version + dpi).

**`rp-pdf markdown --ocr`** (requires `--ai`): a third stage after refinement
replaces `no text layer` placeholders with transcriptions and marks those pages
`ocr_transcribed: true`; failed pages keep their placeholder.

**`rp-pdf validate-vlm-ocr`**: generates a three-page synthetic PDF — page 1 with
a text layer (must be skipped), pages 2-3 with text present only as embedded
images — runs the real OCR path against the configured model, and scores the
transcriptions against the known text (whitespace-insensitive similarity, with
ok/warn thresholds). Lets a user prove their model/endpoint works before
spending money on a real document.

**Shared VLM config** (`vlm_utils.make_client`, used by both the AI pass and
OCR): `--model`/`--base-url`/`--organization` with `RP_PDF_VLM_MODEL` /
`RP_PDF_VLM_BASE_URL` / `RP_PDF_VLM_ORG` env fallbacks, key from `RP_PDF_VLM_API_KEY`
→ `OPENAI_API_KEY`. `--organization` is passed to the client only when set
(OpenAI-hosted, org-scoped accounts); local/third-party servers leave it unset.
These defaults (and every other CLI option) can also live in an optional TOML
config file — see "Config file" below.

**Tests:** against the faked OpenAI-compatible endpoint from Phase 2 — scanned
pages transcribed and text-layer pages skipped (no API traffic), request
carries the page image, failure/short-response fallback with warnings, cache
hits on the second run, `--ocr` placeholder replacement and `--ocr` without
`--ai` rejected, validation PDF has the right text-layer shape, validate
pass/warn/fail paths, and config resolution including organization (arg/env
precedence and the org reaching the wire as a header).

See `dev-notes/phase-3-ocr-vlm.md` for the full design.

### Config file ✅

Optional TOML config (`rp-pdf.config`) giving any CLI option a persistent default,
resolved **flag → env var → config file → built-in default**. A `[default]`
section names the command that a bare `rp-pdf FILE.pdf` runs (else `index`);
per-command sections (`[markdown]`, `[text]`, …) plus a shared `[vlm]` section
hold option defaults, with a command-scoped VLM key overriding `[vlm]`. Because
flags win, every boolean option is a paired `--flag/--no-flag` defaulting to
unset, so e.g. `--no-ai` can disable a config-enabled AI pass. Discovery:
`--config`/`$RP_PDF_CONFIG`, then nearest `rp-pdf.toml` walking up from CWD, then
`~/.config/rp-pdf/config.toml` (project merges over user). Secrets stay out — the
API key is env-only, never read from the file. Config loading lives in the CLI
layer; `core` stays import-clean. Tests: `tests/test_config.py` (discovery,
precedence matrix, default action, key-not-from-config).

### Phase 4 — Quality of life

Three independent, small items.

**4a. `index` performance flag.** `get_index` currently extracts text from every
page to compute `has_text` — the slowest part of indexing a large ebook. Add
`check_text: bool = True` to `core.get_index` and `--no-text-check` to the CLI;
when disabled, `has_text` is `null` in output (model field becomes
`bool | None`). Index of a several-hundred-page PDF becomes near-instant.

**4b. Form fields.** `core.get_fields(path, password) -> list[FormField]` via
pypdf `reader.get_fields()`; model: `name`, `field_type` (text/checkbox/radio/
choice/signature), `value`, `default_value`. New CLI command `rp-pdf fields FILE`.
Documents without forms return `[]`. Fixture: generate a simple AcroForm with
pypdf in conftest.

**4c. CI.** GitHub Actions workflow: matrix of ubuntu-latest + windows-latest,
steps = install uv (`astral-sh/setup-uv`), `uv sync`, `ruff check` +
`ruff format --check`, `uv run pytest`. Ubuntu installs `poppler-utils` so
render tests run; Windows skips them (already automatic). Requires the repo to
be on GitHub — skip this item if it stays on a local remote.

### Phase 5 — RAG: chunking and vector store

Make a PDF semantically queryable: chunk → embed → store → query, with page
provenance carried through so answers can cite labeled pages.

**Design principles:**

- Core stays import-clean: new modules `chunking.py` (pure) and `rag.py`
  (store/embedding); CLI wraps them like everything else.
- Heavy dependencies live in an optional group: `uv sync --extra rag`. Base
  install stays light.
- Local-first: no API keys required for the default path.

**Chunking** (`core`/`chunking.py`):

```python
def chunk_document(path, pages="all", target_chars=1200, overlap_chars=150,
                   password=None) -> list[Chunk]
```

- Splits on paragraph boundaries first, sentence boundaries as fallback,
  hard-split as last resort; adjacent chunks overlap by `overlap_chars`.
- `Chunk` model: `id` (stable hash of doc + span), `text`, `start_physical_page`,
  `end_physical_page`, `start_labeled_page`, `end_labeled_page`, `index`.
- `rp-pdf chunk FILE` emits chunks as JSON — useful standalone for feeding any
  external RAG pipeline, independent of our store.

**Vector store** (`rag.py`):

- **Engine: chromadb** (Apache-2.0, embedded/local, persistent directory).
  Alternative considered: LanceDB — also fine; chroma chosen for the simplest
  embedded API and built-in default embedding.
- **Embeddings: pluggable from day one**, selected via `--embedder` (env
  `RP_PDF_EMBEDDER`). Two implementations ship in Phase 5:
  - `local` (default): chroma's built-in ONNX MiniLM — downloads once, no
    torch, no API key.
  - `voyage` (API-based, higher quality): reads `VOYAGE_API_KEY`; errors
    clearly when the key is missing.
  The embedder interface is a small protocol (name + embed batch) so further
  providers are additive; the embedder name is stored in collection metadata
  and ingest/query refuse to mix embedders within a collection.
- Chunk metadata (pages, labels, source path, file hash) stored alongside
  vectors; re-ingesting an unchanged file is a no-op (file hash + chunk params).

**CLI:**

```sh
rp-pdf ingest FILE [--db DIR] [--collection NAME] [--embedder NAME]
                 [--target-chars N] [--overlap N]
rp-pdf query "question" [--db DIR] [--collection NAME] [--top-k K]
```

`query` output: hits with `score`, `text`, page provenance, and source path.

DB location resolution: `--db` flag, else `RP_PDF_DB` environment variable, else
`./.rp-pdf-db` in the current directory.

**Tests:** chunker is pure-python — test sizes, overlap, page provenance,
paragraph preservation. Store tests inject a deterministic dummy embedding
function (no model download in CI); one optional integration test runs the real
default embedder when the model is available locally.

### Phase 6 — MCP server

The spec's v2 goal: expose the same core to agents via MCP.

- `FastMCP` from the official `mcp` SDK; optional dependency group `mcp`;
  console script `rp-pdf-mcp` (stdio transport).
- Tools, mapped 1:1 onto core functions and returning their pydantic models as
  structured content: `pdf_index`, `pdf_text`, `pdf_tables`, `pdf_images`
  (metadata only), `pdf_search`, and — with a RAG store present — `pdf_query`.
  Rendering is omitted initially (file output is less useful over MCP; revisit
  with image content blocks if needed).
- Page specs behave exactly like the CLI, labels-first with a `physical`
  parameter, so agent ergonomics match human ergonomics.
- Configurable root directory allowlist so the server only reads PDFs under
  permitted paths.
- Tests: in-process client via the SDK's test transport; no subprocess needed.

### Out of scope

PDF modification/creation — revisit only when a real document needs it. OCR
was originally on this list; the Phase 2 AI pass made it nearly free (a VLM
that reviews pages can also transcribe scanned ones), and Phase 3 brought it
into scope on exactly those terms — VLM-based only. Local OCR engines
(tesseract etc.) remain out of scope.
