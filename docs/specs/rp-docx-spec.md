# rp-docx — Word Document Toolkit Specification

**Version:** 1.3
**Status:** **Implemented (Phase 1 complete).** Validation against a real house template (§13) is still outstanding.
**Parent document:** `robo-papyro-spec.md` v1.2 — read that first. Its §7 (licensing) and §10 (constraints) govern this package.

**Changes from v1.2:** corrections from implementation, each marked **[v1.3]** in place. §3 makes `StyleMap.code` optional, because the specified default named a style Word does not ship · §5.1 adds the wrong-path case and states that style checking is lazy · §5.3 records the answer to its own question: python-docx does not open a `.dotx` at all · §10 adds `--in-place` and makes `images -o` optional · §11.3's hand-made fixture files turned out to be unnecessary. The full list, with reasoning, is in [`dev-notes/status-robo-papyro-phase-1.md`](../../dev-notes/status-robo-papyro-phase-1.md).

**Changes from v1.1:** §5 adds template manifests and synthesis · §5.3 adds the `.dotx` content-type handling · §10 adds `templates manifest` and `templates synthesize` · §11 replaces the corporate-template dependency with three synthetic fixtures and states the no-binary-templates-in-git rule · §12 step 4 no longer blocks on a corporate file; Phase 1 is now fully self-contained.

**Changes from v1.0:** layout and §4 updated for the `rasterize` / `render_pages` split · §3 drops models now owned by `rp-core` · §10 switches to JSON-by-default with `--plain`.

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
│   ├── ooxml.py            # WordprocessingML namespace map, content-type strings, part names, .dotx retyping
│   ├── templates.py        # resolution, inspection, StyleMap, manifest, synthesis
│   ├── docx/
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── runs.py         # run-offset mapping — the §6 utility, standalone
│   │   └── template.py     # {{ placeholder }} substitution
│   ├── cli.py              # typer — formatting and printing only
│   └──                     # (no mcp_server.py: Phase 2 put the server in rp-mcp)
└── tests/
    ├── conftest.py         # generates all fixture documents and templates — nothing binary is committed
    ├── fixtures/
    │   └── *.manifest.json # template shapes — text, not binaries; empty until a real template lands
    └── test_*.py
```

**Owned by `rp-core`, never redefined here:** `Capability`, `ErrorDetail`, `ErrorEnvelope`, the exception hierarchy, range parsing (`rp_core.ranges`), binary discovery, rasterization, and all CLI conventions. **[Added Phase 2.5, per `rp-pptx-spec.md` §12 step 2]** the generic OOXML package mechanics — zip read/repack, content-type reading and rewriting, the compiled-XPath helper (`rp_core.ooxml`) — and the shared Markdown block/inline parser (`rp_core.markdown`) also moved out of this package and into `rp-core`, once `rp-pptx` needed the same mechanics. `rp_docx.ooxml` now wraps `rp_core.ooxml` with the WordprocessingML namespace map, the two content-type strings, and Word-specific errors; `rp_docx.docx.write` keeps its own Markdown-to-docx *renderer* over the shared AST rather than its own parser. See `dev-notes/status-robo-papyro-phase-2.5.md` for the rationale and the refactor's test-compatibility record.

`runs.py` is its own module because both `write.replace_text` and `template.fill_template` depend on it, and it is the highest-risk code in the package.

### Core contract
- `rp_docx.docx.*` and `rp_docx.templates` never print and never import typer
- Every public function returns a pydantic model or a list of them
- All paths in and out are `pathlib.Path`
- User-facing indices are 1-based
- No in-place mutation unless an explicit `output` path or `--in-place` is given
- Package-specific settings use the `RP_DOCX_*` prefix (parent §2)

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

class StyleDef(BaseModel):
    name: str
    type: Literal["paragraph", "character", "table", "numbering"]
    builtin: bool
    base_style: str | None

class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["dotx", "docx"]
    styles: list[StyleDef]
    page_size: str
    has_letterhead: bool

class TemplateManifest(BaseModel):
    """Redacted-by-construction description of a template's shape.

    Carries structure only — style names, page geometry, presence flags.
    Never document text, never image bytes. Safe to commit and to share
    outside the environment holding the original template.
    """
    name: str
    format: Literal["dotx", "docx"]
    styles: list[StyleDef]
    page_size: str
    page_margins_twips: dict[str, int] | None
    default_paragraph_style: str | None
    has_letterhead: bool
    header_image_count: int
    footer_present: bool
    section_count: int
    stylemap: StyleMap | None      # if a .stylemap.json sits beside the template

class StyleMap(BaseModel):
    h1: str = "Heading 1"
    h2: str = "Heading 2"
    h3: str = "Heading 3"
    h4: str = "Heading 4"
    body: str = "Normal"
    bullet: str = "List Bullet"
    numbered: str = "List Number"
    code: str | None = None          # [v1.3] optional; see below
    table: str = "Table Grid"
```

**[v1.3] `code` is optional, and it is the only role that is.** v1.2 gave it
`= "Source Code"`, which is [pandoc's name for the style it applies to code
blocks](https://pandoc.org/MANUAL.html#custom-styles) — not a name Word defines.
Word ships **no code paragraph style at all**, and neither does python-docx's
bundled default template, so combined with §5.1's "never silently fall back"
that default made every Markdown document containing a code block fail on the
default template. (Pandoc is a forbidden dependency under §7, which is likely
how the name reached this spec without the style behind it.)

`None` means "this template has no code style", and code blocks render in the
body style with a monospace font. Naming a style still makes it *required*,
exactly like every other role: optional means "may be unset", not "may be
wrong".

```python

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
build_manifest(path: Path) -> TemplateManifest
synthesize(manifest: TemplateManifest, output: Path) -> Path
fill_template(template: str | Path, context: dict, output: Path, *,
              strict: bool = True) -> FillResult
```

### Render / convert

Thin re-exports of `rp_core.render.render_pages` and `rp_core.binaries.soffice_convert`. `rp-docx` has no numbering or naming requirements beyond the default, so it uses the convenience wrapper and never touches `rasterize` directly. No rendering implementation lives in this package.

---

## 5. Templates

House templates are the normal path, not the exception. `create()` and `fill_template()` default to a house template rather than python-docx's built-in default.

### 5.1 Resolution

1. Explicit `Path` that exists → use it
2. Bare name (e.g. `"memo"`) → resolve against `RP_DOCX_TEMPLATE_DIR`, then `<repo>/templates/local/` and `<repo>/templates/`, trying `<name>.dotx` then `<name>.docx`
3. `None` → the configured default template name (`RP_DOCX_TEMPLATE`), or python-docx's built-in if none configured
4. **[v1.3]** A path-shaped argument that does not exist → `InputError` naming the *path*
5. Unresolvable name → `InputError` listing available templates

**[v1.3] Case 4 is new, and it matters more than it looks.** Without it, `--template ../drafts/memo.dotx` falls through to case 5 and reports "No template called '../drafts/memo.dotx'. Available: memo, letter…" — sending the user to hunt the template directories for a typo in their own path. Anything carrying a suffix or a path separator is a wrong path, not a name to look up.

**[v1.3]** `resolve_template` returns a `Path` in every case, falling back to python-docx's own bundled default rather than to a `None` every caller downstream would have to special-case.

**Style mapping.** House templates rarely use Word's built-in style names. Markdown→docx conversion maps through `StyleMap`, loaded from an optional `<template>.stylemap.json` sitting beside the template — never hardcoded.

If a mapped style is absent from the template, raise `InputError` naming the missing style and listing what the template does have. **Never silently fall back**: that produces documents which look wrong in ways nobody notices until review.

**[v1.3] "Absent" means absent *when needed*.** The check happens per style at the point of use, not eagerly over the whole `StyleMap`. Read eagerly, this rule rejects python-docx's own default template — because Word defines no code style, for a role most documents never use. A document containing no code block does not need a code style. Lazy checking is also what makes an adversarial template fixture meaningful: `hostile` lacks "Heading 1", so markdown *with* a top-level heading fails loudly while markdown without one succeeds.

### 5.2 Manifests and synthesis

The real house templates are confidential and cannot enter this repository. `TemplateManifest` solves this: it captures a template's *shape* — style names, page geometry, presence flags — and no content whatsoever.

**The loop:**
1. `build_manifest()` runs against the real template, wherever it lives, and emits JSON
2. That JSON is committed to `tests/fixtures/` — it is text, diffable, and carries nothing confidential
3. `synthesize()` reconstructs a structurally equivalent `.dotx` from the manifest at test time
4. CI exercises the real template's shape without the file ever leaving the machine that holds it

This also makes debugging shareable: a manifest can be pasted into an issue or a conversation where the template itself could not.

**Redaction is a correctness property, not a convention.** `TemplateManifest` must never carry document text, image bytes, author names, or file paths outside the template's own basename. Add a test asserting that a manifest built from a template containing distinctive body text does not contain that text anywhere in its serialized form. If a future field would violate this, it does not belong in the manifest.

`synthesize()` reproduces: style definitions (name, type, base style), page size and margins, section count, and a placeholder header image when `has_letterhead` is set. It does not attempt to reproduce fonts, colors, or spacing — the goal is structural equivalence for testing style resolution, not visual fidelity.

### 5.3 `.dotx` handling

`.dotx` and `.docx` differ chiefly in `[Content_Types].xml`: the template content type is `application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml`.

`ooxml.py` provides:

```python
retype_as_template(path: Path, output: Path | None = None) -> Path
retype_as_document(path: Path, output: Path | None = None) -> Path
```

so fixtures can produce genuine `.dotx` files and so `synthesize()` can emit the right type.

**[v1.3] Verified, and the answer changes the design: `python-docx` does not open a `.dotx` at all.** It reads `[Content_Types].xml`, sees the template content type, and raises `ValueError: … is not a Word file`. Retyping is nonetheless **lossless in both directions** — the part list is identical across a retype → open → save → retype cycle.

So the two functions above are not a fixture convenience, as v1.2 framed them; they are load-bearing:

- **On the way in**, every entry point accepting a document goes through `ooxml.opened(path)`, which retypes a template into a temporary copy and opens that. Calling `docx.Document(path)` directly works right up until someone passes a template, which is the normal path in this package rather than the exception. `mammoth` needs the same treatment.
- **On the way out**, `ooxml.save(document, output)` retypes when the output is named `.dotx`, because python-docx always writes the *document* content type. A file named `.dotx` that is really a document is one Word opens as an ordinary document — silently editing what the user meant to keep as a template.

This is asserted rather than remembered, in `test_ooxml.py::TestContentTypes`: if a future python-docx learns to open templates, that test fails and `opened()` can be simplified, which is worth being told about.

`resolve_template` must find `.dotx` before `.docx` when both exist — test this.

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
- `strict=True` raises `InputError` on unresolved placeholders; `strict=False` leaves them and reports them in `FillResult.unresolved`

---

## 9. Other Footguns

**Markdown → docx.** Build with `python-docx` against the resolved template so house styles are inherited. Support at minimum: headings 1–4, paragraphs, bold/italic/code spans, bullet and numbered lists, GFM pipe tables, horizontal rules, hyperlinks. Hand-roll a small block parser rather than adding a markdown library with an unvetted license.

**Page size.** python-docx defaults to US Letter. Set it explicitly on `create()` rather than inheriting silently — unless a template is supplied, in which case the template wins.

**Table shading and widths.** Use a clear/solid pattern with an explicit fill hex; an omitted or mis-specified pattern renders black in some viewers. Set both table- and cell-level widths in absolute twips — percentage widths render inconsistently outside Word.

---

## 10. CLI Design

```
rp-docx doctor                                # via rp_core.clikit.doctor_command

rp-docx index      FILE [--plain]
rp-docx text       FILE [--style STYLE] [--runs] [--plain]
rp-docx markdown   FILE [-o OUT] [--embed-images]
rp-docx tables     FILE [--index N] [--format json|csv|md] [-o DIR]
rp-docx images     FILE [-o DIR] [--plain]      # [v1.3] -o optional
rp-docx comments   FILE [--author NAME] [--plain]
rp-docx changes    FILE [--author NAME] [--plain]
rp-docx props      FILE [--plain]

rp-docx create     -o OUT [--from-markdown FILE] [--template NAME|PATH]
                          [--page-size letter|a4]
rp-docx append     FILE --markdown FILE (-o OUT | --in-place)
rp-docx replace    FILE --map JSON (-o OUT | --in-place)
                          [--no-preserve-formatting] [--ignore-case]
rp-docx template   TEMPLATE --context JSON -o OUT [--no-strict]
rp-docx accept     FILE (-o OUT | --in-place) [--author NAME]
rp-docx reject     FILE (-o OUT | --in-place) [--author NAME]

rp-docx templates list                [--plain]
rp-docx templates inspect NAME        [--plain]
rp-docx templates manifest FILE       [-o OUT.manifest.json]
rp-docx templates synthesize MANIFEST -o OUT.dotx
rp-docx templates stylemap FILE       [-o OUT.stylemap.json]   # scaffold, best-effort

rp-docx convert    FILE --to pdf|odt|html [-o OUT]
rp-docx render     FILE -o DIR [--dpi 150] [--pages 1-5]
```

`templates stylemap` emits a best-effort `StyleMap` scaffold by matching a template's style names against common patterns, for a human to correct. It is a convenience, never authoritative — a generated stylemap must be reviewed before use, and the command says so in its output.

**Rules.**
- **JSON is the default output** for every read command, emitted via `model_dump_json()`. This is the agent-facing path and must be stable and complete. `--plain` produces human-readable output. There is no `--json` flag — parent §4.6.
- Errors, exit codes, and the `ErrorEnvelope` payload come from `rp_core.clikit`. Do not construct error output locally.
- `--pages` accepts the range syntax parsed by `rp_core.ranges`.
- Never overwrite an input file without `--in-place`. **[v1.3]** v1.2's command
  list omitted the flag its own rules require; every editing command now takes
  it, and refuses rather than guessing when given neither it nor `-o`. The two
  plausible defaults — overwrite the input, or invent a filename — are both
  surprises that surface only afterwards.
- **[v1.3]** `--map` and `--context` accept either a path to a JSON file or the
  JSON itself. A person types a filename; a script that already holds the
  mapping should not have to write it to disk first.
- **[v1.3]** `--author` is repeatable, on `comments`, `changes`, `accept`, and
  `reject`.
- Every new subcommand must be registered wherever the CLI's dispatcher requires it, and the invariant test in parent §10 must cover this CLI too.

---

## 11. Testing

### 11.1 No binary templates in git

Template fixtures are **generated at test time**, not committed. A downloaded or corporate `.dotx` in the repo is a licensing question, an opaque diff, and a debugging hazard all at once — when a test fails you cannot tell whether the code or the template changed.

`templates/local/` is gitignored and documented in `templates/README.md` as the drop point for real templates during manual testing. Nothing there is ever required for CI.

**No binaries are committed at all**, per the §11.3 outcome: even the tracked-changes/comments fixtures `python-docx` cannot produce through its own API are generated in `conftest.py` by writing hand-crafted XML parts onto an otherwise-generated document, rather than checked in as files.

### 11.2 Three synthetic templates, built in `conftest.py`

Fixtures should be **adversarial**, not realistic. Realism is not what catches bugs here.

| Fixture | Purpose |
|---|---|
| `minimal` | Built-in style names only, Letter, no header. The happy path and the default-`StyleMap` path. |
| `house_like` | Non-Word style names (`"RP Body Text"`, `"House Heading 1"`), a style name containing a space and a non-ASCII character (`"Résumé Heading"`), A4 page size, a header containing an image, a linked character style, and a `.stylemap.json` beside it. |
| `hostile` | Missing a style the `StyleMap` maps to; no `.stylemap.json`; a style whose name differs from another only by case. Exists to prove failures are loud. |

Required assertions:
- `house_like` round-trips: create → read → house styles preserved, header and section content intact
- `hostile` raises `InputError` naming the missing style and listing what the template does have — never a silent fallback
- A4 from `house_like` wins over `create()`'s Letter default
- `resolve_template` prefers `.dotx` over `.docx` when both exist
- A manifest built from a template containing distinctive body text does not contain that text (§5.2)
- `synthesize(build_manifest(t))` produces a template whose `TemplateInfo.styles` equals the original's

### 11.3 Everything else

- Document fixtures (headings, styled runs, nested tables, images, headers/footers) are generated programmatically in `conftest.py`
- ~~Tracked-changes and comments fixtures **cannot** be generated by `python-docx`. The implementation should report which hand-made files are needed; expect 2–3 files under `tests/fixtures/`, each < 30 KB~~ — **[v1.3] none were needed.** True that python-docx cannot produce them, but they can still be *generated*: `conftest.py` replaces a generated document's body with hand-written XML, and for comments appends `comments.xml` / `commentsExtended.xml` with their relationships and content-type overrides. More work than committing two binaries, and the right trade for the same reason §11.1 gives — a generated fixture cannot drift, so a failure is always the code. `tests/fixtures/` stays empty, reserved for the `*.manifest.json` a real template will produce
- Test module names must not collide with those in other packages. `importmode = "importlib"` at the workspace root makes this non-fatal, but distinct names remain the convention
- Round-trip tests: create → read → assert; replace → read → assert; accept-changes → assert no `w:ins`/`w:del` remain
- Explicit test that replacement works in table cells, headers, and footers
- Explicit test for a placeholder split across runs
- Explicit test that read commands emit JSON with no flag, and human output with `--plain`
- Mark LibreOffice-dependent tests `@pytest.mark.requires_soffice` and skip cleanly when absent
- Target > 85% coverage on `docx/`, `ooxml.py`, and `templates.py`

---

## 12. Phase 1 — Execution Plan

**[v1.3] All nine steps are complete.** The outcome, including the checkpoint reports steps 3, 4 and 6 asked for and the full list of places §5–§9 turned out to be wrong, is in [`dev-notes/status-robo-papyro-phase-1.md`](../../dev-notes/status-robo-papyro-phase-1.md). The plan below is kept as written, as the record of what was asked for.

Prerequisite: Phase 0.5 steps 1–4 merged. **No corporate template is required at any point.** *(Held: none was used.)*

**Step 1.** Scaffold `packages/rp-docx/` as a workspace member depending on `rp-core`. Entry point `rp-docx`, plus the `robo_papyro.commands` entry point registering `docx`. Verify `rp docx --help` resolves through the umbrella before writing further code.

**Step 2.** Implement `models.py` per §3, minus anything owned by `rp_core` — import those.

**Step 3.** Implement `ooxml.py`: namespace map, zip unpack/repack, xpath helpers, and the content-type retyping from §5.3. Tests first. Report whether `python-docx` opens and round-trips `.dotx` cleanly.

**Step 4.** Implement `templates.py` per §5, and build the three synthetic fixtures from §11.2 in `conftest.py`. Then **report**: show `inspect_template` output for `house_like`, the manifest built from it, and the result of synthesizing that manifest back into a template. Continue without waiting — this checkpoint exists to surface surprises, not to block.

**Step 5.** Implement `docx/runs.py` per §6 as a standalone, unit-tested function, before anything depends on it. Cover all four required cases.

**Step 6.** Implement `docx/read.py` in order: `get_properties`, `get_index`, `get_text`, `get_tables`, `get_images`, `get_comments`, `get_tracked_changes`. Tests alongside each. Report which hand-made fixture files are needed.

**Step 7.** Implement `docx/write.py`, then `docx/template.py`. Both build on `runs.py` and the resolved `StyleMap`.

**Step 8.** Implement `cli.py` per §10 using `rp_core.clikit`. Leave `mcp_server.py` as a documented stub. **Resolved:** Phase 2 implemented the server as `rp_mcp.docx` and deleted the stub. This package has no `mcp_server.py`, and must not grow one — see `rp-mcp-spec.md`.

**Step 9.** Run the full suite. Then run each CLI command against a generated sample document, and verify `rp docx index FILE` and `rp-docx index FILE` produce identical output.

**Definition of done:** suite green with no binary template committed; coverage target met; both `rp-docx` and `rp docx` functional; JSON emitted by default with `--plain` working; errors matching `ErrorEnvelope`; nothing outside the approved license list in `uv.lock`; and a written list of any place §5–§9 turned out to be wrong in practice.

---

## 13. After Phase 1 — Validating Against the Real Template

Phase 1 ships without ever seeing a corporate template. Validation is a separate, manual pass:

1. Drop the real `.dotx` into `templates/local/`
2. `rp-docx templates inspect` → confirm the style list is read correctly
3. `rp-docx templates stylemap` → scaffold, then hand-correct into the real `.stylemap.json`
4. `rp-docx create --from-markdown ... --template <real>` → open in Word, confirm house styles applied
5. `rp-docx templates manifest` → commit the manifest to `tests/fixtures/` so CI regression-tests the real template's shape from then on

Only step 5 produces a repository artifact, and it carries no confidential content by construction (§5.2). Everything discovered in steps 2–4 comes back as a defect report or a spec correction, not as a file.
