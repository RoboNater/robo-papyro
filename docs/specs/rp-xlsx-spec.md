# rp-xlsx — Spreadsheet Toolkit Specification

**Version:** 1.0
**Status:** **Specified. Phase 3 not started.** §12 is the execution plan.
**Parent document:** `robo-papyro-spec.md` v1.6 — read that first. Its §7 (licensing) and §10 (constraints) govern this package.
**Companion:** [`dev-notes/phase-3-openpyxl-probe.md`](../../dev-notes/phase-3-openpyxl-probe.md) — every claim this spec makes about openpyxl's behaviour was run against openpyxl 3.1.5 before being written down, and the output is in that note. Where this document says "verified", that is what it means.

This spec is written after three leaves shipped, and it inherits their findings
as requirements rather than rediscovering them: template retyping is
load-bearing and belongs in `save()` (§5.3), role→name and availability checks
happen lazily at the point of use (§5.1), template resolution distinguishes a
wrong path from an unknown name (§5.1), every editing command takes `--in-place`
and refuses to guess (§10), a part's filename is never its position (§7),
nothing binary is committed (§11), and a feature that cannot be supported
correctly fails loudly rather than returning a plausible empty result (§6).

**The one thing that makes this package different from its three siblings:**
`rp-pdf` reads, and `rp-docx`/`rp-pptx` edit formats whose libraries round-trip
faithfully. openpyxl does not. A load→save silently discards cached formula
values and every package part openpyxl does not model. §6 is therefore the
centre of this spec, the way §6 (run-spanning) was the centre of the `rp-docx`
and `rp-pptx` specs — and it is the section to read first.

---

## 1. Purpose

A Python package + CLI for reading, creating, and editing Excel workbooks, so
that agentic coding tools with no native spreadsheet capability can operate on
`.xlsx` files through a stable, scriptable interface.

Architecture mirrors `rp-docx` and `rp-pptx`: pure-function core returning
pydantic models, thin CLI wrapper, thin MCP wrapper. The `rp-mcp` server for
this package should be ~3 lines per tool.

**Distribution:** `rp-xlsx` · **Import:** `rp_xlsx` · **CLI:** `rp-xlsx`, also reachable as `rp xlsx`

**Formats:** `.xlsx`, `.xlsm`, `.xltx`, `.xltm` — openpyxl's `SUPPORTED_FORMATS`,
verified. `.csv`/`.tsv` are an input and output *interchange* format, not a
document format: they are read into and written out of workbooks, never
"opened".

### Non-goals

- **Formula evaluation.** We read formulas and whatever value the last real
  spreadsheet application cached; we never compute one. Evaluating Excel's
  function set is a project, the credible libraries are copyleft or heavy
  (`formulas` is EUPL-1.2, barred by parent §7), and a subtly wrong number is
  the worst output this suite could produce. §6 says what we do instead.
- **Legacy `.xls` and binary `.xlsb`.** openpyxl refuses both on the extension
  alone (verified). The error names the LibreOffice command that converts them;
  routing through `soffice` implicitly would make an external binary mandatory
  on a read path, which parent §10 forbids.
- **Rendering fidelity guarantees** — LibreOffice converts; we don't chase
  pixel parity.
- **Pivot tables, slicers, form controls, and threaded comments** — read *or*
  write. openpyxl does not model them; §6 makes their presence a loud failure on
  the write path rather than a silent deletion.
- **Chart creation.** Charts are read (§4). Authoring them means deciding on
  axes, scaling, and series binding on the caller's behalf; out of scope until a
  real workbook needs it. (Note that openpyxl *can* author charts, so this is a
  scope decision, not a capability limit.)
- **Style and theme authoring beyond what `create` needs** — bold headers,
  number formats, column widths, and freeze panes are in; a styling DSL is not.
- Collaborative/real-time editing.

---

## 2. Package Layout

```
packages/rp-xlsx/
├── pyproject.toml
├── README.md
├── src/rp_xlsx/
│   ├── __init__.py         # public API re-exports
│   ├── errors.py           # RpXlsxError and subclasses, parented onto rp_core per parent §4.1
│   ├── models.py           # xlsx-specific pydantic models only
│   ├── refs.py             # A1 notation, sheet selection — §9, standalone, no openpyxl needed
│   ├── ooxml.py            # SpreadsheetML content types, opened()/save(), template retyping
│   ├── fidelity.py         # §6 — at-risk part scanning and the lossy-edit guard
│   ├── templates.py        # resolution, inspection, manifest, synthesis
│   ├── xlsx/
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── sheets.py       # add/delete/rename/reorder
│   │   ├── tabular.py      # CSV/TSV/JSON/Markdown-table interchange, both directions
│   │   └── template.py     # {{ placeholder }} substitution
│   └── cli.py              # typer — formatting and printing only
└── tests/
    ├── conftest.py         # generates every fixture workbook and template
    ├── fixtures/           # *.manifest.json only — no binaries, per §11
    └── test_*.py
```

**Owned by `rp-core`, never redefined here:** `Capability`, `ErrorDetail`,
`ErrorEnvelope`, the exception hierarchy, integer range parsing
(`rp_core.ranges`), binary discovery, rasterization, progress reporting, the
OPC/OOXML zip and content-type mechanics (`rp_core.ooxml`), the Markdown
block/inline parser (`rp_core.markdown`), and all CLI conventions
(`rp_core.clikit`).

`rp_core.ooxml` already provides everything this package needs at the package
level — `part_names`, `read_part`, `parse_part`, `repack`, `resolve_target`,
`override_content_types`, `content_type_from`, `retype`, `compiled_xpath`. §6's
part scanning and §5.3's retyping are both thin wrappers over it. **No new
promotion into `rp-core` is required for the OOXML mechanics.** One promotion
*is* required, and it is not OOXML — see §3.

### Core contract

- `rp_xlsx.xlsx.*`, `rp_xlsx.templates`, `rp_xlsx.refs`, and `rp_xlsx.fidelity`
  never print and never import typer
- Every public function returns a pydantic model or a list of them
- All paths in and out are `pathlib.Path`
- User-facing indices are 1-based — sheets, rows, columns, tables, images
- No in-place mutation unless an explicit `output` path or `--in-place` is given
- Package-specific settings use the `RP_XLSX_*` prefix (parent §2)
- Long operations take `progress: Progress | None` and call it; only the CLI
  decides that means stderr (`AGENTS.md` rule 3). A 200k-row read is exactly the
  case `rp_core.progress` exists for.

### Dependencies

`rp-core`, `openpyxl` (MIT), `pydantic` (MIT), `typer` (MIT), `Pillow` (MIT-CMU
— openpyxl requires it to handle embedded images at all, verified: `add_image`
raises without it), and `lxml` (BSD-3) because `ooxml.py` and `fidelity.py`
work at the part level through `rp_core.ooxml`, which is built on lxml.

Transitively, openpyxl brings **`et-xmlfile` (MIT)** and nothing else. It is not
currently in `uv.lock` and needs an allowlist entry alongside `openpyxl`
(already pre-approved in `ci/allowed-packages.toml`; `et-xmlfile` is not).

**Rejected:** `pandas` — BSD-3 and technically permissible, but it pulls
`numpy` (and `pytz`/`tzdata`) into the base install path for tabular shaping
this package does in a few hundred lines over data it has already parsed, and
`rp-pdf` users would inherit all of it. `xlrd` — `.xls` only, and `.xls` is a
non-goal. `pylightxl`/`xlsx2csv` — narrower than openpyxl at the same
dependency cost. `formulas`/`pycel` — formula evaluation is a non-goal, and
`formulas` is EUPL-1.2 (barred outright by parent §7).

---

## 3. Data Models (`models.py`)

**One promotion first.** `CoreProperties` is now defined identically in
`rp_docx.models` and `rp_pptx.models`, and `rp-pptx-spec.md` §3 states the rule
for what happens next: *"Duplicated deliberately… If a third leaf needs it,
promote it to rp-core then."* This is that third leaf. §12 step 2 moves
`CoreProperties` to `rp_core.models` and refactors both existing leaves onto it,
their tests passing unchanged. The OPC core-properties part is format-
independent and carries no format identifier, so it survives parent §10's
invariant. It is a data shape, not logic; nothing else moves with it.

```python
class WorkbookIndex(BaseModel):
    path: Path
    format: Literal["xlsx", "xlsm", "xltx", "xltm"]
    sheet_count: int
    sheets: list[SheetInfo]
    defined_name_count: int
    has_macros: bool                # an xl/vbaProject.bin part is present
    has_cached_values: bool         # at least one formula carries a cached <v> — §6
    at_risk: list[str]              # part categories an edit would drop — §6
    core_properties: CoreProperties # imported from rp_core.models after §12 step 2

class SheetInfo(BaseModel):
    index: int                      # 1-based position in the workbook
    name: str
    state: Literal["visible", "hidden", "veryHidden"]
    used_range: str | None          # "A1:D20"; None for a genuinely empty sheet — §9
    declared_range: str             # what the file claims (ws.dimensions) — §9
    rows: int                       # rows in used_range, not in declared_range
    columns: int
    formula_count: int
    merged_count: int
    table_count: int
    chart_count: int
    image_count: int
    comment_count: int
    freeze_panes: str | None
    autofilter: str | None

class Cell(BaseModel):
    sheet: str
    ref: str                        # "B5"
    row: int                        # 1-based
    column: int                     # 1-based
    value: CellValue                # str | float | int | bool | datetime | None
    formula: str | None             # "=SUM(B2:B4)"; None when the cell is not a formula
    value_available: bool           # False for a formula with no cached value — §6
    number_format: str              # "General", "0.00%", "yyyy-mm-dd"
    is_date: bool
    is_merged_origin: bool

class SheetData(BaseModel):
    sheet: str
    index: int
    range: str                      # the range actually returned
    header: list[str] | None        # first row, when header=True
    rows: list[list[CellValue]]     # values only — see §9 on display strings
    truncated: bool                 # max_rows cut the result short

class ExcelTable(BaseModel):
    """An Excel table object (ListObject) — not a Markdown or docx table."""
    name: str
    sheet: str
    ref: str
    header_row: bool
    totals_row: bool
    style: str | None
    columns: list[str]

class NamedRange(BaseModel):
    name: str
    scope: str | None               # sheet name for a sheet-scoped name; None if workbook-scoped
    refers_to: str

class CellComment(BaseModel):
    sheet: str
    ref: str
    author: str | None
    text: str

class EmbeddedImage(BaseModel):
    index: int
    sheet: str
    anchor: str | None              # "C3"; None when the anchor is not a simple cell anchor
    filename: str
    content_type: str
    width_px: int | None            # None for formats Pillow cannot read
    height_px: int | None
    extracted_path: Path | None

class ChartRef(BaseModel):
    index: int
    sheet: str
    chart_type: str
    title: str | None
    anchor: str | None
    series: list[ChartSeries]
    data_available: bool            # False when openpyxl cannot model this chart

class ChartSeries(BaseModel):
    name: str | None
    values_ref: str | None          # the reference, not the values — we do not evaluate
    categories_ref: str | None

class FidelityReport(BaseModel):
    """What editing this workbook with openpyxl would cost. — §6"""
    path: Path
    safe_to_edit: bool
    at_risk: list[AtRiskPart]
    cached_values_present: bool     # True means an edit discards them
    macros_present: bool

class AtRiskPart(BaseModel):
    category: str                   # "threaded_comments", "pivot_cache", "slicer", ...
    part: str                       # the part name in the package
    detail: str                     # what a save would do to it

class WriteResult(BaseModel):
    output: Path
    cells_written: int
    recalculation_required: bool    # the source had formulas whose cached values are now gone
    dropped: list[AtRiskPart]       # non-empty only when allow_lossy let a write through

class ReplaceResult(BaseModel):
    output: Path
    replacements: dict[str, int]    # key -> count; unmatched keys report 0
    locations: list[str]            # "Sheet1!B4", "header:Sheet1"
    recalculation_required: bool
    dropped: list[AtRiskPart]       # non-empty only when allow_lossy let a write through

class SheetOpResult(BaseModel):
    output: Path
    sheet_count: int                # after the operation
    sheets: list[str]               # names, in order, after the operation
    recalculation_required: bool
    dropped: list[AtRiskPart]

class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]
    recalculation_required: bool
    dropped: list[AtRiskPart]

class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["xltx", "xltm", "xlsx", "xlsm"]
    sheets: list[SheetInfo]
    defined_names: list[NamedRange]
    placeholders: list[str]         # the {{ keys }} the template contains — §5.2

class TemplateManifest(BaseModel):
    """Redacted-by-construction description of a template's shape. — §5.2"""
    name: str
    format: Literal["xltx", "xltm", "xlsx", "xlsm"]
    sheets: list[SheetShape]
    defined_names: list[NamedRange]
    placeholders: list[str]
    image_count: int                # logo presence, not logo bytes

class SheetShape(BaseModel):
    index: int
    name: str
    state: Literal["visible", "hidden", "veryHidden"]
    used_range: str | None
    header: list[str] | None        # the header row, which is structure — §5.2 explains
    column_widths: dict[str, float]
    freeze_panes: str | None
    number_formats: dict[str, str]  # column letter -> format, where the column is uniform
    table_names: list[str]
    placeholder_cells: dict[str, str]   # "B2" -> "{{ client.name }}"
```

`CellValue` is `str | float | int | bool | datetime | None`. Pydantic's union
coercion will happily turn `True` into `1` in the wrong union order — declare it
`bool` first and test a boolean cell explicitly. This has bitten every codebase
that has ever serialized a spreadsheet.

---

## 4. Public API

### Read (`rp_xlsx.xlsx.read`)

```python
get_index(path: Path) -> WorkbookIndex
get_data(path: Path, *, sheets: str = "all", names: list[str] | None = None,
         cells: str | None = None, header: bool = True,
         max_rows: int | None = None, values: Literal["cached", "formulas"] = "cached",
         progress: Progress | None = None) -> list[SheetData]
get_cells(path: Path, *, sheets: str = "all", names: list[str] | None = None,
          cells: str | None = None, empty: bool = False) -> list[Cell]
get_formulas(path: Path, *, sheets: str = "all") -> list[Cell]
get_tables(path: Path, *, sheets: str = "all") -> list[ExcelTable]
get_names(path: Path) -> list[NamedRange]
get_comments(path: Path, *, sheets: str = "all") -> list[CellComment]
get_images(path: Path, *, sheets: str = "all",
           output_dir: Path | None = None) -> list[EmbeddedImage]
get_charts(path: Path, *, sheets: str = "all") -> list[ChartRef]
get_properties(path: Path) -> CoreProperties
get_markdown(path: Path, *, sheets: str = "all", names: list[str] | None = None,
             cells: str | None = None, max_rows: int | None = 200) -> str
```

**Sheet selection is two arguments, not one, and that is deliberate.** `sheets`
is an `rp_core.ranges` spec over 1-based sheet position (`"2"`, `"1-3"`,
`"2,4"`, `"all"`); `names` selects by sheet name. A single argument accepting
both cannot be disambiguated — `"2024"` is a perfectly ordinary sheet name and
also a position spec, and a tool that guesses will one day read the wrong sheet
and say nothing. §11 requires a test with a sheet literally named `"2"`.
Supplying both is an `InputError`; supplying neither means every sheet.

`cells` is A1-notation (`"A1:D20"`, `"B:B"`, `"3:3"`) parsed by `refs.py`, not
by `rp_core.ranges` — A1 notation is a spreadsheet concept and stays in the leaf,
exactly as PDF page labels stay in `rp-pdf` (parent §4.3).

`get_data` returns **values**, not display strings — `0.25` for a cell showing
`25.00%`. `number_format` is reported by `get_cells` so a caller can format it;
reimplementing Excel's format engine is not in scope, and half-implementing it
is worse (§9).

`empty=False` on `get_cells` skips cells with no value and no formula, so a
sparse sheet does not serialize a million nulls.

### Write (`rp_xlsx.xlsx.write`)

Every function that opens an existing workbook goes through §6's guard.

```python
create(output: Path, *, sheets: list[SheetSpec] | None = None,
       template: str | Path | None = None,
       header_style: bool = True, allow_lossy: bool = False) -> WriteResult

set_cells(path: Path, updates: dict[str, dict[str, CellValue]], *,
          output: Path | None = None, allow_lossy: bool = False) -> WriteResult
    # {"Sheet1": {"B2": 5, "C3": "=B2*2"}} — sheet name -> ref -> value

append_rows(path: Path, sheet: str, rows: list[list[CellValue]], *,
            output: Path | None = None, allow_lossy: bool = False) -> WriteResult

replace_text(path: Path, replacements: dict[str, str], *,
             output: Path | None = None, sheets: str = "all",
             match_case: bool = True, include_formulas: bool = False,
             allow_lossy: bool = False) -> ReplaceResult

set_properties(path: Path, props: CoreProperties, *,
               output: Path | None = None, allow_lossy: bool = False) -> WriteResult
```

**Correction, post-implementation (PR review).** `create`'s `template=` branch opens and
re-saves an existing workbook — the template — so it goes through §6's guard exactly like
every other function here, with `allow_lossy` to override it; a template-less `create` opens
nothing existing, so the guard never fires on that path and `WriteResult.dropped` is always
empty there. `create` and `set_properties` return `WriteResult` rather than the bare `Path`
originally specified, so a caller (the CLI, the MCP tool) reports what the guard actually
found instead of fabricating `recalculation_required`/`dropped`. `fill_template` (below)
gained the same `allow_lossy` parameter and `FillResult` gained `recalculation_required`/
`dropped`, for the same reason: it opens and re-saves the template it fills.

`SheetSpec` is a small model — `name`, `rows`, optional `header`, optional
`column_widths`, optional `freeze_header: bool` — so `create` has one input
shape whether the rows came from CSV, JSON, or a Markdown table (§9).

**`replace_text` does not touch formulas by default.** A replacement landing
inside `=SUM(Revenue!A1:A9)` produces a formula that is either broken or, worse,
silently pointing somewhere else. `include_formulas=True` opts in, and the
result's `locations` mark those hits so a reviewer can see them.

**A value beginning with `=` is written as a formula, always.** There is no
"literal text that looks like a formula" escape in this API; a caller who needs
one prefixes with `'` exactly as they would in Excel. Document it, test it.

### Sheets (`rp_xlsx.xlsx.sheets`)

```python
add_sheet(path, name, *, index=None, output=None, allow_lossy=False) -> SheetOpResult
delete_sheets(path, sheets="", names=None, *, output=None, allow_lossy=False) -> SheetOpResult
rename_sheet(path, old, new, *, output=None, allow_lossy=False) -> SheetOpResult
reorder_sheets(path, order: list[int], *, output=None, allow_lossy=False) -> SheetOpResult
```

`order` must be a complete permutation of `1..sheet_count`; anything else is an
`InputError` naming the missing or duplicated indices — `rp-pptx` §4's rule,
same reasoning.

**A workbook must end with at least one visible sheet.** Excel refuses to open
one without it, so `delete_sheets` and any state change that would leave none
raise `InputError`. This is stricter than openpyxl, which will happily write the
broken file.

Sheet names are validated on the way in: Excel's forbidden characters
(`: \ / ? * [ ]`), a 31-character limit, non-empty, and unique within the
workbook. openpyxl raises `ValueError` for the characters but only *warns* past
31 characters (verified) — a warning is invisible to an agent, so this package
raises.

**Correction, post-implementation (PR review).** `rename_sheet` refuses
(`InputError`) rather than renames when a formula or a defined name
(workbook- or sheet-scoped) sheet-qualifies a reference to `old`. openpyxl
does not rewrite those references when a worksheet's title changes —
verified directly: a workbook with `Summary!A1 = =Data!A1` and a defined
name `'Data'!$A$1`, renamed `Data → Renamed` and reloaded, still contains
`=Data!A1` and `'Data'!$A$1` even though the sheet is now called
`Renamed`. A rename that proceeded anyway would report success while
leaving references pointed at a sheet that no longer exists — this
package's no-silent-wrong-output posture (§10) treats that as worse than
refusing. Detection (`refs.sheet_reference_pattern`) matches both the
quoted (`'Sheet Name'!`, internal `'` doubled per Excel's own escaping)
and bare (`Sheet1!`) forms, case-insensitively, and covers ordinary cell
formulas plus workbook- and sheet-scoped defined names; it does not scan
chart series, conditional formatting, or data validation formulas
(a documented gap, not a silent one). Reference *rewriting* — the
alternative the original spec text implied — is not implemented; refusal
was chosen deliberately over a partial rewrite that could miss some
reference-bearing structure and look done when it wasn't.

### Tabular interchange (`rp_xlsx.xlsx.tabular`)

```python
to_csv(path: Path, output_dir: Path, *, sheets="all", names=None,
       delimiter: str = ",", encoding: str = "utf-8") -> list[Path]
from_csv(sources: list[Path], *, delimiter: str | None = None,
         encoding: str = "utf-8", header: bool = True) -> list[SheetSpec]
from_json(source: Path | str) -> list[SheetSpec]
from_markdown(source: Path | str) -> list[SheetSpec]
```

`from_markdown` consumes `rp_core.markdown`'s AST and takes its GFM pipe tables,
using the nearest preceding heading as the sheet name. It is the one place this
package touches Markdown on the write side; there is no "Markdown document → 
workbook" mapping, because a workbook is not a document.

**Delimiter is explicit or inferred from the file extension** (`.tsv` → tab),
never sniffed from content. `csv.Sniffer` is wrong often enough on real exports
that the failure mode — one column containing everything — is a recognisable
bug report, and a silent misparse is exactly what parent §10 exists to avoid.

### Templates (`rp_xlsx.templates`)

```python
list_templates() -> list[TemplateInfo]
resolve_template(name_or_path: str | Path | None) -> Path | None
inspect_template(path: Path) -> TemplateInfo
build_manifest(path: Path) -> TemplateManifest
synthesize(manifest: TemplateManifest, output: Path) -> Path
fill_template(template: str | Path, context: dict, output: Path, *,
              strict: bool = True, allow_lossy: bool = False) -> FillResult
```

**`resolve_template` returns `None` for `None` here, unlike its two siblings**,
and this is a considered divergence rather than an oversight. `rp-docx` and
`rp-pptx` fall back to their library's bundled default template because
python-docx and python-pptx *have* one and a document must start from some set
of styles. openpyxl has no bundled workbook template, and `Workbook()` is not
one — it is an empty file. Inventing a house-less default would mean shipping a
binary or synthesizing a template nobody asked for. `create(template=None)`
therefore starts from `openpyxl.Workbook()`, and the "explicitness is erased by
resolution" problem `rp-pptx` §5.1 documents does not arise.

### Render / convert

Thin re-exports of `rp_core.render.render_pages` and
`rp_core.binaries.soffice_convert`, exactly as in `rp-docx` and `rp-pptx`. No
rendering implementation lives in this package.

**Rendering a spreadsheet is worth one warning in the docs:** LibreOffice
paginates a sheet according to its print area and page setup, so page count is a
property of the file's print settings rather than of its data. Say so in
`docs/usage-xlsx.md`; do not try to control it.

---

## 5. Templates

House workbooks — a branded report shell with headers, number formats, and a
few named ranges — are a real pattern, and the manifest/synthesis loop from
`rp-docx` §5.2 applies unchanged in shape.

**This whole section is a checkpointed sub-scope (§12 step 8).** It is the least
certain part of the phase: a spreadsheet template's value is mostly in styling,
and structural synthesis reproduces less of it than a `.potx` synthesis
reproduces of a deck. If step 8 fights back, the documented fallback is to ship
`list_templates`, `resolve_template`, `inspect_template`, and `fill_template`
(which are cheap and immediately useful) and defer `build_manifest`/`synthesize`
with the reasons in the status note. `fill_template` must not be deferred — it
is the feature people actually want from a template.

### 5.1 Resolution

Identical to `rp-docx` §5.1 and `rp-pptx` §5.1, with `.xltx`/`.xltm`/`.xlsx` in
place of `.dotx`/`.docx`:

1. Explicit `Path` that exists → use it
2. Bare name (e.g. `"quarterly"`) → resolve against `RP_XLSX_TEMPLATE_DIR`, then
   `<repo>/templates/local/`, then `<repo>/templates/`, trying `<name>.xltx`,
   then `<name>.xltm`, then `<name>.xlsx`
3. `None` → the configured default (`RP_XLSX_TEMPLATE`), else `None` (§4)
4. A path-shaped argument that does not exist → `InputError` naming the *path* —
   anything carrying a suffix or a separator is a wrong path, not a name
5. Unresolvable name → `InputError` listing the available templates

**`RP_XLSX_TEMPLATE_DIR` splits on `os.pathsep` and searches ancestor repo
roots**, matching `RP_DOCX_TEMPLATE_DIR`. `AGENTS.md` records that
`RP_PPTX_TEMPLATE_DIR` diverged from `rp-docx` here — a single directory,
`./templates` only — and that the asymmetry was written up rather than fixed.
Do not copy the divergent one. Two of three behaving alike is the closest thing
to a convention this suite has, and a third variant would end the possibility of
documenting any of it in one sentence.

### 5.2 Manifests and synthesis

Real house workbooks are confidential and cannot enter this repository. The loop
is `rp-docx` §5.2's:

1. `build_manifest()` runs against the real template, wherever it lives
2. The JSON is committed to `tests/fixtures/` — text, diffable, nothing confidential
3. `synthesize()` reconstructs a structurally equivalent `.xltx` at test time
4. CI exercises the real template's shape without the file ever leaving the
   machine that holds it

**Redaction is a correctness property, and this format makes the line harder
than the other two.** A `.potx` has layouts and no content; a workbook template
has cells, and cells are where the confidential data would be. `SheetShape`
therefore carries exactly three things that touch cell contents, each justified:

- **`header`** — a report's column headings are its schema, which is what a
  template *is*. Without them a synthesized template cannot exercise anything.
- **`placeholder_cells`** — `{{ client.name }}` is a slot, not a value.
  `fill_template` cannot be tested against a synthesized template without them.
- **`number_formats`**, per column and only where the column is uniform — a
  format string is presentation, and it is the thing most likely to be wrong.

Everything else is counts, ranges, names, and geometry. **No other cell value
enters a manifest**, and the §11 assertion is the same as `rp-docx`'s: a
manifest built from a template containing distinctive body text does not contain
that text anywhere in its serialized form. Write the fixture so the distinctive
text is a *body* cell, not a header — otherwise the test asserts nothing.

`synthesize()` reproduces sheet names, order, and visibility; header rows;
column widths; frozen panes; per-column number formats; defined names; table
names and refs; placeholder cells; and a placeholder image when
`image_count > 0`. It does not reproduce themes, fonts, colours, conditional
formatting, or data validation — structural equivalence for testing resolution
and filling, not visual fidelity. Say this in the docstring, because the gap
between "synthesized template" and "the real thing" is wider here than for the
other two formats.

### 5.3 `.xltx` handling — verified, and it is the mirror image of `.dotx`

Verified against openpyxl 3.1.5 (probe note §6):

- **`load_workbook("x.xltx")` works.** Unlike python-docx and python-pptx,
  openpyxl opens templates natively and sets `wb.template = True`. There is no
  read-side retyping to do, and `opened()` is correspondingly simpler than its
  two siblings.
- **`save()` carries the template content type across a rename.** A workbook
  loaded from `.xltx` and saved as `.xlsx` is *still typed as a template*. This
  is the same class of bug as `rp-pptx`'s, reflected: there, a template saved
  under a template name became a presentation; here, a template saved under a
  workbook name stays a template.

So `ooxml.save(workbook, output)` sets `workbook.template` from the **output
extension** before writing — `.xltx`/`.xltm` → `True`, `.xlsx`/`.xlsm` → `False`
— and a `TestContentTypes` test asserts both directions, exactly as in `rp-docx`
and `rp-pptx`. Also assert the openpyxl behaviour the workaround exists for, so
that the day openpyxl fixes it the test fails and `save()` can be simplified.

Macro-enabled formats add one more rule: `.xlsm`/`.xltm` are always opened with
`keep_vba=True` (verified: the default drops `xl/vbaProject.bin` outright), and
`create` writing to an `.xlsm` name without a macro source is an `InputError`
rather than a macro-free file wearing a macro-enabled extension.

`resolve_template` must find `.xltx` before `.xlsx` when both exist — test it.

---

## 6. The Fidelity Problem — the centre of this package

**Read this before writing any code that saves a workbook.**

`rp-docx` §6 and `rp-pptx` §6 are about a hazard in *editing text*. This package
inherits no such hazard: openpyxl returns a cell's string as one string, and
in-cell rich text is opt-in via `load_workbook(rich_text=True)`, which this
package does not use. The run-spanning problem does not exist here.

What exists instead is worse, because it is not local to the edit. **openpyxl
does not round-trip a workbook.** Two distinct losses, both verified, both
silent:

### 6.1 Every cached formula value is discarded

A formula cell in an Excel-written file holds `<f>SUM(A1:A2)</f><v>3</v>`.
openpyxl's writer emits the formula and drops the cached value. Load a workbook,
change one unrelated cell, save: every formula in the file now reads as `None`
to any programmatic consumer — including a subsequent `rp-xlsx` read — until a
real spreadsheet application opens it and recalculates.

This cannot be prevented while openpyxl is the writer, and it must not become a
reason to refuse every edit. Three responses, all required:

1. **`wb.calculation.fullCalcOnLoad = True` on every write.** Verified to
   round-trip. Excel and LibreOffice recompute on open, so a human never sees
   the hole. Not an option, not a flag — there is no reading of "save this
   workbook" that wants stale-or-absent values instead.
2. **`WriteResult.recalculation_required`** is `True` whenever the source
   contained formulas, so a caller learns it from the result rather than from
   the documentation.
3. **`WorkbookIndex.has_cached_values`** tells a reader, before it trusts a
   single number, whether this file has ever been through a calculating
   application. `False` on a workbook full of formulas means every value it
   reports is `None`, and knowing that is the difference between "the data is
   empty" and "the data has not been computed".

### 6.2 Parts openpyxl does not model are deleted

Verified by injection and round-trip: threaded comments, the persons part,
pivot caches, slicers, form controls, and custom XML are all gone after a
load→save, with no error and no warning. The list is representative; the rule is
"whatever openpyxl does not model", and next year's openpyxl models more.

**So the guard keys on presence of at-risk parts, not on a list of features.**
`fidelity.scan(path) -> FidelityReport` reads the package's part names and
content types through `rp_core.ooxml` and classifies anything in a known at-risk
category. Every write path against an existing workbook calls it first:

- `safe_to_edit` → proceed.
- Otherwise → raise **`LossyEditError`** (an `RpXlsxError`, **exit code 3** —
  the taxonomy already reads 3 as "unreadable/unsupported", parent §4.1). The
  message names the categories and the parts; the hint names `--allow-lossy`.
- `allow_lossy=True` → proceed, and report what was dropped in
  `WriteResult.dropped`. **The flag never makes the loss silent.**

Presence is detectable with certainty; placement is not. `rp-pptx`'s
modern-comment finding applies verbatim (`AGENTS.md`: *"Presence and placement
are different questions with different reliability"*) — the guard fires on the
part being in the package, and only sharpens its message with a sheet name when
it can attribute one.

**Reads are never blocked by this.** `get_index` stays total and reports
`at_risk`; `rp-xlsx fidelity FILE` reports it in full. An agent should be able to
ask "what would editing this cost me?" and get an answer without attempting the
edit.

**Macros are not in the at-risk set** — they are handled instead. `.xlsm`/`.xltm`
open with `keep_vba=True` (§5.3), so the macros survive. Verified.

### 6.3 What this rules out, deliberately

A part-preserving writer — merge openpyxl's output back over the original zip,
keeping unmodelled parts — is the obvious next idea and is **out of scope for
Phase 3**. Relationship IDs, content-type overrides, and `calcChain.xml` all
have to stay consistent with a sheet XML that openpyxl rewrote wholesale, and a
half-correct merge produces a file Excel repairs on open, which is a corrupted
workbook wearing a green test suite. Record it in the status note as the natural
Phase 3.5 if real workbooks demand it.

---

## 7. What Needs Raw XML

Far less than in the OOXML leaves, because openpyxl models most of the format.
Everything below goes through `rp_xlsx.ooxml` over `rp_core.ooxml`, with the
SpreadsheetML namespace map and content-type strings living there and nowhere
else.

- **§6's part scan.** Part names and content types only; no sheet XML parsing.
- **Template retyping** (§5.3) — driven by `wb.template` plus a content-type
  assertion in tests.
- **`has_cached_values`** — the observable is a `<v>` sibling of an `<f>` in a
  sheet part. Detecting it by loading twice and comparing works but doubles the
  parse cost of an index; reading the first sheet part directly is cheap. Either
  is acceptable; the test asserts the observable, not the technique.
- **Threaded comments** are read *nowhere*. openpyxl reads only classic
  comments; §6 stops an edit from deleting the threaded ones. Reading them is
  future work, and the note in the status document should say so, because "no
  comments" and "no comments openpyxl can see" are different answers to
  `get_comments`. Report classic comments and let `at_risk` carry the rest —
  unlike `rp-pptx`'s deck-wide raise, a workbook with threaded comments is still
  a workbook whose cells read correctly, and refusing the whole read would cost
  far more than it protects.

**A part's filename is not its position.** `xl/worksheets/sheet1.xml` is not
necessarily the first sheet: sheet order lives in `xl/workbook.xml`'s
`<sheets>` element, and the `r:id` on each `<sheet>` resolves through the
relationships part. This is the same trap `rp-pptx` fell into with
`p:sldIdLst`, and this package's own `reorder_sheets` and `delete_sheets` make
it reachable. Any raw-XML code that needs to know which sheet a part belongs to
walks `<sheets>` → relationship → part. openpyxl's own object model already
does this correctly, so the rule binds only `ooxml.py` and `fidelity.py`.

---

## 8. Templating Without Dependencies

Identical rules to `rp-docx` §8 and `rp-pptx` §8:

- Syntax: `{{ key }}` and `{{ key.subkey }}` only. **No expression evaluation,
  no Jinja.**
- Loops and conditionals are out of scope — generate rows from data instead
  (§4's `create`/`append_rows` are the answer to "repeat this row per record").
- `strict=True` raises `InputError` on unresolved placeholders; `strict=False`
  leaves them in place and reports them in `FillResult.unresolved`
- A key that matched nothing is reported with a count of zero

**Scope of substitution:** cell string values on every sheet, plus header and
footer text (`ws.oddHeader`/`oddFooter` and their even/first variants). Not
formulas (§4's rule), not sheet names, not defined names, not comments. A
placeholder inside a cell that also contains other text is replaced in place,
leaving the surrounding text alone.

Because a cell's text is a single string, substitution is a `str.replace` — the
three-step run-offset dance from the other two leaves is not needed and must not
be copied over. Overlapping placeholder keys still resolve **longest-first**, so
results never depend on dict ordering; that part of the inherited rule does
apply.

---

## 9. Tabular Mapping and Other Footguns

Everything here was verified, or is a direct consequence of something verified.

**Declared dimensions lie.** A sheet with one value in `A1` and a *fill colour*
on `E1000` reports `max_row = 1000` and `dimensions = "A1:E1000"` (verified) —
and `read_only=True` reports the same. So `SheetInfo` carries both
`declared_range` (what the file says) and `used_range` (the bounding box of
cells that actually hold a value or a formula), and every read that returns rows
uses the latter. An agent asking for "the data" must never be handed 999 rows of
nulls. This is the single most common complaint about every spreadsheet-reading
tool that has ever existed.

**Merged cells: the origin holds the value, the rest are `MergedCell` with
`value = None`** (verified). `get_data` reports them as `None` — the grid shape
is the truth — and `get_cells` marks the origin with `is_merged_origin`. Do not
"helpfully" broadcast the origin's value across the span: a caller computing a
column sum would double-count, and `rp-pptx` §3 made the opposite choice for a
format where the grid is presentational rather than data.

**Dates come back as `datetime`, always** (verified) — a date-only cell arrives
at midnight, because the format string is the only thing distinguishing the two
and `is_date` reports it. Serialize as ISO-8601; a bare date renders as
`2024-05-01T00:00:00`, which is honest about what the file holds.

**Values are not display strings.** A cell showing `25.00%` has value `0.25` and
number format `0.00%`; one showing `$1,234` holds `1234`. `get_data` returns the
value. Implementing Excel's number-format engine is out of scope, and a partial
implementation is worse than none, because a caller cannot tell which cells it
got right. `get_cells` reports `number_format` so a caller who needs the display
string can produce it deliberately.

**1904 date systems exist.** A workbook authored on classic Mac Excel offsets
every date by four years. openpyxl handles this via `wb.epoch`; the only
requirement here is not to construct datetimes by hand from serial numbers
anywhere in this package. If you find yourself writing `1899-12-30`, stop.

**Empty string, `None`, and a cell that does not exist are three different
things** and JSON has two of them. `None` means "no value"; `""` means a cell
holding an empty string (which Excel does store, and which changes `used_range`);
a cell absent from `get_cells` output means it was never written. Document it in
`docs/usage-xlsx.md`, because an agent diffing two reads will otherwise see
noise.

**`create` writes with `header_style=True` by default** — a bold header row and
a freeze on row 2, which is what every human wants and no agent will think to
ask for. It is a flag, so `--no-header-style` exists for a machine-consumed
file. Column widths are set from content length, capped, unless supplied.

**Very large workbooks.** `read_only=True` streams and is dramatically cheaper on
a 100MB file, but the resulting worksheet is a different class with a reduced
API (verified: `ReadOnlyWorksheet`), and it does not fix `max_row`. Use it for
`get_data`/`get_cells` when no cell-level styling is requested, and take the
normal path otherwise; the choice must be invisible in the output. `write_only`
mode exists for `create` with large inputs. Neither is a CLI flag — a
performance mode a caller has to know to ask for is a performance mode that goes
unused.

**Two loads are required to see both a formula and its value** (verified: they
come from `data_only=False` and `data_only=True` respectively). `values="cached"`
does both and merges; `values="formulas"` does one load and reports formulas
with `value_available: false`. Default to the merge — correctness first — and
let `--formulas-only` buy back the second parse on a huge file.

**Sheet name validation differs between the two directions.** openpyxl raises
`ValueError` for `[`, but merely warns past 31 characters (verified). This
package raises in both cases (§4), and the error is an `InputError` with the
offending name, never a `ValueError` reaching the user (parent §4.1).

**`.xls` is refused on its extension, before any content check** (verified) — so
a valid `.xlsx` renamed to `.xls` is also refused. The error message must name
the file's *extension* as the reason and suggest
`soffice --headless --convert-to xlsx FILE`, or a user with a correctly-formed
file will conclude the file is corrupt.

**`BadZipFile` is a `zipfile` exception**, not an openpyxl one (verified). Both
it and `InvalidFileException` must be caught and mapped: a corrupt package is
`CorruptFileError` (exit 3), an unsupported format is `InputError` (exit 1),
and a missing file is `MissingFileError` (exit 1, also a `FileNotFoundError` for
library callers) — the `rp-pdf` pattern, unchanged.

---

## 10. CLI Design

```
rp-xlsx doctor                                 # via rp_core.clikit.doctor_command

rp-xlsx index     FILE [--plain]
rp-xlsx data      FILE [--sheets SPEC] [--sheet NAME]... [--cells RANGE]
                       [--no-header] [--max-rows N] [--formulas-only]
                       [--format json|csv|md] [-o DIR] [--plain]
rp-xlsx cells     FILE [--sheets SPEC] [--sheet NAME]... [--cells RANGE] [--empty] [--plain]
rp-xlsx formulas  FILE [--sheets SPEC] [--plain]
rp-xlsx tables    FILE [--sheets SPEC] [--plain]
rp-xlsx names     FILE [--plain]
rp-xlsx comments  FILE [--sheets SPEC] [--plain]
rp-xlsx images    FILE [--sheets SPEC] [-o DIR] [--plain]
rp-xlsx charts    FILE [--sheets SPEC] [--plain]
rp-xlsx props     FILE [--plain]
rp-xlsx markdown  FILE [-o OUT] [--sheets SPEC] [--cells RANGE] [--max-rows N]
rp-xlsx fidelity  FILE [--plain]

rp-xlsx create    -o OUT [--from-csv FILE]... [--from-json FILE] [--from-markdown FILE]
                         [--template NAME|PATH] [--no-header-style]
rp-xlsx set       FILE --map JSON (-o OUT | --in-place) [--allow-lossy]
rp-xlsx append    FILE --sheet NAME (--rows JSON | --from-csv FILE)
                         (-o OUT | --in-place) [--allow-lossy]
rp-xlsx replace   FILE --map JSON (-o OUT | --in-place) [--sheets SPEC]
                         [--ignore-case] [--include-formulas] [--allow-lossy]
rp-xlsx template  TEMPLATE --context JSON -o OUT [--no-strict]

rp-xlsx sheets list    FILE [--plain]
rp-xlsx sheets add     FILE --name NAME [--index N] (-o OUT | --in-place) [--allow-lossy]
rp-xlsx sheets delete  FILE (--sheets SPEC | --sheet NAME...) (-o OUT | --in-place) [--allow-lossy]
rp-xlsx sheets rename  FILE --from NAME --to NAME (-o OUT | --in-place) [--allow-lossy]
rp-xlsx sheets reorder FILE --order LIST (-o OUT | --in-place) [--allow-lossy]

rp-xlsx templates list                [--plain]
rp-xlsx templates inspect NAME        [--plain]
rp-xlsx templates manifest FILE       [-o OUT.manifest.json]
rp-xlsx templates synthesize MANIFEST -o OUT.xltx

rp-xlsx convert   FILE --to pdf|csv|ods|html [-o OUT]
rp-xlsx render    FILE -o DIR [--dpi 150] [--pages 1-5]
```

**`sheets` is a sub-app, so there is no bare `rp-xlsx sheets FILE`.** typer
cannot register a command and a sub-app under one name, and per-sheet metadata
is already in `index`. `sheets list` exists so the sub-app is discoverable and
so a script that only wants names does not parse the whole index.

**Rules** — inherited from `rp-docx` §10 and `rp-pptx` §10, restated because
they are contract:

- **JSON is the default output** for every read command, via `model_dump_json()`.
  `--plain` produces human-readable output. **There is no `--json` flag** —
  parent §4.6, enforced suite-wide by a test that reads parsed parameters rather
  than rendered help.
- Errors, exit codes, and the `ErrorEnvelope` payload come from
  `rp_core.clikit`. Do not construct error output locally.
- `--sheets` takes the `rp_core.ranges` spec over 1-based sheet position;
  `--sheet` takes a name and is **repeatable**; supplying both is an
  `InputError` (§4).
- `--cells` takes A1 notation.
- **Never overwrite an input file without `--in-place`.** Every editing command
  takes it and refuses when given neither it nor `-o`.
- `--map`, `--rows`, and `--context` accept either a path to a JSON file or the
  JSON itself.
- `--order` takes a comma-separated permutation (`3,1,2`).
- `--allow-lossy` appears on **every** command that writes to an existing
  workbook, and nowhere else. Its help text says what it permits, not what it
  disables.
- `create` and `render` write artifacts **and** emit JSON describing what they
  wrote; `markdown -o` and `data --format csv -o` write the artifact and emit
  JSON. `AGENTS.md` records that this claim was previously wrong in six files at
  once — state it once, correctly, and grep for the copies.
- Every new subcommand must be registered wherever the CLI's dispatcher requires
  it, and the parent §10 command-surface invariant test gets an `rp-xlsx`
  equivalent (`packages/rp-xlsx/tests/test_invariants_xlsx.py`), asserting the
  command surface matches this section.

---

## 11. Testing

### 11.1 No binary fixtures in git

Inherited outright: **nothing binary is committed.** Every workbook and template
is generated in `conftest.py`. `tests/fixtures/` holds only `*.manifest.json`.

Three fixture families cannot be produced by openpyxl's public API and must be
built the way `rp-docx` builds tracked changes — by writing parts onto a
generated package:

1. **Cached formula values** — inject `<v>` beside `<f>` in the sheet part. This
   is the only way to test §6.1, and without it every fidelity test passes
   vacuously, because an openpyxl-authored workbook has no cached values to
   lose. The probe note's script is the working recipe.
2. **At-risk parts** — threaded comments, a persons part, a pivot cache, a
   slicer, a form control, custom XML. They need no valid content: §6's guard
   keys on part names and content types, so the fixture is honest about being a
   presence fixture and no test asserts anything about their contents. (This is
   `rp-pptx`'s `modern_comments_deck` doctrine, and the reasoning transfers
   exactly.)
3. **A macro-enabled workbook** — inject an `xl/vbaProject.bin` with arbitrary
   bytes and the macro-enabled content type, to test that `keep_vba` preserves
   it.

`templates/local/` remains the gitignored drop point for real workbooks during
manual testing. Nothing there is ever required by CI.

### 11.2 Three synthetic templates, built in `conftest.py`

Adversarial, not realistic — same doctrine, same trio:

| Fixture | Purpose |
|---|---|
| `minimal` | One sheet, a header row, no placeholders, `.xlsx`. The happy path and the no-template path. |
| `house_like` | `.xltx`; three sheets including one hidden and one named `"2"` (§4's disambiguation test); a header row; per-column number formats including a percentage and a date; frozen panes; a defined name; an Excel table; `{{ }}` placeholders in a title block; an image on the first sheet; a sheet name containing a space and a non-ASCII character. |
| `hostile` | A sheet whose name is 31 characters exactly; a cell whose value begins with `=` but is stored as text; a merged block; a formula with no cached value; a column of mixed types; a format-only cell at row 5000 (the phantom-dimension case); a placeholder split by nothing but adjacent to another placeholder key that is a prefix of it (`{{ client }}` and `{{ client.name }}` — the longest-first rule). |

Required assertions:

- `house_like` round-trips: `inspect_template` → `build_manifest` →
  `synthesize` → the synthesized template's sheet names, order, visibility,
  headers, number formats, defined names, table names, and placeholder cells
  equal the original's
- A manifest built from a template whose **body** cells contain distinctive text
  does not contain that text anywhere in its serialized form (§5.2)
- `resolve_template` prefers `.xltx` over `.xlsx` when both exist
- A wrong path reports the path, not "no template called …" (§5.1 case 4)
- `resolve_template(None)` returns `None`, and `create(template=None)` succeeds
  (§4's divergence from the sibling packages)
- `hostile`'s phantom row does not appear in `get_data`, and `used_range` differs
  from `declared_range`
- `{{ client }}` and `{{ client.name }}` in the same cell both resolve correctly,
  longest-first, regardless of dict ordering

### 11.3 Everything else

- **§6 is tested from the observable, not the code path.** Required: a workbook
  with injected cached values loses them across an edit *and* the result reports
  `recalculation_required: true`; the written file carries `fullCalcOnLoad`; a
  workbook with an at-risk part raises `LossyEditError` with **exit code 3** and
  an envelope naming the part; `--allow-lossy` proceeds and lists the same parts
  in `dropped`; `get_index` on that workbook still succeeds and reports
  `at_risk`; an `.xlsm` keeps its `vbaProject.bin` across an edit with no flag.
  Every one of these asserts on a file or an envelope, because `AGENTS.md`'s
  rule is that a guarantee needs an observable, and here the observable is the
  bytes on disk.
- Round-trip tests: create → read → assert; set → read → assert; replace → read
  → assert; sheet add/delete/rename/reorder → names-and-order assert
- `delete_sheets` covering every visible sheet raises `InputError`; deleting all
  but one succeeds
- Sheet-name validation: forbidden character, over 31 characters, duplicate,
  empty — all `InputError`, none reaching the user as `ValueError` or a warning
- Selector tests: `--sheets 2` and `--sheet "2"` select different sheets on a
  workbook containing a sheet named `"2"`; supplying both is an error
- A boolean cell survives serialization as `true`, not `1` (§3)
- A merged block reports `None` for spanned cells and marks the origin
- A date-only cell and a datetime cell both serialize as ISO-8601
- A percentage cell reports `0.25` with format `0.00%`
- `replace_text` does not alter a formula by default and does with
  `--include-formulas`
- A value beginning with `=` is written as a formula; a `'`-prefixed one is not
- `.xls`, `.xlsb`, and a corrupt `.xlsx` produce `InputError`/`InputError`/
  `CorruptFileError` with the right exit codes and no bare builtin
- CSV round trip: `to_csv` → `from_csv` → `create` reproduces values; delimiter
  comes from `--delimiter` or the extension, never from sniffing
- Explicit test that read commands emit JSON with no flag and human output with
  `--plain`
- LibreOffice-dependent tests use the functional probe pattern
  (`requires_soffice` probes that conversion *works*), and skip cleanly. **No
  test may require LibreOffice to pass.**
- Test module basenames carry the `_xlsx` suffix, as `rp-pptx`'s do
- Target > 85% coverage on `xlsx/`, `ooxml.py`, `fidelity.py`, `refs.py`, and
  `templates.py`

---

## 12. Phase 3 — Execution Plan

**Audience: the implementing session.** Prerequisites: none. Phases 0–2.5 are
merged; this phase depends on none of them beyond the shared infrastructure they
left behind. **No real workbook or house template is required at any point.**

### 12.0 Before writing any code

Read, in this order: `AGENTS.md` (all of it — the failure-modes section is a
list of bugs this repo has already shipped), this document §6 and §9,
`dev-notes/phase-3-openpyxl-probe.md`, and
`dev-notes/status-robo-papyro-phase-2.5.md` (the closest precedent — same
shape of work, and its "findings" section is what a good status note looks
like). Skim `packages/rp-pptx/src/rp_pptx/` for the house style; this package
should look like its sibling to anyone reading both.

Then set the environment up and confirm the baseline is green *before* changing
anything:

```sh
uv sync --all-extras
uv run rp doctor                    # install poppler if it reports it missing — AGENTS.md says how
uv run pytest -q                    # must be green before you start
```

**Working rules for this phase**, all inherited and all enforced somewhere:

- Land the work in the order below. Each step is a commit or a small group of
  them, with its tests, and the suite is green at every commit.
- **Test the behaviour the spec asks for, not the behaviour you wrote.** Write
  each assertion from this document, then make it pass. `AGENTS.md` explains why
  this is the rule that has caught the most real bugs here.
- Do not add a dependency beyond `openpyxl` (and the `et-xmlfile` it brings).
  If one seems necessary, stop and ask.
- Where reality contradicts this spec, **reality wins** — implement what is
  correct and record the contradiction for the status note as you go. Every
  previous phase found several; finding none means you are not looking.
- Before pushing anything that touches output:
  `CI=true GITHUB_ACTIONS=true uv run pytest -q`.

### Step 1 — Scaffold the distribution

`packages/rp-xlsx/` with `pyproject.toml`, `src/rp_xlsx/`, `tests/`, `README.md`.
Declare `rp-core` in `dependencies` **and** `[tool.uv.sources] rp-core = {
workspace = true }` — members do not inherit. Register the CLI twice:
`[project.scripts] rp-xlsx = "rp_xlsx.cli:app"` and
`[project.entry-points."robo_papyro.commands"] xlsx = "rp_xlsx.cli:app"`. Add
`rp-xlsx` to `robo-papyro`'s runtime dependencies, and update
`TestPackagingContract` in `packages/robo-papyro/tests/test_umbrella_cli.py`,
which reads the manifest and will not otherwise notice.

Add `openpyxl` (already pre-approved) and **`et-xmlfile = "MIT"`** to
`ci/allowed-packages.toml`.

**Verify:** `uv sync && uv run rp xlsx --help && uv run rp-xlsx --help` and
`python3 ci/license_gate.py`. Do not proceed until the umbrella resolves the new
leaf — a broken entry point discovered later looks like a dozen unrelated
failures.

### Step 2 — Promote `CoreProperties` to `rp-core`

Per §3. Move the model into `rp_core.models`, re-export it from
`rp_docx.models` and `rp_pptx.models` so no import in either leaf changes, and
run both packages' suites — **they must pass unchanged**. Nothing else moves.

Fallback, if it fights back (it should not — it is a model with eight scalar
fields): define `CoreProperties` locally in `rp_xlsx.models` a third time,
record why in the status note, and continue. Do not let this block the phase.

**Verify:** `uv run pytest packages/rp-docx packages/rp-pptx packages/rp-core -q`,
and `uv run pytest ci -q` for the `rp_core`-has-no-format-identifier invariant.

### Step 3 — `models.py`

Per §3, xlsx-specific models only. Get `CellValue`'s union order right and write
the boolean test now, while the reason is in front of you.

### Step 4 — `refs.py`, standalone and unit-tested first

A1 notation and sheet selection, with no openpyxl import and no I/O: parse
`"A1"`, `"A1:D20"`, `"B:B"`, `"3:3"`; convert column letters to and from
indices (including `AA`, `ZZ`); resolve the `sheets`/`names` pair to an ordered
list of sheet positions, raising `InputError` when both are given or a name is
unknown (the error lists the workbook's sheet names). Malformed input is
`InputError` naming the offending token.

Build and test this before anything depends on it, exactly as `rp-pptx` did with
`runs.py`. Include the sheet-named-`"2"` case here — it is a pure-function test
and belongs at this level.

### Step 5 — `ooxml.py` and `fidelity.py`, with a checkpoint

`ooxml.py`: the SpreadsheetML namespace map and content-type strings,
`opened(path)` (which selects `keep_vba` from the extension and `data_only` from
the caller), and `save(workbook, output)` with §5.3's output-extension retyping.
`TestContentTypes` lands here, asserting both directions **and** the openpyxl
behaviour the workaround exists for.

`fidelity.py`: `scan(path) -> FidelityReport` per §6.2, over `rp_core.ooxml`'s
part names and content types, plus the `has_cached_values` observable (§7).

Build the injection fixtures from §11.1 in this step — the guard cannot be
tested without them.

**CHECKPOINT — report before continuing.** Re-run the probe note's four findings
against the openpyxl version `uv.lock` actually resolved, and report: the
version, whether each finding still holds, and the `FidelityReport` for the
at-risk fixture. If a real Excel-authored workbook is available, also report
what a load→save does to it (§4 of the probe note is explicitly *not* evidence
about Excel-authored charts). If a finding no longer holds, say so plainly and
adjust §6 — the guard's shape does not depend on the specific list, which is
why it was written that way.

### Step 6 — `xlsx/read.py`

Implement in this order, with tests alongside each: `get_properties`,
`get_index`, `get_data`, `get_cells`, `get_formulas`, `get_tables`, `get_names`,
`get_comments`, `get_images`, `get_charts`, `get_markdown`.

`get_index` is the one that must never refuse a readable file: at-risk parts,
threaded comments, an unreadable chart, a phantom dimension — none of them may
make an index fail. Every §9 footgun surfaces in this step; work through that
section as a checklist and write the test for each as you go.

Progress reporting (`rp_core.progress`) goes on `get_data` and `get_cells` here,
not as a later retrofit — and note `AGENTS.md`'s warning that a progress test
which opens a step first cannot catch a reporter that starts too late.

### Step 7 — `xlsx/write.py` and `xlsx/sheets.py`

On top of §6's guard, which every entry point calls **first** — before opening
the workbook, so a refusal costs nothing and cannot half-write. `fullCalcOnLoad`
on every save. `recalculation_required` computed from the source, not from what
was written.

Then `sheets.py`: add, delete, rename, reorder, with §4's permutation rule, the
at-least-one-visible-sheet rule, and name validation.

### Step 8 — `templates.py` and `xlsx/template.py`, checkpointed

§5 and §8. Build the three synthetic templates from §11.2 in `conftest.py`
first — they are what tells you whether `inspect_template` is right.

**CHECKPOINT — report before continuing:** `inspect_template` output for
`house_like`, the manifest built from it, and the synthesized round-trip. The
equivalent checkpoint in Phase 1 caught two silently-unpopulated manifest
fields, and Phase 2.5's caught that synthesis needed raw XML.

§5's deferral clause applies to `build_manifest`/`synthesize` only, and taking it
is a legitimate outcome: ship resolution, inspection, and `fill_template`,
record the reasons in the status note, and move on. `fill_template` is not
deferrable.

### Step 9 — `xlsx/tabular.py`

CSV/TSV both directions, JSON in, Markdown tables in (via `rp_core.markdown`),
Markdown out (via `get_markdown`). Explicit delimiters, explicit encodings, no
sniffing.

### Step 10 — `cli.py`

Per §10, using `rp_core.clikit` for every convention: `plain_option`, `emit`,
`handle_errors`, `doctor_command`. Add
`packages/rp-xlsx/tests/test_invariants_xlsx.py` asserting the command surface
matches §10, modelled on `rp-pptx`'s.

Read parsed parameters, never rendered `--help`, in every CLI test —
`AGENTS.md` explains how a negative assertion on rendered help passes for the
wrong reason on exactly the run that gates a merge.

### Step 11 — the MCP server

`packages/rp-mcp/src/rp_mcp/xlsx.py`, one tool per leaf function, ~3 lines each:
name, docstring, call. Register the suite in `rp_mcp/cli.py` and add the
`rp-xlsx-mcp` console script. Every path argument goes through
`sandbox.resolve_input`/`resolve_output`; the write tools register only when
`sandbox.writable`. `packages/rp-mcp/tests/test_invariants_mcp.py` walks the
registered tool list, so it covers the new tools automatically — but read it
first: synthesized arguments must pass schema validation or the check never
reaches the body.

Two xlsx-specific decisions for the tool docstrings, and they matter more here
than in the other leaves: **`allow_lossy` must be exposed** (an agent that
cannot override the guard will retry the same call forever), and every write
tool's docstring must say that formulas lose their cached values and the file
needs opening in Excel to recompute. `docs/security-mcp.md` changes in the same
commit if any sandbox rule changes; it should not need to.

### Step 12 — Documentation, skill, and CI

All of it, in one pass, then grep for the copies:

- `docs/usage-xlsx.md`, modelled on `docs/usage-pptx.md`, with §6 explained in
  plain language — it is the thing a user must understand before editing a
  workbook.
- `skills/spreadsheet-toolkit/SKILL.md`. **Run every command in it.**
  `ci/test_skill_commands.py` checks quoted flags against the parsed command and
  needs `rp-xlsx` added to its `APPS` and `UMBRELLA` maps; it cannot catch a
  semantic constraint like "`--allow-lossy` is meaningless on `create`", so
  check those against §10 by hand.
- `README.md` (the distribution table, a `## rp-xlsx` section, and the base
  install path count if it changes), `AGENTS.md` (distribution table, layout,
  a `### rp-xlsx` package-notes section whose first line is §6, the invariants
  table, and the licensing paragraph), `ROADMAP.md`, and
  `docs/specs/robo-papyro-spec.md` §1/§3/§9.
- `.github/workflows/ci.yml`: `rp-xlsx` in the test matrix; smoke steps for
  `rp xlsx`/`rp-xlsx` identity, a no-external-binary round trip, and the
  exit-code taxonomy including `LossyEditError`'s 3; `rp-xlsx-mcp --help`.
- `dev-notes/status-robo-papyro-phase-3.md`, in the pattern of
  `status-robo-papyro-phase-2.5.md`: what landed, the verification numbers, and
  **every decision that went the other way first**. The corrections are the
  valuable part. Link it from the `ROADMAP.md` entry.

### Definition of done

Suite green with nothing binary committed; coverage targets met; both `rp-xlsx`
and `rp xlsx` functional and byte-identical on the same input; JSON by default
with `--plain` working and no `--json` flag anywhere; errors matching
`ErrorEnvelope` with the right exit codes; the license gate green with
`et-xmlfile` allowlisted and the base install path still free of weak copyleft;
`rp-xlsx-mcp` serving over stdio with the write tools absent without a write
root; §6's guard demonstrated by tests that assert on bytes and envelopes; and a
status note listing every place §4–§9 turned out to be wrong in practice.

---

## 13. After Phase 3 — Validating Against a Real Workbook

Ships without ever seeing a corporate workbook; validation is a separate manual
pass, mirroring `rp-docx` §13 and `rp-pptx` §13:

1. Drop a real workbook into `templates/local/`
2. `rp-xlsx index` and `rp-xlsx fidelity` → confirm sheets, used ranges, and the
   at-risk report match what the file actually contains. **This is the step that
   matters most**: §6's guard is only as good as its category list, and a real
   corporate workbook is the first thing that will carry a part nobody here
   thought of.
3. `rp-xlsx data --sheets 1 --max-rows 20` → confirm the used-range detection
   against a sheet with real formatting
4. Edit a copy, open it in Excel, and confirm the recalculation actually happens
   and nothing is reported as repaired
5. `rp-xlsx templates manifest` on a real house template → commit the manifest to
   `tests/fixtures/` so CI regression-tests its shape from then on

Only step 5 produces a repository artifact, and it carries no confidential
content by construction (§5.2). Everything discovered in steps 2–4 comes back as
a defect report or a spec correction, not as a file.
