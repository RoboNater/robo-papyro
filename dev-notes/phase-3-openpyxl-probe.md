# openpyxl 3.1.5 — what was verified before `rp-xlsx-spec.md` was written

Phase 1 and Phase 2.5 both lost time to a library behaviour the spec had
guessed at (`python-docx` refusing `.dotx`; `shape.shape_type` raising). This
note is the counter-measure: every load-bearing claim in
[`docs/specs/rp-xlsx-spec.md`](../docs/specs/rp-xlsx-spec.md) about what
openpyxl does was run first, against **openpyxl 3.1.5** on CPython 3.11, and
the output is recorded here.

Reproduce it in a throwaway environment — openpyxl is not yet a workspace
dependency, and this note must not become a reason to add one early:

```sh
uv venv /tmp/probe && uv pip install --python /tmp/probe/bin/python openpyxl pillow
/tmp/probe/bin/python probe.py     # the script below
```

---

## 1. A load→save destroys every cached formula value

The most important finding in this document, because it is silent.

A formula cell in a real (Excel-written) workbook carries both the formula and
the value Excel last computed: `<f>SUM(A1:A2)</f><v>3</v>`. `data_only=True`
reads that `<v>`. openpyxl's writer emits the `<f>` and **drops the `<v>`**.

```
cached value read with data_only:                     3
edited sheet still carries a cached <v> for A3:       False
data_only read of the edited file:                    None
```

So: read a workbook, change one unrelated cell, save it, and every formula in
the file now reads as `None` to any programmatic consumer — including
`rp-xlsx` itself — until Excel or LibreOffice opens it and recalculates.
Nothing warns. This is what §6 of the spec is built around, and it is why
`fullCalcOnLoad` (below) is set on every write rather than offered as an
option.

A workbook openpyxl authored has no cached values at all, which is the same
observation from the other end:

```
formula cell (default):                               '=SUM(B2:B4)'  (data_type 'f')
formula cell (data_only) on an openpyxl-written file: None
```

**Consequence for the API:** formula and cached value cannot be obtained from
one `load_workbook` call. Reporting both means loading twice and merging.

## 2. `fullCalcOnLoad` is available and round-trips

The mitigation for finding 1 works:

```
calcPr in workbook.xml:        True
fullCalcOnLoad survives load:  True
```

`wb.calculation.fullCalcOnLoad = True` writes `<calcPr fullCalcOnLoad="1"/>`,
which makes Excel and LibreOffice recompute on open. It does nothing for a
programmatic reader, which is why it is a mitigation and not a fix.

## 3. Parts openpyxl does not model are dropped, silently

Six representative parts were injected into a workbook zip and the file was
loaded and saved:

```
foreign parts lost on load->save:
  ['customXml/item1.xml', 'xl/ctrlProps/ctrlProp1.xml', 'xl/persons/person.xml',
   'xl/pivotCache/pivotCacheDefinition1.xml', 'xl/slicers/slicer1.xml',
   'xl/threadedComments/threadedComment1.xml']
```

Threaded comments, pivot caches, slicers, form controls, and custom XML all
vanish with no error and no warning. The list is representative, not
exhaustive — the rule is "whatever openpyxl does not model", and the guard in
§6 is written against part presence rather than against this list.

## 4. Charts and images *do* survive — the widely-quoted limitation is stale

openpyxl's own documentation still says charts and images are lost on a
round trip. For 3.1.5 and openpyxl-authored content, that is no longer true:

```
authored image parts:        ['xl/drawings/...', 'xl/media/image1.png']
after round trip:            ['xl/drawings/...', 'xl/media/image1.png']
images seen on reload:       1
charts after rt:             1
```

Also surviving a round trip: merged ranges, conditional formatting, data
validation, defined names, Excel tables (`ListObject`), classic comments, cell
fonts and fills, freeze panes, autofilter, and sheet visibility state.

This is **not** licence to assume Excel-authored charts survive equally well —
these were shapes openpyxl itself wrote, so openpyxl's model was complete by
construction. §12 step 5 re-runs the check against a real Excel-authored
workbook if one can be obtained, and the guard does not depend on the answer.

## 5. `.xlsm` macros need `keep_vba=True`, and the default is `False`

```
keep_vba=False: vbaProject survives:  False
keep_vba=True:  vbaProject survives:  True
```

An `.xlsm` opened with defaults and saved is an `.xlsm` with no macros. The
spec makes `keep_vba=True` unconditional for macro-enabled formats rather than
an option, because there is no reading of "edit this workbook" that means
"delete its code".

Note also that `Workbook().save("x.xlsm")` writes a file whose content type is
**not** macro-enabled:

```
openpyxl-written .xlsm content type is macroEnabled:  False
```

## 6. Templates: openpyxl opens `.xltx`, and mis-types on the way out

The `.dotx`/`.potx` finding repeats, but inverted — the problem is the write
side, not the read side:

```
xltx content type written:                              True
load_workbook('.xltx') ok; wb.template =                True
resaved .xltx keeps template content type:              True
saving a template-loaded wb as .xlsx writes template CT: True   # <-- wrong
```

So `load_workbook` handles templates fine (unlike python-docx and python-pptx),
but `wb.template` is sticky: save a template-derived workbook under an `.xlsx`
name and it is still typed as a template. Excel opens such a file read-only-ish,
as a template instance. Retyping is therefore driven by the **output
extension**, in `save()`, exactly where `rp-docx` and `rp-pptx` do it.

`SUPPORTED_FORMATS` is `('.xlsx', '.xlsm', '.xltx', '.xltm')`.

## 7. How openpyxl rejects what it cannot read

```
x.xls    -> InvalidFileException  "openpyxl does not support the old .xls file format…"
x.xlsb   -> InvalidFileException  "openpyxl does not support binary format .xlsb…"
x.txt    -> InvalidFileException  "openpyxl does not support .txt file format…"
bad.xlsx -> BadZipFile            "File is not a zip file"
```

Two things follow. The extension check happens **before** the content check —
a perfectly good `.xlsx` renamed to `.xls` is refused on its name alone. And
`BadZipFile` is a `zipfile` exception, not an openpyxl one, so both have to be
caught and mapped (§2 of the spec: nothing raises a bare builtin).

## 8. Dimensions lie, and `read_only` does not help

One value in `A1`, one *format-only* cell at `E1000`:

```
max_row/max_col:        1000 5      dims: A1:E1000
read_only max_row:      1000
```

`ws.max_row` is the extent of anything the sheet mentions, formatting included.
An agent asking for "the data" must not be handed 1000 rows of `None`.

## 9. Smaller verified facts

```
merged origin: 'merged'   spanned: None (type MergedCell)
dates:  value=datetime.datetime(2024,5,1,12,30) data_type='d' fmt='yyyy-mm-dd h:mm:ss' is_date=True
        a date-only cell also comes back as datetime, at midnight
percent: value=0.25 data_type='n' fmt='0.00%'   -> the display string is not the value
sheet title > 31 chars:  accepted, UserWarning only
sheet title with '[':    ValueError("Invalid character [ found in sheet title")
write_only workbook:     supported
iter_rows(values_only=True) yields plain tuples
```

`et_xmlfile` (MIT) is openpyxl's only runtime dependency.

---

## The probe, reduced to the four findings that drive the design

Paste into the throwaway environment above. Everything else in this note is a
one-liner against the same objects.

```python
import zipfile
from pathlib import Path

import openpyxl

out = Path("probe"); out.mkdir(exist_ok=True)
parts = lambda p: sorted(zipfile.ZipFile(p).namelist())

# --- build a workbook with a formula, then inject the cached <v> Excel writes
wb = openpyxl.Workbook(); ws = wb.active
ws["A1"], ws["A2"], ws["A3"] = 1, 2, "=SUM(A1:A2)"
wb.save(out / "src.xlsx")
with zipfile.ZipFile(out / "src.xlsx") as zin, \
     zipfile.ZipFile(out / "excel-like.xlsx", "w") as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "xl/worksheets/sheet1.xml":
            data = data.replace(b"<f>SUM(A1:A2)</f>", b"<f>SUM(A1:A2)</f><v>3</v>")
        zout.writestr(item, data)

# 1. the cached value is readable, and an edit destroys it
print(openpyxl.load_workbook(out / "excel-like.xlsx", data_only=True)["Sheet"]["A3"].value)   # 3
e = openpyxl.load_workbook(out / "excel-like.xlsx"); e["Sheet"]["A1"] = 5
e.save(out / "edited.xlsx")
print(openpyxl.load_workbook(out / "edited.xlsx", data_only=True)["Sheet"]["A3"].value)       # None

# 2. fullCalcOnLoad is the mitigation, and it round-trips
e.calculation.fullCalcOnLoad = True; e.save(out / "calc.xlsx")
print(openpyxl.load_workbook(out / "calc.xlsx").calculation.fullCalcOnLoad)                   # True

# 3. unmodelled parts disappear
with zipfile.ZipFile(out / "src.xlsx") as zin, \
     zipfile.ZipFile(out / "foreign.xlsx", "w") as zout:
    for item in zin.infolist():
        zout.writestr(item, zin.read(item.filename))
    zout.writestr("xl/threadedComments/threadedComment1.xml", b"<threadedComments/>")
    zout.writestr("xl/pivotCache/pivotCacheDefinition1.xml", b"<pivotCacheDefinition/>")
openpyxl.load_workbook(out / "foreign.xlsx").save(out / "foreign-rt.xlsx")
print(sorted(set(parts(out / "foreign.xlsx")) - set(parts(out / "foreign-rt.xlsx"))))

# 4. a template stays a template unless the writer retypes it
t = openpyxl.Workbook(); t.template = True; t.save(out / "t.xltx")
openpyxl.load_workbook(out / "t.xltx").save(out / "from-t.xlsx")
print(b"template.main+xml" in zipfile.ZipFile(out / "from-t.xlsx").read("[Content_Types].xml"))
```

The script is deliberately not committed as a test: it exercises a library the
workspace does not yet depend on. Once `rp-xlsx` exists, every claim here that
still constrains behaviour becomes an assertion in
`packages/rp-xlsx/tests/`, per §11 of the spec — a note is a record, and a
record does not fail when reality moves.
