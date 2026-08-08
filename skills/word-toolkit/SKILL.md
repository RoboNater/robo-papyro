---
name: word-toolkit
description: Read, create, and edit Word documents from the shell with rp-docx — headings and text, tables, images, comments, tracked changes, Markdown conversion, creating documents on house templates, filling {{ placeholder }} templates, and find-and-replace that actually reaches headers and footers. Use whenever a task involves a .docx or .dotx file, or asks for a report, memo, or letter as a Word document.
---

# Word documents with `rp-docx`

`rp-docx` reads, creates, and edits `.docx` and `.dotx` files. Read commands
print JSON to stdout, so you can parse the result instead of scraping text.

Check it is installed: `rp-docx --help` (or `rp docx --help`).

## Start here

```sh
rp-docx index FILE.docx
```

Counts, styles used, the heading tree, and core properties. The heading list is
usually enough to decide what to do next.

## Reading

| Command | What you get |
|---|---|
| `rp-docx index FILE` | Counts, headings, styles used, properties |
| `rp-docx text FILE [--style "Heading 1"] [--runs]` | Paragraphs with styles |
| `rp-docx markdown FILE` | The document as Markdown |
| `rp-docx tables FILE [--index N] [--format csv\|md -o DEST]` | Tables as JSON, CSV, or Markdown |
| `rp-docx images FILE [--out DIR]` | Image metadata; extracts with `--out` |
| `rp-docx comments FILE` | Comments with authors, anchors, resolved state |
| `rp-docx changes FILE` | Tracked insertions, deletions, format changes |
| `rp-docx props FILE` | Title, author, dates, keywords |

## Writing

**Never edit an input in place unless you were asked to.** Every editing
command takes `-o OUT.docx`; `--in-place` exists and is explicit for a reason.

```sh
rp-docx create -o report.docx --from-markdown notes.md --template memo
rp-docx append report.docx --markdown more.md -o report-v2.docx
rp-docx replace report.docx --map '{"Acme":"Acme Corp"}' -o fixed.docx
rp-docx template memo --context ctx.json -o letter.docx
rp-docx accept draft.docx -o clean.docx        # or `reject`
```

Setting core properties has **no CLI command** — it is library-only
(`rp_docx.set_properties`), or an MCP tool (`docx_set_properties`) if you are
talking to `rp-mcp`. `rp-docx props FILE` reads them.

`create --from-markdown` understands headings, paragraphs, bullet and numbered
lists, pipe tables, fenced code, and thematic breaks.

## Things that will bite you

**`replace` is not a string replace, and that is the point.** Word splits a
logical string across runs arbitrarily, so a naive replacement finds nothing
*and reports success*. `rp-docx replace` reaches body, tables, text boxes,
headers, footers, footnotes, and endnotes, and it reports a per-key count —
check it. A count of 0 means the text is not there, not that it worked.

**Templates: list, inspect, then fill.**

```sh
rp-docx templates list                 # what resolves by name
rp-docx templates inspect memo         # its styles, page size, letterhead
```

Filling is strict by default, and that is how you discover the placeholder
names: a template with an unfilled `{{ client_name }}` fails and **names it**,
rather than shipping a document with the braces still in it. Run it once with
whatever context you have and read the error. (Listing them up front is
library-only — `rp_docx.find_placeholders` — or the `docx_find_placeholders`
MCP tool.)

`--template` takes a path or a bare name; a name resolves against the template
directories, which `RP_DOCX_TEMPLATE_DIR` adds to.

**Style resolution never falls back.** If a template lacks a style the Markdown
needs, `create` fails and names it rather than producing something that looks
wrong. Word defines no code style, so a Markdown document with a fenced code
block needs a template that has one.

**`.dotx` works everywhere `.docx` does.** python-docx refuses to open one;
`rp-docx` handles the difference.

**Indices are 1-based** — paragraphs, tables, images, sections.

## Reading the outcome

JSON on stdout. Errors on **stderr**, human message first and a JSON envelope
as the last line:

```json
{"error": {"type": "TemplateError", "message": "No template called 'memo'. Available: …", "hint": null, "exit_code": 1}}
```

| Exit | Meaning | What to do |
|---|---|---|
| 1 | Bad arguments — missing file, unknown template, unfilled placeholder | Fix the call |
| 2 | A required external program is missing | `rp-docx doctor` |
| 3 | Corrupt or not a Word file | Report it; do not retry |

Reading and writing need **no external program**. Only `convert` and `render`
need LibreOffice.

## As a library

```python
from pathlib import Path
from rp_docx import get_index, get_text, create, replace_text, fill_template

index = get_index(Path("report.docx"))
create(Path("out.docx"), markdown="# Title", template="memo")
result = replace_text(Path("in.docx"), {"Acme": "Acme Corp"}, output=Path("out.docx"))
print(result.replacements)          # per-key counts — check them
```

Full guide: `docs/usage-docx.md` in the robo-papyro checkout.
