# rp-docx — Word Document Toolkit Specification

**Version:** 1.0
**Status:** Ready for implementation (Phase 1)
**Parent document:** `robo-papyro-spec.md` — read that first. Its §7 (licensing) and §10 (constraints) govern this package.

---

## 1. Purpose

A Python package + CLI for reading, creating, and editing Word documents, designed so that agentic coding tools with no native document capability can operate on `.docx` files through a stable, scriptable interface.

Architecture mirrors `rp-pdf`: pure-function core returning pydantic models, thin CLI wrapper, thin MCP wrapper. Adding the MCP server in Phase 2 should be ~3 lines per tool.

**Distribution:** `rp-docx` · **Import:** `rp_docx` · **CLI:** `rp-docx`, also reachable as `rp docx`

### Non-goals
- Rendering fidelity guarantees
- Legacy binary `.doc` (not present in the corpus)
- Collaborative/real-time editing

---

## 2. Package Layout

```
packages/rp-docx/
├── pyproject.toml
├── src/rp_docx/
│   ├── __init__.py         # public API re-exports
│   ├── models.py           # docx-specific pydantic models only
│   ├── ooxml.py            # namespace map, zip unpack/repack, xpath helpers
│   ├── templates.py        # resolution, inspection, StyleMap
│   ├── docx/
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── runs.py         # run-offset mapping — the §6 utility, standalone
│   │   └── template.py     # {{ placeholder }} substitution
│   ├── cli.py              # typer — formatting and printing only
│   └── mcp_server.py       # Phase 2 stub
└── tests/
    ├── conftest.py         # fixture generators (build .docx via python-docx)
    ├── fixtures/           # hand-made files for tracked-changes/comments
    └── test_*.py
```

`Capability`, `ErrorEnvelope`, the error hierarchy, page-spec parsing, rendering, and CLI conventions come from `rp_core`. Do not redefine them.

`runs.py` is its own module because both `write.replace_text` and `template.fill_template` depend on it, and it is the highest-risk code in the package.

### Core contract
- `rp_docx.docx.*` and `rp_docx.templates` never print and never import typer
- Every public function returns a pydantic model or a list of them
- All paths in and out are `pathlib.Path`
- User-facing indices are 1-based
- No in-place mutation unless an explicit `output` path or `--in-place` is given

### Dependencies
`rp-core`, `python-docx` (MIT), `lxml` (BSD-3, transitive), `mammoth` (BSD-2), `typer` (MIT), `pydantic` (MIT), `Pillow` (MIT-CMU).

Forbidden: `docxtpl` (LGPL-2.1-only — templating is implemented natively, see §8), `pandoc` (GPL), `PyMuPDF` (AGPL).

---

## 3. Data Models (`models.py`)

```python
class DocumentIndex(BaseModel):
    path: Path
    paragraph_count: int
    word_count: int
    section_count: int
    table_count: int
    image_count: int
    comment_count: int
    tracked_change_count: int
    has_headers_footers: bool
    styles_used: list[str]
    headings: list[Heading]
    core_properties: CoreProperties

class Heading(BaseModel):
    index: int          # 1-based paragraph index
    level: int          # 1-9
    text: str
    style: str

class Paragraph(BaseModel):
    index: int
    text: str
    style: str
    list_level: int | None
    runs: list[Run] | None   # populated only when requested

class Run(BaseModel):
    text: str
    bold: bool
    italic: bool
    underline: bool
    font: str | None
    size_pt: float | None
    color: str | None        # hex

class Table(BaseModel):
    index: int
    rows: int
    cols: int
    data: list[list[str]]
    style: str | None
    section_context: str | None   # nearest preceding heading

class EmbeddedImage(BaseModel):
    index: int
    rel_id: str
    filename: str
    content_type: str
    width_px: int | None
    height_px: int | None
    alt_text: str | None
    extracted_path: Path | None

class Comment(BaseModel):
    id: str
    author: str
    initials: str | None
    date: datetime | None
    text: str
    anchor_text: str | None
    para_id: str | None          # w14:paraId
    resolved: bool

class TrackedChange(BaseModel):
    id: str
    type: Literal["insertion", "deletion", "format"]
    author: str
    date: datetime | None
    text: str
    paragraph_index: int

class CoreProperties(BaseModel):
    title: str | None
    author: str | None
    last_modified_by: str | None
    created: datetime | None
    modified: datetime | None
    revision: int | None
    category: str | None
    keywords: str | None

class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["dotx", "docx"]
    styles: list[str]            # paragraph + character styles available
    page_size: str
    has_letterhead: bool

class StyleMap(BaseModel):
    h1: str = "Heading 1"
    h2: str = "Heading 2"
    h3: str = "Heading 3"
    h4: str = "Heading 4"
    body: str = "Normal"
    bullet: str = "List Bullet"
    numbered: str = "List Number"
    code: str = "Source Code"
    table: str = "Table Grid"

class ReplaceResult(BaseModel):
    output: Path
    replacements: dict[str, int]   # placeholder -> count
    locations: list[str]           # "body", "table:2", "header:1", "footer:1"

class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]
```

---

## 4. Public API

### Read (`rp_docx.docx.read`)

```python
get_index(path: Path) -> DocumentIndex
get_text(path: Path, *, style_filter: str | None = None,
         runs: bool = False) -> list[Paragraph]
get_markdown(path: Path, *, embed_images: bool = False) -> str   # via mammoth
get_tables(path: Path, *, table_index: int | None = None) -> list[Table]
get_images(path: Path, *, output_dir: Path | None = None) -> list[EmbeddedImage]
get_comments(path: Path) -> list[Comment]
get_tracked_changes(path: Path) -> list[TrackedChange]
get_properties(path: Path) -> CoreProperties
```

### Write (`rp_docx.docx.write`)

```python
create(output: Path, *, markdown: str | None = None,
       template: str | Path | None = None, title: str | None = None,
       page_size: Literal["letter", "a4"] = "letter") -> Path

append_markdown(path: Path, markdown: str, *, output: Path | None = None) -> Path

replace_text(path: Path, replacements: dict[str, str], *,
             output: Path | None = None, match_case: bool = True,
             preserve_formatting: bool = True) -> ReplaceResult

set_properties(path: Path, props: CoreProperties, *,
               output: Path | None = None) -> Path

accept_changes(path: Path, *, output: Path | None = None,
               authors: list[str] | None = None) -> Path
reject_changes(path: Path, *, output: Path | None = None,
               authors: list[str] | None = None) -> Path
```

### Templates (`rp_docx.templates`)

```python
list_templates() -> list[TemplateInfo]
resolve_template(name_or_path: str | Path | None) -> Path
inspect_template(path: Path) -> TemplateInfo
load_stylemap(template: Path) -> StyleMap
fill_template(template: str | Path, context: dict, output: Path, *,
              strict: bool = True) -> FillResult
```

### Render / convert

Thin re-exports of `rp_core.render.render_pages` and `rp_core.binaries.soffice_convert`. No implementation in this package.

---

## 5. Templates Are First-Class

House templates exist and are the normal path, not the exception. `create()` and `fill_template()` default to a house template rather than python-docx's built-in default.

**Resolution order:**
1. Explicit `Path` that exists → use it
2. Bare name (e.g. `"memo"`) → resolve against `RP_TEMPLATE_DIR`, then `<repo>/templates/`, trying `<name>.dotx` then `<name>.docx`
3. `None` → the configured default template name, or python-docx's built-in if none configured
4. Unresolvable name → `InputError` listing available templates

**Style mapping.** House templates rarely use Word's built-in style names. Markdown→docx conversion maps through `StyleMap`, loaded from an optional `<template>.stylemap.json` sitting beside the template — never hardcoded.

If a mapped style is absent from the template, raise `InputError` naming the missing style and listing what the template does have. **Never silently fall back**: that produces documents which look wrong in ways nobody notices until review.

**Required test:** create from a template → read back → assert house styles survive round-trip and header/section content is preserved.

---

## 6. The Run-Spanning Problem — Read This First

Word splits a single logical string across multiple `w:r` runs arbitrarily, driven by spellcheck state, rsid, and formatting changes. A naive `run.text.replace()` misses any placeholder straddling a run boundary. This is why `docxtpl` exists, and reimplementing it correctly is the main engineering work in this package.

**Required approach:**
1. For each paragraph, build a concatenated string plus a run-offset map
2. Locate matches against the concatenated string
3. Write the replacement into the run containing the match start; blank the tail of spanned runs
4. Inherit formatting from the first spanned run (documented behavior)
5. Walk **table cells, headers, footers, footnotes, endnotes, and text boxes** — body-only replacement is a common silent bug

Build and unit-test `runs.py` before anything that depends on it. Required cases: a placeholder split across three runs; a match spanning a formatting boundary; a match inside a table cell; overlapping candidate matches.

---

## 7. Comments and Tracked Changes Need Raw XML

`python-docx` has no API for these. Access via `document.part` and lxml xpath.

- Insertions: `w:ins`. Deletions: `w:del` containing `w:delText` — **not** `w:t`
- Comment anchors: `w:commentRangeStart` / `w:commentRangeEnd` + `w:commentReference`, with bodies in `word/comments.xml`
- Resolved state lives in `word/commentsExtended.xml`, keyed by `w15:paraId` — a separate part that may not exist
- Accepting a change: unwrap `w:ins` (promote children), delete the `w:del` subtree. Rejecting is the inverse and must convert `w:delText` back to `w:t`

The namespace map lives in `ooxml.py` and nowhere else.

---

## 8. Templating Without docxtpl

Minimal, safe substitution:
- Syntax: `{{ key }}` and `{{ key.subkey }}` only. **No expression evaluation, no Jinja.**
- Loops and conditionals are out of scope — generate from markdown instead
- Reuses `runs.py`; the same run-splitting problem applies to placeholders
- `strict=True` raises on unresolved placeholders; `strict=False` leaves them and reports them in `FillResult.unresolved`

---

## 9. Other Footguns

**Markdown → docx.** Build with `python-docx` against the resolved template so house styles are inherited. Support at minimum: headings 1–4, paragraphs, bold/italic/code spans, bullet and numbered lists, GFM pipe tables, horizontal rules, hyperlinks. Hand-roll a small block parser rather than adding a markdown library with an unvetted license.

**Page size.** python-docx defaults to US Letter. Set it explicitly on `create()` rather than inheriting silently — unless a template is supplied, in which case the template wins.

**Table shading and widths.** Use a clear/solid pattern with an explicit fill hex; an omitted or mis-specified pattern renders black in some viewers. Set both table- and cell-level widths in absolute twips — percentage widths render inconsistently outside Word.

---

## 10. CLI Design

```
rp-docx doctor                                # delegates to rp_core.doctor

rp-docx index      FILE [--json]
rp-docx text       FILE [--style STYLE] [--runs] [--json]
rp-docx markdown   FILE [-o OUT] [--embed-images]
rp-docx tables     FILE [--index N] [--format json|csv|md] [-o DIR]
rp-docx images     FILE -o DIR [--json]
rp-docx comments   FILE [--json] [--author NAME]
rp-docx changes    FILE [--json] [--author NAME]
rp-docx props      FILE [--json]

rp-docx create     -o OUT [--from-markdown FILE] [--template NAME|PATH]
                          [--page-size letter|a4]
rp-docx append     FILE --markdown FILE [-o OUT]
rp-docx replace    FILE --map JSON [-o OUT] [--no-preserve-formatting]
                          [--ignore-case]
rp-docx template   TEMPLATE --context JSON -o OUT [--no-strict]
rp-docx accept     FILE [-o OUT] [--author NAME]
rp-docx reject     FILE [-o OUT] [--author NAME]

rp-docx templates list [--json]
rp-docx templates inspect NAME [--json]

rp-docx convert    FILE --to pdf|odt|html [-o OUT]
rp-docx render     FILE -o DIR [--dpi 150] [--pages 1-5]
```

**Rules.** `--json` on every read command emits the model via `model_dump_json()` — this is the agent-facing path and must be stable and complete. Default output is human-readable. Errors, exit codes, and `--json` handling all come from `rp_core.clikit`. Never overwrite an input file without `--in-place`.

---

## 11. Testing

- `conftest.py` generates fixture `.docx` files programmatically with `python-docx`: headings, styled runs, nested tables, images, headers/footers
- Tracked-changes and comments fixtures **cannot** be generated by `python-docx`. The implementation should report which hand-made files are needed; expect 2–3 small files under `tests/fixtures/`, each < 30 KB
- Round-trip tests: create → read → assert; replace → read → assert; accept-changes → assert no `w:ins`/`w:del` remain
- Explicit test that replacement works in table cells, headers, and footers
- Explicit test for a placeholder split across runs
- Explicit test that a template's house styles survive create → read
- Mark LibreOffice-dependent tests `@pytest.mark.requires_soffice` and skip cleanly when absent
- Target > 85% coverage on `docx/`, `ooxml.py`, and `templates.py`

---

## 12. Phase 1 — Execution Plan

**Step 1.** Scaffold `packages/rp-docx/` as a workspace member depending on `rp-core`. Entry point `rp-docx`, plus the `robo_papyro.commands` entry point registering `docx`.

**Step 2.** Implement `models.py` per §3, minus anything already in `rp_core` — import those.

**Step 3.** Implement `ooxml.py`: namespace map, zip unpack/repack, xpath helpers. Tests first.

**Step 4.** Implement `docx/runs.py` per §6 as a standalone, unit-tested function, before anything depends on it. Cover all four required cases.

**Step 5.** Implement `templates.py` per §5. Then **stop and report**: run `rp-docx templates inspect` against the real house template and show the style list, so the first `.stylemap.json` can be authored by hand before the rest hardens around guesses.

**Step 6.** Implement `docx/read.py` in order: `get_properties`, `get_index`, `get_text`, `get_tables`, `get_images`, `get_comments`, `get_tracked_changes`. Tests alongside each. Report which fixture files need to be supplied by hand.

**Step 7.** Implement `docx/write.py`, then `docx/template.py`. Both build on `runs.py`.

**Step 8.** Implement `cli.py` per §10 using `rp_core.clikit`. Leave `mcp_server.py` as a documented stub.

**Step 9.** Run the full suite. Then run each CLI command against a generated sample document, and verify `rp docx index FILE` works through the umbrella.

**Definition of done:** suite green, coverage target met, both `rp-docx` and `rp docx` functional, nothing outside the approved license list in `uv.lock`, and a written list of any place §6–§9 turned out to be wrong in practice.
