# rp-pdf — PDF Extraction Toolkit Specification

**Version:** 1.1
**Status:** Implemented · revised during Phase 0.5
**Parent document:** `robo-papyro-spec.md` v1.1 — read that first. Its §4 (`rp-core`), §7 (licensing) and §10 (constraints) govern this package.

**Changes from v1.0:** the package is `rp-pdf` / `rp_pdf`, not `pdfx` — §"Naming" records the full rename surface · §"Architecture" reflects the workspace layout and what moved to `rp-core` · §"CLI Design" adopts the suite exit-code taxonomy and the `ErrorEnvelope` error payload, and drops the `--json` spelling · §"Error Handling" replaces "exit 1" with the §4.7 taxonomy · the original kickoff prompt is kept verbatim as a historical appendix.

## Purpose

A Python library + CLI for extracting structured information from PDF files, designed for
programmatic consumption (JSON-first output). A future MCP server will wrap the same core
API, so the core must remain free of CLI/formatting concerns.

## Naming

The package shipped as `pdfx`. Phase 0 renamed it, and took the rename to the full
user-facing surface on the grounds that a repo with no external consumers is the only
cheap moment for it.

| Was | Now |
|---|---|
| distribution `pdfx`, import `pdfx`, CLI `pdfx` | `rp-pdf`, `rp_pdf`, `rp-pdf` |
| `PDFX_VLM_*`, `PDFX_CACHE_DIR`, `PDFX_CONFIG` | `RP_PDF_VLM_*`, `RP_PDF_CACHE_DIR`, `RP_PDF_CONFIG` |
| `PDFX_POPPLER_PATH` | `RP_POPPLER_PATH` (suite-wide, lives in `rp-core`) |
| `pdfx.toml` | `rp-pdf.toml` |
| `~/.config/pdfx/`, `~/.cache/pdfx/` | `~/.config/rp-pdf/`, `~/.cache/rp-pdf/` |
| `PdfxError` | `RpPdfError` |

Package-specific settings are `RP_PDF_*`; anything the whole suite shares is `RP_*` and
lives in `rp-core`.

## Constraints

- **License:** Permissive dependencies only — no AGPL (this excludes PyMuPDF). Parent §7.
- **Python:** 3.11+
- **Dependencies:**
  - `rp-core` — errors and exit codes, binary discovery, rasterization, range parsing, CLI conventions
  - `pypdf` — document metadata, outline/TOC, page-level text extraction
  - `pdfplumber` — table extraction, higher-fidelity text with layout when needed
  - `pdf2image` + system `poppler-utils` — page rasterization to images
  - `typer` — CLI
  - `pydantic` — typed result models / JSON serialization
- **Packaging:** a `uv` workspace member under `packages/rp-pdf/`, resolved through the
  single root lockfile; `[project.scripts] rp-pdf` plus a `robo_papyro.commands` entry
  point so the same typer app is reachable as `rp pdf ...`

## Architecture

```
packages/rp-pdf/
├── pyproject.toml
├── README.md
├── src/rp_pdf/
│   ├── __init__.py
│   ├── core.py          # pure extraction functions; no printing, no CLI
│   ├── models.py        # pydantic models: DocumentIndex, PageText, Table, ImageInfo, ...
│   ├── pages.py         # PDF page-label resolution; generic ranges come from rp_core.ranges
│   ├── errors.py        # RpPdfError and friends, parented onto rp_core.errors
│   ├── config.py        # rp-pdf.toml discovery and flag -> env -> config -> default
│   ├── markdown.py      # Markdown conversion, including the VLM review pass
│   ├── ocr.py           # VLM transcription of pages with no text layer
│   └── cli.py           # typer app wrapping core functions
└── tests/
    ├── conftest.py      # fixtures; generate small test PDFs programmatically
    └── test_*.py
```

**Design rule:** `core.py` functions accept a path (or open handle) plus parameters and
return pydantic models. `cli.py` only parses args, calls core, and serializes output.
The future MCP server (`FastMCP` from the official `mcp` SDK) will import `core` directly.

**What lives in `rp-core` instead of here** (parent §5): generic range parsing, the error
hierarchy and exit codes, binary discovery, the `rasterize` primitive, and the shared CLI
conventions. What deliberately stayed: `pdftotext`'s flags and form-feed page splitting,
all pypdf/pdfplumber logic, page-label resolution, and the command surface.

## Core API

All page numbers are **1-based** in the public API and CLI.

```python
def get_index(path: Path) -> DocumentIndex
    # page_count, metadata (title/author/dates), outline/bookmarks tree,
    # per-page summary (page number, width/height, rotation, has_text flag)

def get_text(path: Path, pages: PageSpec, layout: bool = False) -> list[PageText]
    # poppler's pdftotext by default; engine="pypdf"/"pdfplumber" for in-process

def get_tables(path: Path, pages: PageSpec) -> list[Table]
    # pdfplumber extract_tables(); Table = page, index, rows (list[list[str|None]])

def get_images(path: Path, pages: PageSpec, out_dir: Path | None) -> list[ImageInfo]
    # embedded images via pypdf page.images; save to out_dir if given,
    # otherwise return metadata only (name, page, size, format)

def render_pages(path: Path, pages: PageSpec, out_dir: Path,
                 dpi: int = 200, fmt: str = "png") -> list[RenderedPage]
    # wraps rp_core.render.rasterize, resolving page labels and naming files by label
```

`PageSpec` accepts: `"all"`, single page `"5"`, range `"3-7"`, open-ended range
`"-4"` or `"7-"`, mixed list `"1,3-5,9"`.
Specs are interpreted against the document's page labels when it has them, and against
1-based physical positions otherwise or with `--physical`. Every per-page result carries
both `physical_page` and `labeled_page`.

## CLI Design

```
rp-pdf index  FILE                          # document index as JSON
rp-pdf text   FILE --pages 3-7 [--layout]   # text; JSON default, --plain for raw text
rp-pdf tables FILE --pages all [--csv DIR]  # tables as JSON, or one CSV per table
rp-pdf images FILE --pages all --out DIR    # extract embedded images
rp-pdf render FILE --pages 1-3 --out DIR --dpi 200 --format png
rp-pdf doctor                               # which external binaries are installed
```

Every command is also reachable as `rp pdf COMMAND ...`.

Conventions (all inherited from `rp_core.clikit`, parent §4.6):
- JSON to stdout by default (machine-friendly); `--plain`/`--csv` for human/file variants.
  **There is no `--json` flag** — JSON is what you get without asking.
- Errors: a human-readable message on stderr, then an `ErrorEnvelope` as the final line
  of stderr. stdout carries results only.
- Encrypted PDFs: accept `--password`; fail clearly if missing/wrong
- Options resolve flag → env → config file → default; a bare `rp-pdf FILE` runs the
  config's `[default].command`, so any new subcommand must be added to `COMMAND_NAMES`

## Error Handling

Errors subclass `rp_pdf.errors.RpPdfError`, which is parented onto `rp_core.errors`; that
parent is what supplies the exit code and the `type` the envelope reports. The payload is
the suite's single shape:

```json
{"error": {"type": "PopplerNotFoundError", "message": "…", "hint": "apt install poppler-utils", "exit_code": 2}}
```

Exit codes follow the suite taxonomy (parent §4.7):

| Code | Meaning | Example |
|---|---|---|
| `0` | success | |
| `1` | user or input error | missing file (`MissingFileError`), bad page spec, bad option |
| `2` | missing external dependency | poppler absent (`PopplerNotFoundError`) |
| `3` | corrupt file or failed conversion | not a PDF (`InvalidPdfError`), `pdftotext` failed |

- Page numbers out of range → error listing the valid range
- `pdf2image` missing poppler → detect and report install hint (`apt install poppler-utils`)
- Pages with no extractable text (scanned) → return empty text with `has_text: false`,
  not an error (VLM-based OCR for such pages was added later; see "OCR for Scanned
  Pages" below)
- No bare builtin exception reaches the user: a missing file raises `MissingFileError`,
  which is also a `FileNotFoundError` for library callers

## Testing

- Generate small test PDFs in `conftest.py` using `reportlab` (dev dependency):
  text pages, a table, an embedded image, multi-page doc with bookmarks
- Test: page-spec parsing, index/outline, text by range, table rows, image extraction,
  render output files exist with correct dimensions
- `pytest`; aim for tests to run without any binary fixtures checked into the repo
- Tests that need poppler carry the `requires_poppler` marker and skip when it is absent;
  tests must never require LibreOffice

## Out of Scope (v1)

- Form field extraction
- PDF modification/creation
- MCP server (v2 — but keep core importable and CLI-free to enable it)
- Local OCR engines (tesseract etc.) — VLM-based OCR was brought into scope
  post-v1; see below

## OCR for Scanned Pages (added post-v1, roadmap Phase 3)

Originally out of scope for v1; brought into scope once the Markdown AI pass
(roadmap Phase 2) supplied the vision-language-model infrastructure — a VLM
that reviews pages can also transcribe scanned ones. VLM-based only: no local
OCR engine, no new dependencies, same OpenAI-compatible configuration,
validation, caching, and cost controls as the AI pass.

```sh
rp-pdf markdown FILE --ai --ocr [--model NAME] [--base-url URL] ...
rp-pdf validate-vlm-ocr [--model NAME] [--base-url URL] [--dpi N]
```

`--ocr` requires `--ai` and transcribes pages that have no text layer, in
place of their `no text layer` placeholders. `validate-vlm-ocr` generates a
synthetic PDF whose pages 2-3 carry text only as embedded images, OCRs it with
the configured model, and scores the transcriptions against the known text so
users can verify their setup before running on a real document. Library
entry point: `rp_pdf.ocr.transcribe_pages`. Design notes:
`dev-notes/phase-3-ocr-vlm.md`.

`rp-pdf markdown` writes Markdown to stdout (or to `-o FILE`); `--full` emits the whole
`MarkdownResult` as JSON instead. That flag was spelled `--json` until Phase 0.5.

---

# Appendix: original kickoff prompt (historical)

Kept verbatim as the record of how the package was built. It predates the workspace and
the rename, and describes the `pdfx` names throughout; it is not instructions for any
current work.

```
Read pdfx-spec.md in this directory and implement the project it describes.

Work in this order:
1. Scaffold the project: pyproject.toml (src layout, typer entry point `pdfx`),
   package skeleton, and dev tooling (pytest, ruff). Use uv for all environment
   and dependency management: `uv add` for dependencies, `uv add --dev` for dev
   tools, `uv run` to execute pytest and the CLI. Never invoke pip directly.
2. Implement pages.py (PageSpec parsing) with tests first.
3. Implement models.py and core.py function by function: get_index, get_text,
   get_tables, get_images, render_pages. Write tests alongside each using
   reportlab-generated fixture PDFs in conftest.py.
4. Implement cli.py with typer, matching the CLI design in the spec exactly.
5. Run the full test suite and fix failures. Then run each CLI command against
   a generated sample PDF and show me the output.

Constraints:
- Permissive licenses only: pypdf, pdfplumber, pdf2image, typer, pydantic.
  Do NOT use PyMuPDF/fitz.
- core.py must not print or import typer — it returns pydantic models only.
- Public API and CLI use 1-based page numbers.
- If poppler-utils is not installed, install it or clearly flag it.

When done, summarize what was built, test results, and any spec deviations.
```
