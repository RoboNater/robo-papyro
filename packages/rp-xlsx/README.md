# rp-xlsx

Spreadsheet reading, authoring, and templating for the
[robo-papyro](../../README.md) suite.

JSON-first: every structured read command (`index`, `data`, `cells`,
`formulas`, `tables`, `names`, `comments`, `images`, `charts`, `props`,
`fidelity`) emits a complete pydantic model, so a tool with no native
spreadsheet capability can operate on `.xlsx`, `.xlsm`, `.xltx`, and `.xltm`
files through a plain CLI. `create` and `render` write files to disk and
report JSON metadata about them the same way. `markdown` is the actual
exception: with no `-o` it prints Markdown itself; given `-o` it writes the
file and reports a JSON `WriteResult` instead. Reachable as both `rp-xlsx` and
`rp xlsx`.

```sh
uv run rp-xlsx index workbook.xlsx
uv run rp-xlsx data workbook.xlsx --sheets 1 --max-rows 20
uv run rp-xlsx set workbook.xlsx --map '{"Sheet1": {"B2": 5}}' -o out.xlsx
```

**openpyxl does not round-trip a workbook.** A load→save silently discards
every formula's cached value and any package part openpyxl does not model
(threaded comments, pivot caches, slicers, form controls, custom XML). Every
write path scans the file first and refuses with exit code 3
(`LossyEditError`) rather than deleting what it cannot represent;
`--allow-lossy` proceeds while still reporting what went. `rp-xlsx fidelity
FILE` answers "what would editing this cost?" without attempting the edit.
See [docs/usage-xlsx.md](../../docs/usage-xlsx.md) for the full explanation.

No external binary is needed to read, create, edit, or restructure a
workbook. LibreOffice is required only for `convert` and `render`; `rp-xlsx
doctor` reports what is installed.

Full guide: [docs/usage-xlsx.md](../../docs/usage-xlsx.md).
Specification: [docs/specs/rp-xlsx-spec.md](../../docs/specs/rp-xlsx-spec.md).
