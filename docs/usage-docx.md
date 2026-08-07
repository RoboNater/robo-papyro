# rp-docx Usage Guide

`rp-docx` reads, creates, and edits Word documents. Structured read commands
(`index`, `text`, `tables`, `images`, `comments`, `changes`, `props`) print
JSON to stdout by default, so output pipes into other tools without a flag;
`markdown` is a conversion command and emits Markdown instead, exactly as
`convert` emits whatever format you asked for. The same functionality is
available as a Python library (`rp_docx`).

`rp-docx` is one package of the [robo-papyro](../README.md) suite; its commands
are also reachable as `rp docx ...`, byte-identically. Shared behavior — range
parsing, exit codes, external-binary discovery, rasterization — comes from
`rp-core` and is the same across every tool in the suite.

## Conventions

- **JSON is the default for structured reads.** `--plain` is the human opt-out.
  There is no `--json` flag anywhere in the suite: two tools differing on the
  shape of every *successful* call would be a worse inconsistency than any
  error-path difference, because it hits the common path. Conversion commands
  (`markdown`, `convert`, `render`) are the exception by nature — they emit the
  format you asked for, not a JSON envelope around it.

- **All indices are 1-based** — paragraphs, tables, images, sections.

- **`.dotx` and `.docx` are both accepted everywhere.** They differ only in one
  content type, and `rp-docx` handles the difference for you. (python-docx
  refuses to open a `.dotx` at all; see [Templates](#templates).)

- **Errors** go to stderr: a human-readable message, then an *error envelope* as
  the last line, so stdout stays clean and a scripted caller always has one line
  of parseable JSON to read.

  ```json
  {"error": {"type": "TemplateError", "message": "No template called 'memo'. Available: …", "hint": null, "exit_code": 1}}
  ```

  | Code | Meaning |
  |---|---|
  | `0` | success |
  | `1` | user or input error — missing file, unresolvable template, unfilled placeholder |
  | `2` | a required external binary is absent (run `rp-docx doctor`) |
  | `3` | the file is corrupt, or not an OOXML package |

- **No command overwrites its input** unless you say so. Editing commands
  (`append`, `replace`, `accept`, `reject`) need either `-o OUT` or `--in-place`,
  and refuse rather than guess — the two plausible defaults are "overwrite" and
  "invent a filename", and both are surprises that only surface afterwards.

- **No external binary is needed** for any read or write path. LibreOffice is
  needed only for `convert` and `render`; poppler only for `render`.

## Environment

| Variable | Meaning |
|---|---|
| `RP_DOCX_TEMPLATE_DIR` | Directories searched for templates named by bare name (`PATH`-separated) |
| `RP_DOCX_TEMPLATE` | Template used when a command names none |
| `RP_SUBPROCESS_TIMEOUT` | Suite-wide subprocess timeout, in seconds (default 600) |
| `RP_SOFFICE_PATH` | Directory holding `soffice`, if it is not on `PATH` |
| `RP_POPPLER_PATH` | Directory holding poppler's binaries, if not on `PATH` |

## CLI

Run via `uv run rp-docx ...` from the project directory, or `rp-docx ...` inside
an activated environment. `rp-docx COMMAND --help` shows full options.

### Reading

#### `rp-docx index FILE` — what is in this document

The command to run first. Counts everything in one pass, so finding out whether
a document has comments does not take eight calls.

```sh
rp-docx index report.docx
```

```json
{
  "path": "report.docx",
  "paragraph_count": 42, "word_count": 1180, "section_count": 2,
  "table_count": 3, "image_count": 1,
  "comment_count": 2, "tracked_change_count": 5,
  "has_headers_footers": true,
  "styles_used": ["Heading 1", "Heading 2", "List Bullet", "Normal"],
  "headings": [{"index": 1, "level": 1, "text": "Quarterly Report", "style": "Heading 1"}],
  "core_properties": {"title": "Quarterly Report", "author": "…", "…": null}
}
```

`table_count` includes tables nested inside cells; `paragraph_count` is body
paragraphs. A heading is a paragraph whose style is a `Heading N`, *or* whose
`w:outlineLvl` says so — which is what makes a house template's renamed heading
style still register as a heading.

#### `rp-docx text FILE` — paragraphs, optionally with formatting

```sh
rp-docx text report.docx
rp-docx text report.docx --style "Heading 2"     # only these
rp-docx text report.docx --runs                  # add per-run formatting
rp-docx text report.docx --plain                 # one line per paragraph
```

`--style` filters without renumbering: a filtered result still says where each
paragraph sits in the document. `--runs` adds each paragraph's runs with their
bold/italic/underline/font/size/colour — omitted otherwise, because run splits
are an artifact of the editor rather than of the document.

#### `rp-docx markdown FILE` — convert to Markdown

```sh
rp-docx markdown report.docx -o report.md
rp-docx markdown report.docx --embed-images      # inline as data URIs
```

Via mammoth. Images are dropped unless `--embed-images` is given: a Markdown
file referencing images that were never written is worse than one with none.

#### `rp-docx tables FILE` — tables as JSON, CSV, or Markdown

```sh
rp-docx tables report.docx                          # JSON
rp-docx tables report.docx --index 2                # just the second
rp-docx tables report.docx --format csv -o ./tables # one CSV per table
rp-docx tables report.docx --format md              # pipe tables
```

Nested tables are found and numbered in document order — python-docx's own
`document.tables` is top level only, and a table inside a cell is exactly where
a caller tends to find nothing. Each table carries `section_context`: the nearest
preceding heading, so a table found on its own can still be placed.

#### `rp-docx images FILE` — embedded images

```sh
rp-docx images report.docx              # metadata only
rp-docx images report.docx -o ./images  # and write them out
```

Reported whether or not they are written, with dimensions and alt text.

#### `rp-docx comments FILE` / `rp-docx changes FILE`

```sh
rp-docx comments report.docx
rp-docx comments report.docx --author "Ada Lovelace"    # repeatable
rp-docx changes report.docx
```

Comments carry their anchor text — the range the comment covers — and their
resolved state, which lives in a separate `commentsExtended.xml` part that may
not exist at all. Tracked changes are reported as `insertion`, `deletion`, or
`format`; a deletion's text comes from `w:delText`, so deletions are not
silently reported as empty.

#### `rp-docx props FILE` — core properties

### Writing

#### `rp-docx create` — build a document

```sh
rp-docx create -o out.docx --from-markdown notes.md
rp-docx create -o out.docx --from-markdown notes.md --template memo
rp-docx create -o out.docx --page-size a4 --title "Annual Review"
```

The template's body is kept, not cleared — a letterhead template's boilerplate
is the reason it exists, and Word's own "new from template" behaves the same
way. Markdown is appended after it.

**A supplied template wins on page size.** A house template that is A4 is A4
whatever `--page-size` says; passing both prints a note to stderr rather than
silently dropping the flag.

Markdown supported: headings 1–4, paragraphs, `**bold**`, `*italic*`, `` `code` ``,
`[links](url)`, bullet and numbered lists (nested by indent), GFM pipe tables,
horizontal rules, and fenced code blocks. Parsed by `rp_core.markdown` — the
small block/inline parser shared with `rp-pptx` — rather than by a third-party
library, since the grammar is small and no markdown library on the approved
license list covers it. `rp-docx` supplies its own renderer over the shared
parse tree.

#### `rp-docx append FILE --markdown FILE` — add to a document

Uses the document's own styles, so text added to a house-styled document is
house-styled too.

#### `rp-docx replace FILE --map JSON` — replace text anywhere

```sh
rp-docx replace contract.docx --map '{"{{ client }}": "Ada"}' -o filled.docx
rp-docx replace contract.docx --map ./values.json --in-place
rp-docx replace contract.docx --map ./values.json -o out.docx --ignore-case
```

`--map` takes either a path to a JSON file or the JSON itself.

This walks the body, table cells, text boxes, **every header and footer**, and
footnotes and endnotes. Body-only replacement is the classic silent bug. It also
works across run boundaries: Word routinely stores `{{ client }}` as `{{ cli` +
`ent }}`, which a naive replace misses while reporting success.

The result says what happened and where:

```json
{"output": "filled.docx",
 "replacements": {"{{ client }}": 3, "{{ absent }}": 0},
 "locations": ["body", "table:2", "header:1"]}
```

A key that matched nothing is reported with a count of zero rather than omitted,
so a caller checking whether its replacement landed does not have to know
whether a missing key means "absent" or "not attempted".

The replacement inherits the formatting of the run each match *starts* in;
`--no-preserve-formatting` strips that run's direct formatting instead.

#### `rp-docx template TEMPLATE --context JSON` — fill placeholders

```sh
rp-docx template memo --context ./client.json -o letter.docx
rp-docx template memo --context '{"client": {"name": "Ada"}}' -o letter.docx --no-strict
```

Syntax is `{{ key }}` and `{{ key.subkey }}` — **no expression evaluation and no
Jinja**. A template is data, and rendering one cannot run anything. Loops and
conditionals are out of scope: generate the varying part as Markdown and pass it
to `create` instead.

`--strict` (the default) fails if the context does not supply every placeholder,
listing the ones it missed — a contract with `{{ client.name }}` still in it is
worse than no document. `--no-strict` leaves them and reports them in
`unresolved`.

#### `rp-docx accept FILE` / `rp-docx reject FILE` — resolve tracked changes

```sh
rp-docx accept draft.docx -o final.docx
rp-docx reject draft.docx --author "Grace Hopper" -o final.docx
```

Accepting promotes insertions and discards deletions; rejecting does the inverse
and converts deleted text back to visible text. `--author` (repeatable) narrows
it, leaving everyone else's changes tracked. Formatting changes (`w:rPrChange`,
`w:pPrChange`) are handled too: rejecting one restores the properties it
recorded.

**Known limit.** Rejecting an *inserted paragraph mark* removes the revision
record but does not merge the two paragraphs back together, which is what Word
does. Text content is unaffected.

### Templates

House templates are the normal path, not the exception. `create` and `template`
both default to one.

**Resolution order** for `--template`:

1. An existing path, used as given
2. A bare name, resolved against `RP_DOCX_TEMPLATE_DIR`, then the checkout's
   `templates/local/` and `templates/` — trying `.dotx` before `.docx`
3. Nothing given → `RP_DOCX_TEMPLATE`, or python-docx's bundled default
4. Anything else → an error listing what *is* available

**Style mapping.** House templates rarely use Word's built-in style names, so
Markdown conversion goes through a `StyleMap` loaded from an optional
`<template>.stylemap.json` beside the template:

```json
{"h1": "House Heading 1", "body": "RP Body Text", "bullet": "House Bullet",
 "table": "Table Grid"}
```

If a mapped style is missing from the template, `rp-docx` **raises** — naming the
style and listing what the template does have. It never falls back silently:
that produces documents which look wrong in ways nobody notices until review.
The check happens per style at the point of use, so a document with no code
block does not need a code style.

`code` is the one role a stylemap may leave unset, because Word ships no code
style at all. Unset means code blocks render in the body style with a monospace
font. Naming a style makes it required, exactly like the others.

#### `rp-docx templates list` / `inspect NAME`

```sh
rp-docx templates list
rp-docx templates inspect memo
```

#### `rp-docx templates manifest FILE` — share a template's shape, not its content

```sh
rp-docx templates manifest ./templates/local/memo.dotx -o memo.manifest.json
```

A **manifest** describes a template's shape — style names, page geometry,
presence flags — and carries no document text, no image bytes, no author names,
and no path beyond the template's own basename. That is what makes it safe to
commit and to paste into an issue where the template itself could not go. It is
enforced by a test, not by convention.

#### `rp-docx templates synthesize MANIFEST -o OUT.dotx`

Rebuilds a structurally equivalent `.dotx` from a manifest: style definitions,
page size and margins, section count, and a placeholder header image when the
manifest records a letterhead. It does *not* reproduce fonts, colours, or
spacing — the goal is structural equivalence for testing style resolution, not
visual fidelity.

Together these let CI regression-test a confidential template's shape while the
template never leaves the machine that holds it.

#### `rp-docx templates stylemap FILE` — scaffold a stylemap

```sh
rp-docx templates stylemap memo.dotx -o memo.stylemap.json
```

Matches style names against common patterns to produce a starting point.
**Never authoritative** — the command says so on stderr. A generated stylemap
that happens to be wrong is worse than none, because it looks reviewed.

### Convert and render

```sh
rp-docx convert report.docx --to pdf -o report.pdf     # also odt, html
rp-docx render report.docx -o ./pages --dpi 150 --pages 1-5
rp-docx doctor
```

`convert` needs LibreOffice; `render` needs LibreOffice *and* poppler (the
document is converted to PDF first, then rasterized). Both are thin
re-exports of `rp-core` — no rendering implementation lives in this package.
`--pages` takes the suite's range syntax (`all`, `5`, `3-7`, `-4`, `7-`,
`1,3-5,9`).

Run `rp-docx doctor` to see what is installed.

## Library

Every public function returns a pydantic model (or a list of them) and takes
`pathlib.Path`s. Nothing in the library prints, and nothing imports typer.

```python
from pathlib import Path
from rp_docx import (
    get_index, get_text, get_tables, get_comments, get_tracked_changes,
    create, append_markdown, replace_text, accept_changes, fill_template,
    build_manifest, inspect_template, synthesize,
)

index = get_index(Path("report.docx"))
print(index.paragraph_count, [h.text for h in index.headings])

# Runs are only populated when asked for.
for paragraph in get_text(Path("report.docx"), runs_wanted=True):
    for run in paragraph.runs or []:
        if run.bold:
            print(run.text)

# Creating, on a house template.
create(Path("out.docx"), markdown="# Title\n\nBody.", template="memo")

# Replacement reports where it landed.
result = replace_text(
    Path("contract.docx"), {"{{ client }}": "Ada"}, output=Path("filled.docx")
)
print(result.replacements, result.locations)

# Filling a template; strict=False collects misses instead of raising.
filled = fill_template("memo", {"client": {"name": "Ada"}}, Path("letter.docx"))
print(filled.unresolved)

# A manifest carries a template's shape and none of its content.
manifest = build_manifest(Path("memo.dotx"))
synthesize(manifest, Path("rebuilt.dotx"))
```

Errors come from `rp_core.errors` by way of `rp_docx.errors`, so their exit
codes and serialized shape match every other tool in the suite:

```python
from rp_docx.errors import (
    RpDocxError,       # everything below
    MissingFileError,  # also a FileNotFoundError; exit 1
    TemplateError,     # unresolvable template, or a missing mapped style; exit 1
    PlaceholderError,  # strict fill with an unsupplied placeholder; exit 1
    InvalidDocxError,  # not a readable OOXML package; exit 3
)
```

### Reaching past python-docx

`rp_docx.ooxml` is the only place that knows *WordprocessingML* — the
namespace map, the `.dotx`/`.docx` content types, and part names like
`word/comments.xml`. The generic package mechanics underneath it (the zip
read/repack, content-type rewriting, and compiled-XPath helper) live in
`rp_core.ooxml` and are shared with `rp-pptx`; `rp_docx.docx.runs` is the only
place that knows how Word splits text. Markdown parsing itself is shared too:
`rp_core.markdown` holds the block/inline parser, and `rp_docx.docx.write`
supplies only the Word *renderer* over that shared AST. All of these are
public because they are useful on their own:

```python
from rp_docx import ooxml
from rp_docx.docx import runs

with ooxml.opened(Path("template.dotx")) as document:   # works on .dotx too
    print(len(document.styles))

root = ooxml.parse_part(Path("report.docx"), ooxml.DOCUMENT_PART)
for where, paragraph in runs.iter_paragraphs(root):
    print(where, runs.paragraph_text(paragraph))
```

## `.dotx` files

A `.dotx` and a `.docx` differ in exactly one thing: the main-document content
type in `[Content_Types].xml`. Everything else — parts, styles, markup — is the
same.

python-docx **does not open a `.dotx` at all**. It reads the content type, sees
the template one, and raises `ValueError: … is not a Word file`. Since house
templates are the normal path here rather than the exception, `rp_docx.ooxml`
retypes a copy in a temporary directory and opens that. Retyping is lossless in
both directions, so this costs a copy and nothing else.

The same applies on the way out: writing to a file named `.dotx` retypes it
after saving, because python-docx always writes the document content type — a
file named `.dotx` that is really a document is one Word opens as an ordinary
document, silently editing what you meant to keep as a template.
