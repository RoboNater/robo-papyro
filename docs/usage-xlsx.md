# Excel (`rp-xlsx`)

`rp-xlsx` reads, creates, edits, and restructures `.xlsx` workbooks, `.xlsm`
macro-enabled workbooks, and `.xltx`/`.xltm` templates. Structured read
commands (`index`, `data`, `cells`, `formulas`, `tables`, `names`, `comments`,
`images`, `charts`, `props`, `fidelity`) emit JSON on stdout by default; add
`--plain` for human-readable output. There is no `--json` flag — JSON *is* the
default for these. `convert` and `render` follow the same convention: they
write the requested artifacts to disk and report JSON result metadata to
stdout by default, same as any other command. `markdown` is the one command
whose stdout differs by design: with no `-o` it prints Markdown itself; given
`-o FILE` it writes the file and reports a JSON `FileWritten` (the output
path) to stdout instead of the Markdown.

Reachable two ways, which are the same code:

```sh
uv run rp-xlsx index report.xlsx
uv run rp xlsx index report.xlsx
```

## Reading

```sh
rp-xlsx index    report.xlsx                     # sheets, formulas, defined names, at-risk parts
rp-xlsx data     report.xlsx --sheets 1-3         # values as a grid, never display strings
rp-xlsx data     report.xlsx --format csv -o ./out # also: md, json (default)
rp-xlsx cells    report.xlsx --cells A1:D20        # every cell: formula and cached value
rp-xlsx formulas report.xlsx                       # only the formula cells
rp-xlsx tables   report.xlsx                       # Excel table objects (ListObjects)
rp-xlsx names    report.xlsx                       # defined names, workbook- and sheet-scoped
rp-xlsx comments report.xlsx                       # classic per-cell comments
rp-xlsx images   report.xlsx -o ./img              # metadata, and the bytes if -o
rp-xlsx charts   report.xlsx                       # series references — values not evaluated
rp-xlsx props    report.xlsx --plain
rp-xlsx markdown report.xlsx -o report.md
rp-xlsx fidelity report.xlsx                       # what editing this file would cost
```

`--sheets` takes the suite's range syntax on sheet *position*, 1-based: `all`,
`2`, `1-3`, mixed lists (`1,3-5`). A workbook can have a sheet literally named
`"2"`, which `--sheets 2` would not select — use `--sheet NAME` (repeatable)
instead to select by name.

**Values are not display strings.** A cell showing `25.00%` reports `0.25`;
a cell showing `$1,234` reports `1234`. `cells` reports `number_format`
alongside the value for a caller that needs to reproduce the display string.
Dates always come back as ISO-8601 datetimes, even for a date-only cell
(`2024-05-01T00:00:00`), because the number format is the only thing that
distinguished the two in the file.

**`None`, `""`, and an absent cell are three different things.** `None` means
the cell has no value; `""` means the cell holds a stored empty string, which
Excel does allow and which affects the sheet's used range; a cell that never
appears in `cells` output was never written at all. A diff between two reads
that treats these as the same thing will see noise that isn't there.

**A sheet's declared dimensions lie.** A cell with only a fill colour, far
below the real data, inflates `max_row` and `dimensions` — every read that
returns rows uses the sheet's *used* range (bounding box of cells that
actually hold a value or formula), not the declared one, so asking for "the
data" never hands back hundreds of rows of nulls.

## Creating and editing

```sh
rp-xlsx create  -o report.xlsx --from-csv data.csv --template house
rp-xlsx set     report.xlsx --map '{"Sheet1": {"B2": 5}}' -o edited.xlsx
rp-xlsx append  report.xlsx --sheet Data --rows '[[1, 2]]' -o bigger.xlsx
rp-xlsx replace report.xlsx --map '{"old": "new"}' -o filled.xlsx
rp-xlsx template house --context '{"client": {"name": "Acme"}}' -o pitch.xlsx
rp-xlsx sheets add     report.xlsx --name New -o added.xlsx
rp-xlsx sheets delete  report.xlsx --sheet New -o trimmed.xlsx
rp-xlsx sheets rename  report.xlsx --from Old --to New -o renamed.xlsx
rp-xlsx sheets reorder report.xlsx --order 3,1,2 -o reordered.xlsx
```

**Every editing command needs `-o` or `--in-place`.** It will not guess a
filename and it will not overwrite the input silently. `--map`, `--context`,
and `--rows` take either inline JSON or a path to a JSON file.

A value beginning with `=` in `set` is always treated as a formula, never as
literal text. `append` adds rows after a sheet's *used* last row — never after
a phantom dimension from a stray formatted cell. `sheets reorder --order` must
be a complete permutation of the workbook's sheets; anything else is an error
naming what is missing, duplicated, or out of range, and `sheets delete`
refuses to leave zero visible sheets.

`replace` rewrites cell values and header/footer text, and **skips formulas by
default** — a replacement landing inside `=SUM(Revenue!A1:A9)` would otherwise
break it or silently repoint it. Pass `--include-formulas` to opt in.

### CSV, JSON, and Markdown sources

`create` can build sheets from one or more `--from-csv` files, a `--from-json`
file (an array of `{"name", "header"?, "rows"}` objects), or `--from-markdown`
(every pipe table in the document becomes a sheet). `append --from-csv` adds a
single CSV's rows to an existing sheet.

CSV values are coerced conservatively: a field parses as a number only if it
round-trips cleanly, so `"007"` and `"1.5.0"` stay text rather than becoming
`7` or a broken float. `to_csv`/`data --format csv` writes `\r\n` line endings,
matching what Excel itself produces.

## Formulas and cached values

**openpyxl does not round-trip a workbook — this is the thing to know before
anything else.** Two losses, both silent, both unavoidable while openpyxl is
the writer:

- **Every write drops every formula's cached value.** Load a workbook, change
  one cell, save: every formula in the file now reads as `None` to any
  programmatic reader, including a subsequent `rp-xlsx` read, until a real
  spreadsheet application opens the file and recalculates. `rp-xlsx` sets
  `wb.calculation.fullCalcOnLoad = True` on every write so Excel and
  LibreOffice do that automatically the moment a human opens the result — the
  hole only shows up to another program reading the file programmatically
  before that happens. `WriteResult.recalculation_required` is `True`
  whenever the source had formulas, and `WorkbookIndex.has_cached_values`
  tells a reader up front whether a file has ever been through a calculating
  application — `False` on a formula-heavy workbook means every value it
  reports is `None`, which is a very different fact than "the data is empty".
- **Parts openpyxl does not model are deleted on save.** Threaded comments,
  pivot caches, slicers, form controls, and custom XML all disappear from a
  load→save with no warning. `.xlsm`/`.xltm` macros are the one exception —
  they are opened with `keep_vba=True` and do survive.

`rp-xlsx fidelity FILE` reports both, before any write is attempted. Every
edit against an *existing* workbook checks it first:

- Nothing at risk → the edit proceeds normally.
- Something at risk → the command fails with exit code **3** naming what would
  be dropped, and the hint points at `--allow-lossy`.
- `--allow-lossy` → the edit proceeds anyway, and `WriteResult.dropped` says
  what was lost. **The flag never makes the loss silent** — it opts into the
  loss, it does not hide it.

`--allow-lossy` also appears on `create` and `template`, because each can
open an existing workbook too: `create --template FILE` opens and re-saves
the template before writing the new sheets into it, and `template` always
opens the template it fills. A template-less `create` opens nothing
existing, so the flag is a no-op there — there is nothing at risk to opt
into — but the command still accepts it rather than refusing it
conditionally on whether `--template` was also given.

Classic per-cell comments are read normally by `comments`. **Threaded
comments are not read at all** — openpyxl only models classic comments, so a
workbook carrying threaded ones reports them nowhere in `comments`, but
`fidelity`/`index` still flag them as at-risk so an edit does not delete them
silently.

## Templates

House templates are the normal path. `create` and `template` resolve a name
against `RP_XLSX_TEMPLATE_DIR`, then `templates/local/`, then `templates/`,
trying `.xltx` before `.xltm` before `.xlsx`. `RP_XLSX_TEMPLATE` names the
default.

```sh
rp-xlsx templates list
rp-xlsx templates inspect house
rp-xlsx templates manifest house.xltx -o tests/fixtures/house.manifest.json
rp-xlsx templates synthesize house.manifest.json -o rebuilt.xltx
```

A **manifest** describes a template's shape — sheet names and order, header
rows, per-column number formats (where a column is uniform), frozen panes,
defined names, table names and refs, placeholder cells, and whether an image
is present — and is redacted by construction: no body cell value, no image
bytes, no author names, no path beyond the basename. That is what makes it
safe to commit, so CI can exercise a confidential template's shape via
`synthesize` without the file ever leaving the machine that holds it.

`synthesize()` reproduces structure, not appearance: it does not reproduce
themes, fonts, colours, conditional formatting, or data validation. It exists
to test template resolution and placeholder filling, not to stand in for the
real file visually.

`template` fills a workbook's `{{ placeholder }}` and `{{ client.name }}`
cells from a JSON context — no expression evaluation, no loops or
conditionals; generate rows with `create`/`append` for repeated data instead.
`--strict` (the default) fails on an unresolved placeholder; `--no-strict`
leaves it in place and reports it in `FillResult.unresolved`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | user or input error — bad path, bad sheet spec, unknown template, missing `-o` |
| 2 | a required external binary is missing |
| 3 | the file is corrupt, uses something unsupported, or an edit would drop at-risk parts without `--allow-lossy` |

Errors go to stderr as an `ErrorEnvelope`; results go to stdout. Both are
JSON, and the envelope shape is the same across every tool in the suite.

## Converting and rendering

```sh
rp-xlsx convert report.xlsx --to pdf -o report.pdf   # also: csv, ods, html
rp-xlsx render  report.xlsx -o ./pages --dpi 150
```

These need LibreOffice (and poppler for rendering); `rp-xlsx doctor` reports
what is installed. Nothing else in this package needs an external binary —
reading, creating, editing, templating, and sheet operations all work without
one. Page count for `render` is a property of the file's print settings, not
of its data — LibreOffice paginates a sheet according to its print area and
page setup.

They are also the only two commands here that can take long enough for
silence to be ambiguous, so they take `--describe` (what the run will do,
before it starts) and `--progress` (a live line with an elapsed clock while it
runs), both on stderr and on by default only when stderr is a terminal;
`--describe`/`--progress` force them on and `--no-describe`/`--no-progress`
off.
