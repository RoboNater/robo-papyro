# rp-pptx — PowerPoint Toolkit Specification

**Version:** 1.0
**Status:** Ready for implementation (Phase 2.5), blocked on nothing — the phase's one external input, a modern-comments reference deck (§7), gates a deferrable sub-scope, not the phase
**Parent document:** `robo-papyro-spec.md` v1.3 — read that first. Its §7 (licensing) and §10 (constraints) govern this package.

This spec is written after `rp-docx` shipped, and it inherits Phase 1's findings as requirements rather than rediscovering them: template retyping is load-bearing (§5.3 — verified against python-pptx 1.0.2, not assumed), role→name checking is lazy (§5.1), template resolution distinguishes a wrong path from an unknown name (§5.1), every editing command takes `--in-place` and refuses to guess (§10), and no fixture binary is committed — everything is generated, including the comment fixtures python-pptx cannot produce (§11).

---

## 1. Purpose

A Python package + CLI for reading, creating, and editing PowerPoint presentations, so that agentic coding tools with no native document capability can operate on `.pptx` files through a stable, scriptable interface.

Architecture mirrors `rp-docx`: pure-function core returning pydantic models, thin CLI wrapper, thin MCP wrapper. The `rp-mcp` server for this package should be ~3 lines per tool.

**Distribution:** `rp-pptx` · **Import:** `rp_pptx` · **CLI:** `rp-pptx`, also reachable as `rp pptx`

### Non-goals
- Rendering fidelity guarantees — LibreOffice converts; we don't chase pixel parity
- Legacy binary `.ppt` (not present in the corpus)
- Authoring animations, transitions, or embedded media — existing ones pass through edits untouched
- Chart *creation* — charts are read (§4); writing them means shipping spreadsheet parts and is out of scope until a real deck needs it
- Merging or splitting decks — python-pptx cannot copy a slide between presentations (the slide's relationship graph doesn't come with it), and reimplementing that is a project of its own
- Collaborative/real-time editing

---

## 2. Package Layout

```
packages/rp-pptx/
├── pyproject.toml
├── src/rp_pptx/
│   ├── __init__.py         # public API re-exports
│   ├── errors.py           # RpPptxError, subclassing rp_core per parent §4.1
│   ├── models.py           # pptx-specific pydantic models only
│   ├── ooxml.py            # PresentationML/DrawingML namespaces, opened()/save(), retyping
│   ├── templates.py        # resolution, inspection, LayoutMap, manifest, synthesis
│   ├── pptx/
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── runs.py         # a:r run-offset mapping — §6, standalone
│   │   ├── slides.py       # delete/reorder — p:sldIdLst surgery, §7
│   │   └── template.py     # {{ placeholder }} substitution
│   ├── cli.py              # typer — formatting and printing only
│   └── mcp_server.py       # stub, or the rp-mcp server if Phase 2 has landed (§12 step 9)
└── tests/
    ├── conftest.py         # generates all fixture decks and templates
    ├── fixtures/           # *.manifest.json only — no binaries, per §11
    └── test_*.py
```

**Owned by `rp-core`, never redefined here:** `Capability`, `ErrorDetail`, `ErrorEnvelope`, the exception hierarchy, range parsing (`rp_core.ranges`), binary discovery, rasterization, and all CLI conventions.

### Shared OOXML mechanics — promote, don't duplicate

`rp_docx.ooxml` contains machinery that is not Word-specific: zip unpack/repack of an OOXML package, the compiled-`etree.XPath` helper (needed because both python-docx and python-pptx override `_Element.xpath` with a version binding their own incomplete namespace map), and content-type rewriting. Leaf packages cannot import each other (parent §10), so before this package reimplements any of it, **§12 step 2 promotes the format-agnostic parts into `rp_core.ooxml`** and refactors `rp-docx` onto it in the same PR — cross-cutting changes landing atomically is a stated reason the workspace exists (parent §1).

The promoted module must stay format-agnostic to survive parent §10's "no format-specific identifier in `rp_core`" invariant: content-type strings and namespace maps are *arguments*, and everything mentioning `w:`, `p:`, or `a:` stays in the leaf. If the extraction turns out messier than it looks — python-docx and python-pptx package APIs differ more than expected, say — the fallback is a small duplication inside `rp_pptx.ooxml` and a deferred extraction, recorded in the status note. The fallback exists so this decision cannot block the phase.

The same promotion covers `rp-docx`'s hand-rolled Markdown block/inline parser, which is equally format-agnostic — see §9 and §12 step 2.

### Core contract
- `rp_pptx.pptx.*` and `rp_pptx.templates` never print and never import typer
- Every public function returns a pydantic model or a list of them
- All paths in and out are `pathlib.Path`
- User-facing indices are 1-based — slides, tables, images, charts
- No in-place mutation unless an explicit `output` path or `--in-place` is given
- Package-specific settings use the `RP_PPTX_*` prefix (parent §2)

### Dependencies

`rp-core`, `python-pptx` (MIT), `lxml` (BSD-3 — python-pptx's own dependency, but declared directly because `ooxml.py` uses it for the parts python-pptx has no API for), `Pillow` (MIT-CMU), `typer` (MIT), `pydantic` (MIT).

Transitively, python-pptx brings `XlsxWriter` (BSD-2-Clause) — it uses it only when *authoring* charts, which this package never does, but the import graph carries it, so it needs a license-gate allowlist entry (parent §7). It also brings `typing-extensions` (PSF).

**Rejected:** `pptx2md` — its own license is permissive, but it depends on `tqdm` (`MPL-2.0 AND MIT`), which parent §7.1 bars from the base install path, plus scipy and numpy for a task that needs neither. `markitdown` (MIT) — a general-purpose converter whose pptx support is python-pptx underneath, wrapped in a heavy dependency tree. Both do with dependencies what §9 does with ~200 lines against a library we already ship. There is no mammoth-equivalent for pptx; Markdown conversion is hand-rolled in both directions, with the parser shared from `rp-core` after §12 step 2's promotion.

---

## 3. Data Models (`models.py`)

```python
class PresentationIndex(BaseModel):
    path: Path
    slide_count: int
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str            # "16:9", "4:3", or "w:h" reduced
    master_count: int
    layout_names: list[str]
    image_count: int
    table_count: int
    chart_count: int
    notes_count: int             # slides that have speaker notes
    comment_count: int
    titles: list[SlideTitle]
    core_properties: CoreProperties

class SlideTitle(BaseModel):
    index: int                   # 1-based slide index
    layout: str
    title: str | None            # None when the slide has no title placeholder

class SlideText(BaseModel):
    index: int
    layout: str
    title: str | None
    paragraphs: list[Paragraph]

class Paragraph(BaseModel):
    text: str
    level: int                   # 0-8 outline indent level
    runs: list[Run] | None       # populated only when requested

class Run(BaseModel):
    text: str
    bold: bool
    italic: bool
    underline: bool
    font: str | None
    size_pt: float | None
    color: str | None            # hex

class Table(BaseModel):
    index: int                   # 1-based across the deck, in slide order
    slide_index: int
    rows: int
    cols: int
    data: list[list[str]]        # merge-origin cell carries the value; spanned cells are ""
    merges: list[MergeSpan]

class MergeSpan(BaseModel):
    row: int                     # 1-based origin
    col: int
    row_span: int
    col_span: int

class EmbeddedImage(BaseModel):
    index: int
    slide_index: int
    rel_id: str
    filename: str
    content_type: str
    width_px: int | None         # None for WMF/EMF metafiles Pillow can't read — §9
    height_px: int | None
    alt_text: str | None
    extracted_path: Path | None

class SpeakerNotes(BaseModel):
    slide_index: int
    text: str

class Comment(BaseModel):
    id: str
    author: str
    initials: str | None
    date: datetime | None
    text: str
    slide_index: int
    parent_id: str | None        # threaded replies (modern comments); None for top-level

class ChartRef(BaseModel):
    index: int
    slide_index: int
    chart_type: str
    title: str | None
    categories: list[str]
    series: list[ChartSeries]
    data_available: bool         # False when python-pptx can't read this chart type — §9

class ChartSeries(BaseModel):
    name: str | None
    values: list[float | None]

class CoreProperties(BaseModel):
    # Same shape as rp_docx's — the OOXML core-properties part is format-independent.
    # Duplicated deliberately: it is a data shape, not logic, and leaves do not
    # import each other. If a third leaf needs it, promote it to rp-core then.
    title: str | None
    author: str | None
    last_modified_by: str | None
    created: datetime | None
    modified: datetime | None
    revision: int | None
    category: str | None
    keywords: str | None

class PlaceholderDef(BaseModel):
    idx: int                     # ph idx attribute, the layout-inheritance key
    type: str                    # "title", "body", "pic", "tbl", ...
    name: str                    # shape name

class LayoutDef(BaseModel):
    name: str
    index: int                   # 1-based within its master
    placeholders: list[PlaceholderDef]

class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["potx", "pptx"]
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str
    master_count: int
    layouts: list[LayoutDef]

class TemplateManifest(BaseModel):
    """Redacted-by-construction description of a template's shape.

    Structure only — layout names, placeholder inventory, slide geometry,
    presence flags. Never slide text, never image bytes. Safe to commit and
    to share outside the environment holding the original template.
    """
    name: str
    format: Literal["potx", "pptx"]
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str
    master_count: int
    layouts: list[LayoutDef]
    master_image_count: int      # logo presence, not logo bytes
    notes_master_present: bool
    layoutmap: LayoutMap | None  # if a .layoutmap.json sits beside the template

class LayoutMap(BaseModel):
    # Every default names a layout that genuinely exists in python-pptx's
    # bundled default template — the rp-docx StyleMap.code lesson: a default
    # may only name something that is really there.
    title: str = "Title Slide"          # deck title slide
    section: str = "Section Header"     # section-break slides
    content: str = "Title and Content"  # ordinary body slides
    blank: str = "Blank"                # image-only / free-form slides

class ReplaceResult(BaseModel):
    output: Path
    replacements: dict[str, int]  # placeholder -> count; unmatched keys report 0
    locations: list[str]          # "slide:3", "notes:3", "table:2"

class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]

class SlideOpResult(BaseModel):
    output: Path
    slide_count: int              # after the operation
```

---

## 4. Public API

### Read (`rp_pptx.pptx.read`)

```python
get_index(path: Path) -> PresentationIndex
get_text(path: Path, *, slides: str = "all", runs: bool = False) -> list[SlideText]
get_markdown(path: Path, *, slides: str = "all", notes: bool = True,
             images_dir: Path | None = None) -> str
get_tables(path: Path, *, slides: str = "all",
           table_index: int | None = None) -> list[Table]
get_images(path: Path, *, slides: str = "all",
           output_dir: Path | None = None) -> list[EmbeddedImage]
get_notes(path: Path, *, slides: str = "all") -> list[SpeakerNotes]
get_comments(path: Path, *, slides: str = "all") -> list[Comment]
get_charts(path: Path, *, slides: str = "all") -> list[ChartRef]
get_properties(path: Path) -> CoreProperties
```

`slides` accepts the `rp_core.ranges` spec — the module parent §4.3 says "serves PDF pages, docx sections, and future sheet or slide selection". This is that future. **Every read that returns per-slide content takes the selector**, not just the text-shaped ones: an agent asking "what tables are on slide 12" should not have to fetch every table in a 90-slide deck and filter client-side. Only `get_index` and `get_properties` are whole-deck by nature.

### Write (`rp_pptx.pptx.write`)

```python
create(output: Path, *, markdown: str | None = None,
       template: str | Path | None = None,
       aspect: Literal["16:9", "4:3"] = "16:9") -> Path

append_markdown(path: Path, markdown: str, *, output: Path | None = None) -> Path

replace_text(path: Path, replacements: dict[str, str], *,
             output: Path | None = None, match_case: bool = True,
             preserve_formatting: bool = True) -> ReplaceResult

set_notes(path: Path, slide: int, text: str, *,
          output: Path | None = None) -> Path

set_properties(path: Path, props: CoreProperties, *,
               output: Path | None = None) -> Path
```

**The aspect decision is made on the `template` argument, not on the resolved path.** `resolve_template` maps `None` to a real `Path` (§5.1), so by the time resolution has happened, an implicit bundled default is indistinguishable from an explicitly requested one — and the two must behave differently: `template=None` means `create()` forces `aspect` (16:9 by default) over whatever the fallback template says, while any explicitly supplied template — including python-pptx's own bundled one, passed by path — wins on geometry. `create()` therefore records `template is None` *before* resolving. §11.2 requires a test distinguishing exactly this pair.

`append_markdown` segments differently from `create` — see §9. In brief: on append, a first `#` opens a *section* slide, never a title slide; `##` opens a content slide; leading unheaded content opens a new untitled content slide; the existing final slide is never modified.

### Slides (`rp_pptx.pptx.slides`)

```python
delete_slides(path: Path, slides: str, *, output: Path | None = None) -> SlideOpResult
reorder_slides(path: Path, order: list[int], *, output: Path | None = None) -> SlideOpResult
```

`order` must be a complete permutation of `1..slide_count`; anything else is an `InputError` saying which indices are missing or duplicated. A partial spec silently guessing where unlisted slides go is exactly the kind of surprise parent §10 exists to prevent.

`delete_slides` refuses to delete every slide — a spec that would leave zero is an `InputError`. An empty deck is a corner nothing downstream is tested against (PowerPoint, LibreOffice, and python-pptx each get to have an opinion), and "delete all slides" is far likelier a range-spec mistake than an intent.

### Templates (`rp_pptx.templates`)

```python
list_templates() -> list[TemplateInfo]
resolve_template(name_or_path: str | Path | None) -> Path
inspect_template(path: Path) -> TemplateInfo
load_layoutmap(template: Path) -> LayoutMap
build_manifest(path: Path) -> TemplateManifest
synthesize(manifest: TemplateManifest, output: Path) -> Path
fill_template(template: str | Path, context: dict, output: Path, *,
              strict: bool = True) -> FillResult
```

### Render / convert

Thin re-exports of `rp_core.render.render_pages` and `rp_core.binaries.soffice_convert`, exactly as in `rp-docx`. `render_pages` already routes non-PDF input through LibreOffice; a slide is a page. No rendering implementation lives in this package.

---

## 5. Templates

House templates are the normal path, not the exception. `create()` and `fill_template()` default to a house template rather than python-pptx's built-in default.

### 5.1 Resolution

Identical to `rp-docx` §5.1 v1.3, with `.potx`/`.pptx` in place of `.dotx`/`.docx`:

1. Explicit `Path` that exists → use it
2. Bare name (e.g. `"pitch"`) → resolve against `RP_PPTX_TEMPLATE_DIR`, then `<repo>/templates/local/` and `<repo>/templates/`, trying `<name>.potx` then `<name>.pptx`
3. `None` → the configured default template name (`RP_PPTX_TEMPLATE`), or python-pptx's built-in if none configured
4. A path-shaped argument that does not exist → `InputError` naming the *path* — anything carrying a suffix or a separator is a wrong path, not a name to look up
5. Unresolvable name → `InputError` listing available templates

`resolve_template` returns a `Path` in every case, falling back to python-pptx's bundled default rather than to a `None` every caller would special-case. The cost of that convenience is that resolution *erases explicitness* — a resolved path no longer says whether the caller asked for it. Any behavior that depends on whether a template was explicitly supplied (today: `create()`'s aspect rule, §4) is decided on the pre-resolution argument, and this is contract, not implementation detail.

**Layout mapping.** House decks rarely use the default layout names. Markdown→pptx conversion maps roles through `LayoutMap`, loaded from an optional `<template>.layoutmap.json` beside the template — never hardcoded.

If a mapped layout is absent from the template, raise `InputError` naming the missing layout and listing what the template does have. **Never silently fall back.** And **"absent" means absent *when needed*** — the check happens per role at the point of use, not eagerly over the whole map, per the rp-docx §5.1 v1.3 rule. A deck with no section breaks does not need a section layout, and lazy checking is what makes the `hostile` fixture meaningful (§11).

### 5.2 Manifests and synthesis

The real house templates are confidential and cannot enter this repository. The manifest loop is inherited from `rp-docx` §5.2 unchanged:

1. `build_manifest()` runs against the real template, wherever it lives, and emits JSON
2. That JSON is committed to `tests/fixtures/` — text, diffable, nothing confidential
3. `synthesize()` reconstructs a structurally equivalent `.potx` at test time
4. CI exercises the real template's shape without the file ever leaving the machine that holds it

**Redaction is a correctness property, not a convention.** The manifest must never carry slide text, image bytes, author names, or paths beyond the template's basename. The same test as rp-docx's applies: a manifest built from a template containing distinctive text must not contain that text anywhere in its serialized form.

`synthesize()` reproduces: slide geometry, master count, each layout's name and placeholder inventory (idx, type, name), a placeholder image on the master when `master_image_count > 0`, and a notes master when flagged. It does not reproduce theme fonts, colors, or backgrounds — structural equivalence for testing layout resolution, not visual fidelity.

### 5.3 `.potx` handling — verified up front

`.potx` and `.pptx` differ chiefly in `[Content_Types].xml`: the template's main-part content type is `application/vnd.openxmlformats-officedocument.presentationml.template.main+xml`.

**Already verified, against python-pptx 1.0.2 — the rp-docx finding repeats exactly:**

- `Presentation("x.potx")` raises `ValueError: file 'x.potx' is not a PowerPoint file, content type is '…presentationml.template.main+xml'`. python-pptx does not open templates.
- `save()` always writes the *presentation* content type, so a file saved under a `.potx` name without retyping is a mislabeled presentation — PowerPoint opens it as an ordinary deck, silently editing what the user meant to keep as a template.

So retyping is load-bearing infrastructure, not a fixture convenience, and the `rp-docx` pattern is required from the start: every entry point accepting a deck goes through `ooxml.opened(path)`, which retypes a template into a temporary copy and opens that; `ooxml.save(presentation, output)` retypes on the way out when the output is named `.potx`. Asserted in a `TestContentTypes` test, exactly as in `rp-docx` — if a future python-pptx learns to open templates, the test fails and `opened()` can be simplified.

`resolve_template` must find `.potx` before `.pptx` when both exist — test this.

---

## 6. The Run-Spanning Problem, DrawingML Edition

DrawingML splits a logical string across `a:r` runs as arbitrarily as WordprocessingML splits `w:r` — formatting boundaries, language tagging, editing history. A naive per-run replace misses any placeholder straddling a boundary. The algorithm is `rp-docx` §6's, unchanged:

1. Per paragraph (`a:p`), build a concatenated string plus a run-offset map
2. Locate matches against the concatenated string
3. Write the replacement into the run containing the match start; blank the tails of spanned runs
4. Inherit formatting from the first spanned run (documented behavior)
5. Overlapping candidate matches resolve to the longer — the rp-docx Phase 1 decision, inherited, so results never depend on dict ordering

The code cannot be imported from `rp_docx` (parent §10: leaves never import each other), and the namespaces and paragraph structure differ (`a:r`/`a:t` under `a:p` vs `w:r`/`w:t` under `w:p`), so `rp_pptx.pptx.runs` is its own implementation of the shared algorithm. Promoting an element-agnostic offset-map core into `rp-core` is worth considering only if it can stay free of format identifiers; it is not required for this phase.

**Replacement scope:** every shape with a text frame on every selected slide, table cells, shapes inside groups **recursively**, and notes slides. Slide-body-only replacement is the pptx version of the body-only bug rp-docx §6 warns about. Layouts and masters are *excluded* — their text is design furniture, and editing it from a content operation is a surprise. Revisit only if a real deck demands it.

Build and unit-test `runs.py` before anything that depends on it. Required cases: a placeholder split across three runs; a match spanning a formatting boundary; a match inside a table cell; a match inside a grouped shape; overlapping candidate matches.

---

## 7. What Needs Raw XML

python-pptx has no API for any of the following; all of it goes through `ooxml.py` and lxml, with the namespace map living there and nowhere else.

**Slide deletion and reordering.** Deck order is the order of `p:sldId` elements in `p:sldIdLst` in `ppt/presentation.xml`. Reordering is reordering those elements. Deletion removes the `p:sldId`, the relationship it points to, and the slide part itself (plus its notes slide and rels). Media referenced only by a deleted slide is left in the package — orphaned media is invisible bloat, not corruption, and garbage collection of shared media is easy to get wrong; note it as a known limit.

**Comments.** Two generations exist:

- Classic: per-slide `ppt/comments/comment<N>.xml`, authors in `ppt/commentAuthors.xml`
- Modern (threaded): parts under `ppt/comments/` with their own schema, threaded replies, authors in `ppt/authors.xml`

Read-only in this phase, normalized into the one `Comment` model with `parent_id` carrying threading (`None` throughout for classic comments, which don't thread).

**Classic comments are in scope unconditionally. Modern comments are a checkpointed sub-scope that may be deferred without blocking the phase.** Their part layout must be verified against a real PowerPoint-authored file (§12 step 7) — Microsoft's format documentation for modern comments is thin, and the fixture generator (§11) must encode what PowerPoint actually writes, not what the schema implies. That reference file is the phase's only external input, and it may not be to hand when step 7 runs. If it isn't: `get_comments` ships reading classic comments fully, **detects** modern comment parts by content type and reports their presence loudly — a documented warning naming the slides that carry them, never a silent `[]` over a commented deck — and the deferral is recorded in the status note with the fixture generator as the follow-up. Silent emptiness is the one outcome this section forbids.

---

## 8. Templating Without Dependencies

Identical rules to `rp-docx` §8:

- Syntax: `{{ key }}` and `{{ key.subkey }}` only. **No expression evaluation, no Jinja.**
- Loops and conditionals are out of scope — generate from Markdown instead
- Reuses `runs.py`; the same run-splitting problem applies to placeholders
- `strict=True` raises `InputError` on unresolved placeholders; `strict=False` leaves them and reports them in `FillResult.unresolved`
- A key that matched nothing is reported with a count of zero (rp-docx Phase 1 decision, inherited)

`fill_template`'s replacement scope is §6's — slides, tables, groups, notes — which for a template deck covers the title slide and any boilerplate slides carrying placeholders.

---

## 9. Markdown Mapping and Other Footguns

**Markdown parsing is promoted, not reimplemented.** `rp-docx` hand-rolled a block/inline parser (its §9) covering headings, paragraphs, emphasis and code spans, nested lists, GFM pipe tables, fenced code, horizontal rules, and hyperlinks — almost exactly the subset this package needs. Parsing Markdown into a small block/inline AST is format-agnostic in the same way zip handling is: no OOXML identifier anywhere near it. So **§12 step 2's promotion covers the Markdown parser too**: the parser moves to `rp_core.markdown`, `rp-docx` keeps its docx *renderer* over the shared AST, and this package writes only a pptx renderer. Two additions the shared parser needs for pptx (both additive, neither docx-breaking): HTML comment blocks surfaced as AST nodes rather than skipped (speaker notes, below), and thematic breaks already parse. The same fallback clause applies — if the extraction fights back, duplicate the parser subset here, record why, defer.

**Markdown → slides needs a segmentation rule, and it must be deterministic.** A document is a scroll; a deck is a sequence. The mapping, for `create()`:

- First `#` heading → title slide (`LayoutMap.title`), heading as title, any immediately following paragraph as subtitle
- Each subsequent `#` → section-break slide (`LayoutMap.section`)
- Each `##` → new content slide (`LayoutMap.content`), heading as slide title
- `---` (thematic break) → explicit slide break, continuing the current layout, no title
- Body content → the slide's body placeholder: paragraphs and list items become bullets, with list nesting mapped to outline levels 0–8; bold/italic/code spans carried onto runs
- `###` and deeper → bold lead-in bullet at the current level, not a new slide — decks don't have sub-sub-sections, outlines do
- GFM pipe tables → native tables; images → pictures on the slide (`LayoutMap.blank` when an image is a slide's only content); fenced code → a monospace-font text box, since PowerPoint has no code style concept
- An HTML comment block within a slide's content (`<!-- speaker notes here -->`) → that slide's speaker notes — the Marp convention, chosen because it is precedented and invisible to any other Markdown renderer

**`append_markdown()` uses the same rules with one substitution and two guarantees**, because "first heading becomes the deck title" only makes sense when there is no deck yet:

- A first `#` on append opens a *section* slide (`LayoutMap.section`), never a title slide — the deck already has its title
- Leading unheaded content opens a new untitled content slide; it is never merged into the deck's existing final slide
- Append only adds slides — no existing slide's content, notes, or order changes

**No reflow, no auto-splitting.** Slides don't scroll: content that outgrows the placeholder overflows the slide boundary silently. This package places what it is given and does not second-guess quantity — a caller who cares can count bullets per slide with `get_text` on the result, and `docs/usage-pptx.md` states the limit plainly. Auto-splitting a long section across slides is editorial judgment, and out of scope.

**Slide size: python-pptx's default template is 4:3.** The world is 16:9. `create()` sets 16:9 explicitly unless a template is supplied, in which case the template wins — the exact shape of rp-docx's Letter/A4 rule (§9 there), same reasoning: never inherit a default silently.

**Placeholder prompt text is not content.** An empty placeholder displays "Click to add title", which lives in the layout, not the slide. python-pptx returns `""` for the slide-side text frame; make sure reads and word counts go through the slide's own XML so prompt text never leaks into `get_text` or `get_markdown` output.

**WMF/EMF images.** Legacy decks embed metafiles Pillow cannot parse. `width_px`/`height_px` are `None`, extraction still writes the bytes, and nothing raises.

**Charts read through python-pptx's chart API, defensively.** Common types (bar, line, pie, area, scatter) expose categories and series values. Anything the library can't model reports `chart_type` and `title` with `data_available: false` rather than raising — a deck with one exotic chart must not sink `get_charts`.

**Autofit font scaling.** A text frame with `normAutofit` carries a `fontScale` that PowerPoint applies at render time; a run's nominal `size_pt` is not the displayed size. Report the nominal size (it is what the file says) and don't attempt effective-size math.

---

## 10. CLI Design

```
rp-pptx doctor                                # via rp_core.clikit.doctor_command

rp-pptx index      FILE [--plain]
rp-pptx text       FILE [--slides SPEC] [--runs] [--plain]
rp-pptx markdown   FILE [-o OUT] [--slides SPEC] [--images-dir DIR] [--no-notes]
rp-pptx tables     FILE [--slides SPEC] [--index N] [--format json|csv|md] [-o DIR]
rp-pptx images     FILE [--slides SPEC] [-o DIR] [--plain]
rp-pptx notes      FILE [--slides SPEC] [--plain]
rp-pptx comments   FILE [--slides SPEC] [--author NAME] [--plain]
rp-pptx charts     FILE [--slides SPEC] [--plain]
rp-pptx props      FILE [--plain]

rp-pptx create     -o OUT [--from-markdown FILE] [--template NAME|PATH]
                          [--aspect 16:9|4:3]
rp-pptx append     FILE --markdown FILE (-o OUT | --in-place)
rp-pptx replace    FILE --map JSON (-o OUT | --in-place)
                          [--no-preserve-formatting] [--ignore-case]
rp-pptx template   TEMPLATE --context JSON -o OUT [--no-strict]
rp-pptx set-notes  FILE --slide N (--text TEXT | --from FILE) (-o OUT | --in-place)

rp-pptx slides delete   FILE --slides SPEC (-o OUT | --in-place)
rp-pptx slides reorder  FILE --order LIST (-o OUT | --in-place)

rp-pptx templates list                [--plain]
rp-pptx templates inspect NAME        [--plain]
rp-pptx templates manifest FILE       [-o OUT.manifest.json]
rp-pptx templates synthesize MANIFEST -o OUT.potx
rp-pptx templates layoutmap FILE      [-o OUT.layoutmap.json]   # scaffold, best-effort

rp-pptx convert    FILE --to pdf|odp|html [-o OUT]
rp-pptx render     FILE -o DIR [--dpi 150] [--slides 1-5]
```

`templates layoutmap` emits a best-effort `LayoutMap` scaffold by matching layout names against common patterns, for a human to correct — a convenience, never authoritative, and its output says so.

**Rules** — all inherited from `rp-docx` §10 v1.3, restated because they are contract:

- **JSON is the default output** for every read command, via `model_dump_json()`. `--plain` produces human-readable output. There is no `--json` flag — parent §4.6.
- Errors, exit codes, and the `ErrorEnvelope` payload come from `rp_core.clikit`. Do not construct error output locally.
- `--slides` accepts the range syntax parsed by `rp_core.ranges`.
- **Never overwrite an input file without `--in-place`.** Every editing command takes it and refuses when given neither it nor `-o` — no guessed filenames, no silent overwrites.
- `--map` and `--context` accept either a path to a JSON file or the JSON itself.
- `--author` is repeatable on `comments`.
- `--order` takes a comma-separated permutation (`3,1,2`); incomplete or duplicated indices are an `InputError` naming them.
- Every new subcommand must be registered wherever the CLI's dispatcher requires it, and the parent §10 invariant test must cover this CLI too.

---

## 11. Testing

### 11.1 No binary fixtures in git

Inherited outright from `rp-docx` §11 and its Phase 1 outcome, which went further than the spec asked: **nothing binary is committed at all.** Template fixtures are generated in `conftest.py`; comment fixtures — which python-pptx cannot produce — are generated too, by appending the comment parts, relationships, and content-type overrides to a generated deck, the same technique rp-docx's conftest uses for tracked changes. A generated fixture cannot drift, so a failure is always the code. `tests/fixtures/` holds only the `*.manifest.json` files real templates will eventually produce.

The modern-comments generator must be written from a real PowerPoint-authored file inspected at the §12 step 7 checkpoint (§7), then encoded in conftest — the one place reality has to be consulted before the fixture can be trusted.

`templates/local/` remains the gitignored drop point for real decks during manual testing. Nothing there is ever required by CI.

### 11.2 Three synthetic templates, built in `conftest.py`

Adversarial, not realistic — same doctrine, same trio:

| Fixture | Purpose |
|---|---|
| `minimal` | python-pptx's bundled default: stock layout names, 4:3. The happy path, the default-`LayoutMap` path, and both sides of the aspect contract: implicit use (template `None` resolving to it) gets 16:9 forced; explicit use (passed by path) keeps its 4:3. |
| `house_like` | Renamed layouts (`"RP Title"`, `"House Content"`), a layout name containing a space and a non-ASCII character (`"Résumé Layout"`), 16:9, an image on the master (the logo stand-in), a second master, and a `.layoutmap.json` beside it. |
| `hostile` | Missing a layout the `LayoutMap` maps to; no `.layoutmap.json`; two layouts whose names differ only by case. Exists to prove failures are loud. |

Required assertions:
- `house_like` round-trips: create → read → house layouts used, master image intact
- `hostile` raises `InputError` naming the missing layout and listing what the template has — and only when the missing role is actually used (lazy checking, §5.1)
- 16:9 from `house_like` wins over `create()`'s `aspect` argument (explicit template wins on geometry)
- The implicit/explicit pair (§4): `create(template=None)` forces 16:9 over the bundled default's 4:3; `create(template=<path to that same bundled template>)` keeps 4:3 — same resolved file, different behavior, decided on the argument
- `resolve_template` prefers `.potx` over `.pptx` when both exist
- A wrong path reports the path, not "no template called …" (§5.1 case 4)
- A manifest built from a template containing distinctive text does not contain that text (§5.2)
- `synthesize(build_manifest(t))` produces a template whose layout names and placeholder inventory equal the original's

### 11.3 Everything else

- Deck fixtures (titled slides, bulleted outlines with nesting, tables with merged cells, images, grouped shapes, notes) are generated programmatically in `conftest.py`
- Round-trip tests: create → read → assert; replace → read → assert; delete → count and order assert; reorder → order assert, then render order via `get_text`
- `delete_slides` covering the whole deck raises `InputError`; deleting all but one succeeds
- Append semantics (§9): first `#` on append becomes a section slide, leading unheaded content becomes a new untitled slide, and every pre-existing slide's content, notes, and order are unchanged
- Per-slide selectors: `--slides` filtering asserted on at least `tables` and `comments`, not just the text-shaped reads
- Explicit test that replacement works in a table cell, a grouped shape, and a notes slide — and does **not** touch layouts or masters (§6)
- Explicit test for a placeholder split across runs
- Explicit test that read commands emit JSON with no flag, and human output with `--plain`
- Slide-op integrity: after `delete` and `reorder`, the deck reopens cleanly in python-pptx and `p:sldIdLst` matches the surviving parts
- LibreOffice-dependent tests use the functional probe pattern from rp-docx (`requires_soffice` probes that conversion *works*, not that the binary exists), and skip cleanly
- Test module names must not collide with other packages' — `--import-mode=importlib` makes this non-fatal, distinct names remain the convention
- Target > 85% coverage on `pptx/`, `ooxml.py`, and `templates.py`

---

## 12. Phase 2.5 — Execution Plan

Prerequisite: none — Phase 1 is merged, and this phase does not depend on Phase 2 (`rp-mcp`) in either direction. **No house template or real deck is required at any point.** The one external input — a PowerPoint-authored deck with modern threaded comments, read-only reference material for the step 7 checkpoint — gates only the deferrable modern-comments sub-scope (§7), never the phase.

**Step 1.** Scaffold `packages/rp-pptx/` as a workspace member depending on `rp-core`. Entry point `rp-pptx`, plus the `robo_papyro.commands` entry point registering `pptx`. Verify `rp pptx --help` resolves through the umbrella before writing further code.

**Step 2.** Promote the format-agnostic mechanics out of `rp-docx` into `rp-core` (§2, §9). Two extractions, same shape: `rp_core.ooxml` gets package zip handling, the compiled-xpath helper, and content-type read/rewrite — namespace maps and content-type strings as arguments, no format identifier in core; `rp_core.markdown` gets the block/inline parser, emitting the shared AST, with HTML comment blocks surfaced as nodes (`rp-docx` keeps its docx renderer over that AST). Refactor `rp-docx` onto both in the same PR; its tests move with the code and must pass unchanged. Either extraction may independently take the documented fallback (duplicate in the leaf, defer, record why) if it fights back.

**Step 3.** Implement `models.py` per §3 — pptx-specific models only; `rp_core`'s are imported.

**Step 4.** Implement `rp_pptx.ooxml`: PresentationML/DrawingML namespaces, `opened()`/`save()` with `.potx` retyping per §5.3, xpath helpers over the promoted core. The `TestContentTypes` assertion lands here.

**Step 5.** Implement `templates.py` per §5 and the three synthetic fixtures from §11.2 in `conftest.py`. Then **report**: `inspect_template` output for `house_like`, the manifest built from it, and the synthesized round-trip. The checkpoint exists to surface surprises, not to block — rp-docx's equivalent caught two silently-unpopulated manifest fields.

**Step 6.** Implement `pptx/runs.py` per §6 as a standalone, unit-tested module, before anything depends on it. All five required cases.

**Step 7.** Implement `pptx/read.py` in order: `get_properties`, `get_index`, `get_text`, `get_tables`, `get_images`, `get_notes`, `get_comments`, `get_charts`. Tests alongside each. **Checkpoint:** inspect a real PowerPoint-authored file with modern threaded comments, report the actual part layout found (§7), and encode it in the conftest generator (§11.1). If no reference file is available when this step runs, take §7's deferral path — classic comments complete, modern parts detected and reported loudly — and continue; the deferral and its follow-up go in the status note, not in the way of step 8.

**Step 8.** Implement `pptx/slides.py` (§7), then `pptx/write.py` and `pptx/template.py` on top of `runs.py` and the resolved `LayoutMap`.

**Step 9.** Implement `cli.py` per §10 using `rp_core.clikit`. If `rp-mcp` exists by now, add the pptx server there (parent §9 puts MCP servers in their own distribution — never in this leaf); otherwise leave `mcp_server.py` a documented stub for Phase 2 to claim.

**Step 10.** Full suite; CLI sweep against a generated deck; verify `rp pptx index FILE` and `rp-pptx index FILE` byte-identical; `docs/usage-pptx.md`; CI matrix and smoke steps extended (the umbrella-identity, exit-code-taxonomy, and no-LibreOffice-round-trip smokes that cover rp-docx get pptx equivalents); license-gate entry for `XlsxWriter`.

**Definition of done:** suite green with nothing binary committed; coverage target met; both `rp-pptx` and `rp pptx` functional; JSON by default with `--plain` working; errors matching `ErrorEnvelope`; the base install path free of weak copyleft with `XlsxWriter` allowlisted as BSD-2; and a written status note listing every place §5–§9 turned out to be wrong in practice, in the pattern of `dev-notes/status-robo-papyro-phase-1.md`.

---

## 13. After Phase 2.5 — Validating Against a Real House Deck

Ships without ever seeing a corporate template; validation is a separate manual pass, mirroring `rp-docx` §13:

1. Drop the real `.potx` into `templates/local/`
2. `rp-pptx templates inspect` → confirm layouts and placeholders are read correctly
3. `rp-pptx templates layoutmap` → scaffold, then hand-correct into the real `.layoutmap.json`
4. `rp-pptx create --from-markdown ... --template <real>` → open in PowerPoint, confirm house layouts applied
5. `rp-pptx templates manifest` → commit the manifest to `tests/fixtures/` so CI regression-tests the real template's shape from then on

Only step 5 produces a repository artifact, and it carries no confidential content by construction (§5.2). Everything discovered in steps 2–4 comes back as a defect report or a spec correction, not as a file.
