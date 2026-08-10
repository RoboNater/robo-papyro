---
name: spreadsheet-toolkit
description: Read, create, and edit Excel workbooks from the shell with rp-xlsx — sheet data and formulas, cells, Excel tables, defined names, comments, images, charts, properties, Markdown conversion, CSV/JSON/Markdown import, building workbooks on house templates, filling {{ placeholder }} templates, and adding, deleting, renaming, or reordering sheets. Use whenever a task involves a .xlsx, .xlsm, .xltx, or .xltm file, or asks for a spreadsheet or workbook.
---

# Excel workbooks with `rp-xlsx`

`rp-xlsx` reads, creates, and edits `.xlsx`, `.xlsm`, `.xltx`, and `.xltm`
files. Read commands print JSON to stdout, so you can parse the result
instead of scraping text.

Check it is installed: `rp-xlsx --help` (or `rp xlsx --help`).

## Start here

```sh
rp-xlsx index FILE.xlsx
```

Sheet names and counts, formula and defined-name counts, and which parts
would be at risk if you edited the file. The cheapest first call on an
unfamiliar workbook.

## Reading

| Command | What you get |
|---|---|
| `rp-xlsx index FILE` | Sheets, formula count, defined names, at-risk parts |
| `rp-xlsx data FILE [--sheets SPEC] [--format csv\|md -o DIR]` | Values as a grid — never display strings |
| `rp-xlsx cells FILE [--cells A1:D20]` | Every cell, with formula and cached value |
| `rp-xlsx formulas FILE` | Only the formula cells |
| `rp-xlsx tables FILE` | Excel table objects (ListObjects) |
| `rp-xlsx names FILE` | Defined names, workbook- and sheet-scoped |
| `rp-xlsx comments FILE` | Classic comments — see the warning below |
| `rp-xlsx images FILE [--out DIR]` | Image metadata; extracts with `--out` |
| `rp-xlsx charts FILE` | Chart types and series references |
| `rp-xlsx props FILE` | Title, author, dates, keywords |
| `rp-xlsx markdown FILE` | The workbook as Markdown, a heading and table per sheet |
| `rp-xlsx fidelity FILE` | What editing this file would cost, without editing it |

## Writing

**Never edit an input in place unless you were asked to.** Every editing
command takes `-o OUT.xlsx`.

```sh
rp-xlsx create -o report.xlsx --from-csv data.csv --template house
rp-xlsx set report.xlsx --map '{"Sheet1": {"B2": 5}}' -o edited.xlsx
rp-xlsx append report.xlsx --sheet Data --rows '[[1, 2]]' -o bigger.xlsx
rp-xlsx replace report.xlsx --map '{"Q3":"Q4"}' -o fixed.xlsx
rp-xlsx template house --context ctx.json -o pitch.xlsx   # strict by default
rp-xlsx sheets reorder report.xlsx --order 3,1,2 -o reordered.xlsx
rp-xlsx sheets delete report.xlsx --sheet Old -o trimmed.xlsx
```

Setting core properties has **no CLI command** — it is library-only
(`rp_xlsx.set_properties`), or the `xlsx_set_properties` MCP tool. `rp-xlsx
props FILE` reads them.

`create` can also build sheets from `--from-json` (an array of
`{"name", "header"?, "rows"}` objects) or `--from-markdown` (every pipe table
becomes a sheet). A value beginning with `=` in `set` is always a formula,
never literal text.

## Things that will bite you

**Every write drops every formula's cached value.** openpyxl (the library
underneath) does not round-trip a workbook: saving a file — even to change
one unrelated cell — discards the last-computed value of every formula in
it, and it stays gone until a real spreadsheet application recalculates.
`rp-xlsx` forces Excel/LibreOffice to recompute on next open, but a
subsequent `rp-xlsx` read before that happens sees `None` for every
formula. `WorkbookIndex.has_cached_values` (in `index`'s output) tells you
up front whether a file has ever been through a calculating application —
`false` means every formula value it reports is `None`, which is a very
different fact than "the data is empty".

**An edit can be refused for fidelity, not just for a bad argument.** Some
parts (threaded comments, pivot caches, slicers, form controls, custom XML)
are silently deleted by any write. `rp-xlsx` checks for them before editing
an existing workbook and, if present, fails with **exit 3** rather than
dropping them quietly. Run `rp-xlsx fidelity FILE` first if you want to know
before you try; pass `--allow-lossy` to proceed anyway — it does not hide
the loss, it opts into it, and reports what was dropped.

**`comments` never sees threaded comments.** That part is not readable at
all — openpyxl only models classic comments — so a workbook with only
threaded comments reports an empty list from `comments`. **Do not report "no
comments"** on such a workbook; check `fidelity`/`index` for at-risk parts
instead. Classic comments are read normally.

**`--sheets` is position, not name — and a workbook can have a sheet
literally named `"2"`.** `--sheets 2` selects the second sheet by position,
which is not the same as a sheet named `"2"`. Use `--sheet NAME` (repeatable)
to select by name instead.

**Values are not display strings.** A cell showing `25.00%` has value `0.25`;
`cells` reports `number_format` alongside it for anyone who needs to
reproduce the display string. Dates always come back as full ISO-8601
datetimes, even for a date-only cell.

**A sheet's declared dimensions can lie.** A stray formatted cell far below
the real data inflates the sheet's reported size; every read that returns
rows uses the *used* range instead, so `data` never hands back hundreds of
rows of nulls.

**`.xltx`/`.xltm` work everywhere `.xlsx`/`.xlsm` do**, and `.xlsm`/`.xltm`
need a macro source — `create` refuses to write a macro-free file under a
macro-enabled extension.

## Reading the outcome

JSON on stdout. Errors on **stderr**, human message first and a JSON envelope
as the last line:

```json
{"error": {"type": "LossyEditError", "message": "…", "hint": "--allow-lossy", "exit_code": 3}}
```

| Exit | Meaning | What to do |
|---|---|---|
| 1 | Bad arguments — missing file, unknown template, bad sheet spec | Fix the call |
| 2 | A required external program is missing | `rp-xlsx doctor` |
| 3 | Corrupt, not a workbook, or an edit would drop at-risk parts | Report it, or retry with `--allow-lossy` if that is acceptable |

Reading and writing need **no external program**. Only `convert` and `render`
need LibreOffice.

## As a library

```python
from pathlib import Path
from rp_xlsx import get_index, get_data, create, set_cells, reorder_sheets

index = get_index(Path("report.xlsx"))
create(Path("out.xlsx"), sheets=None, template="house")
reorder_sheets(Path("report.xlsx"), [3, 1, 2], output=Path("out.xlsx"))
```

Full guide: `docs/usage-xlsx.md` in the robo-papyro checkout.
