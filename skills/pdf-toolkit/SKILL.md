---
name: pdf-toolkit
description: Read PDFs from the shell with rp-pdf — page index and outline, text, tables, search, embedded images, Markdown conversion, and page rendering. Use whenever a task involves reading a .pdf file, finding something inside one, or turning one into text, Markdown, or images. Handles encrypted PDFs, page labels, and scanned pages.
---

# Reading PDFs with `rp-pdf`

`rp-pdf` extracts structured information from PDF files. Every read command
prints JSON to stdout, so you can parse the result instead of scraping text.

Check it is installed: `rp-pdf --help` (or `rp pdf --help`). If it is not,
`uv sync` in the robo-papyro checkout.

## Start here

```sh
rp-pdf index FILE.pdf
```

Page count, page labels, metadata, outline, and page sizes. Do this before
anything else — it tells you how many pages there are and **what the document
calls them**, which is what every other command's `--pages` is interpreted
against.

## Commands

| Command | What you get |
|---|---|
| `rp-pdf index FILE` | Metadata, outline, per-page summary |
| `rp-pdf text FILE [--pages SPEC]` | Text per page, JSON; `--plain` for raw text |
| `rp-pdf tables FILE [--pages SPEC]` | Tables as JSON; `--csv DIR` writes one CSV per table |
| `rp-pdf search FILE QUERY` | Hits with surrounding context and page numbers |
| `rp-pdf images FILE [--out DIR]` | Image metadata; extracts when `--out` is given |
| `rp-pdf markdown FILE` | Markdown to stdout; `-o FILE` writes it instead |
| `rp-pdf render FILE --pages SPEC --out DIR` | PNGs of the pages |
| `rp-pdf doctor` | Which external tools are installed |

## Things that will bite you

**Search rather than extract-and-grep.** `rp-pdf search FILE "some phrase"`
normalizes whitespace, so a phrase matches across the line wraps extraction
introduces. Grepping extracted text misses those. `--regex` searches raw text
instead; `--max N` caps the result size.

**Page numbers are the document's, not the file's.** A PDF with page labels
(`cover`, `i`–`xx`, then `1` for content) is addressed by those labels:
`--pages 7-9` means the pages *printed* 7 to 9. Pass `--physical` for 1-based
positions instead. Every result carries both `physical_page` and
`labeled_page`, so cite whichever the reader will recognise.

**`--pages` spec:** `all`, `5`, `3-7`, `-4` (up to 4), `7-` (7 to the end),
`1,3-5,9`. A bare `-` is rejected; `all` already means everything.

**Empty text usually means a scan.** If `text` returns little or nothing, the
page is an image. `rp-pdf markdown FILE --ai --ocr` transcribes it with a
vision model. **`--ocr` requires `--ai`** — on its own it is rejected, because
OCR is a third stage of the AI pass rather than a separate engine. The run also
needs a model (`--model NAME` or `RP_PDF_VLM_MODEL`), a key in the environment
(`RP_PDF_VLM_API_KEY`, falling back to `OPENAI_API_KEY`), poppler for page
rendering, and the `ai` optional dependencies installed.

It is opt-in for a reason: it sends page images to a third-party service. Never
turn it on for material you have not been told is safe to send.

**Encrypted files** take `--password PW`. A missing or wrong password is
**exit 1** — it is an argument you can fix, not a broken document. Exit 3 means
the file could not be parsed as a PDF at all.

**Large documents:** `text` on a 500-page PDF is a lot of output. Use
`--pages` to narrow it, or `search` to find the part you want first.

## Reading the outcome

JSON on stdout is the result. Errors go to **stderr**, human message first and
a JSON envelope as the last line:

```json
{"error": {"type": "PopplerNotFoundError", "message": "…", "hint": "apt install poppler-utils", "exit_code": 2}}
```

| Exit | Meaning | What to do |
|---|---|---|
| 1 | Bad arguments — page spec, missing file, wrong password | Fix the call |
| 2 | A required external program is missing | `rp-pdf doctor`, then install what it names |
| 3 | Corrupt, unreadable, or not a PDF | Report it; do not retry |

Text extraction and rendering need **poppler** (`apt install poppler-utils`,
`brew install poppler`). `rp-pdf doctor` says whether it is there.

## As a library

```python
from rp_pdf import core

index = core.get_index("doc.pdf")                     # DocumentIndex
pages = core.get_text("doc.pdf", "1-3")               # list[PageText]
hits  = core.search("doc.pdf", "revenue", max_hits=20)
```

Every function returns a pydantic model. Nothing prints.

Full guide: `docs/usage.md` in the robo-papyro checkout.
