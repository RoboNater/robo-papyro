# Templates

House `.dotx`/`.docx` (Word, resolved by `rp-docx`), `.potx`/`.pptx`
(PowerPoint, resolved by `rp-pptx`), and `.xltx`/`.xltm`/`.xlsx` (Excel,
resolved by `rp-xlsx`) style templates.

**This directory is empty on purpose, and CI never needs anything in it.**
Phase 1 (`rp-docx`), Phase 2.5 (`rp-pptx`), and Phase 3 (`rp-xlsx`) were all
built and tested without a single real template — see §11.1 of
[`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md), §11.1 of
[`rp-pptx-spec.md`](../docs/specs/rp-pptx-spec.md), and §11.2 of
[`rp-xlsx-spec.md`](../docs/specs/rp-xlsx-spec.md). Everything below is for
working with real templates once there are some.

## How resolution works

All three packages resolve a bare template name against a list of
directories, tried in order, then fall back to a configured default (and, for
`rp-docx`/`rp-pptx`, the upstream library's own bundled default — `rp-xlsx`
has none, see below) — but the implementations currently differ in two ways
worth knowing before you rely on one: how many directories the
`_TEMPLATE_DIR` variable can name, and how the in-checkout directories are
located.

| | `rp-docx` (`rp_docx.templates.template_dirs`) | `rp-pptx` (`rp_pptx.templates._roots`) | `rp-xlsx` (`rp_xlsx.templates.template_dirs`) |
|---|---|---|---|
| Directory env var | `RP_DOCX_TEMPLATE_DIR` | `RP_PPTX_TEMPLATE_DIR` | `RP_XLSX_TEMPLATE_DIR` |
| `_TEMPLATE_DIR` accepts | **Multiple** directories, split on `os.pathsep` (`PATH`-style) | **One** directory only — the whole value is wrapped in a single `Path` | **Multiple** directories, split on `os.pathsep`, matching `rp-docx` |
| In-checkout directories | The nearest ancestor of the current working directory that has a `templates/` next to a `.git` or `pyproject.toml` (walks up from `cwd`) | `Path.cwd() / "templates"` directly — no ancestor search | Same ancestor search as `rp-docx` |
| Default-template env var | `RP_DOCX_TEMPLATE` | `RP_PPTX_TEMPLATE` | `RP_XLSX_TEMPLATE` |
| Extensions tried, in order | `.dotx` then `.docx` | `.potx` then `.pptx` | `.xltx` then `.xltm` then `.xlsx` |
| Map file | `<name>.stylemap.json` | `<name>.layoutmap.json` | none — cell text is a single string, so substitution needs no run-splitting map |
| With no template named at all | Falls back to `$RP_DOCX_TEMPLATE`, then python-docx's bundled default | Falls back to `$RP_PPTX_TEMPLATE`, then python-pptx's bundled default | Falls back to `$RP_XLSX_TEMPLATE`, then `None` (a blank `openpyxl.Workbook()`) — deliberate: openpyxl has no bundled default to fall back to |

`rp-xlsx` deliberately matches `rp-docx`'s shape rather than `rp-pptx`'s.
`RP_PPTX_TEMPLATE_DIR` naming more than one directory (the `PATH`-separated
form that works for `RP_DOCX_TEMPLATE_DIR` and `RP_XLSX_TEMPLATE_DIR`)
silently resolves to a single, likely-wrong path instead of erroring, and
`rp-pptx` only finds `templates/local/`/`templates/` when run from the
checkout root — `rp-docx` and `rp-xlsx` find them from any subdirectory.
Running any of the three CLIs from the repository root, as the examples below
do, sidesteps the difference. If you rely on multiple template directories or
run `rp-pptx` from a subdirectory, treat that as a known implementation gap
rather than a documented feature.

All three packages try, in order:

1. `$RP_DOCX_TEMPLATE_DIR` / `$RP_PPTX_TEMPLATE_DIR` / `$RP_XLSX_TEMPLATE_DIR`,
   per the table above
2. `templates/local/`
3. `templates/` (this directory)

so `--template memo` finds `memo.dotx` here, `--template house` finds
`house.potx`, and `--template quarterly` finds `quarterly.xltx`.

An explicit path that does not exist is always an error naming *that path* —
never mistaken for an unresolvable bare name. This matters because the two
failures should not read alike: a typo'd path and a typo'd template name
point the user in different directions.

`templates/local/` comes first among the two in-checkout directories because
it is the **gitignored drop point for real templates** during manual work:
when a name exists in both, the real one is the one meant. Nothing there is
ever required for CI.

## Word style maps

An optional `<name>.stylemap.json` sits beside each `.dotx`/`.docx` template
and maps logical roles to that template's real style names:

```json
{"h1": "House Heading 1", "h2": "House Heading 2", "body": "RP Body Text",
 "bullet": "House Bullet", "numbered": "House Number", "table": "Table Grid"}
```

`rp-docx templates stylemap FILE` scaffolds one to correct by hand. A mapped
style that the template does not define is an **error**, never a silent
fallback — see [`docs/usage-docx.md`](../docs/usage-docx.md#templates).

## PowerPoint layout maps

An optional `<name>.layoutmap.json` sits beside each `.potx`/`.pptx` template
and maps Markdown-conversion roles to that template's real layout names:

```json
{"title": "RP Title", "section": "House Section Break",
 "content": "House Content", "blank": "House Blank"}
```

`rp-pptx templates layoutmap FILE` scaffolds one to correct by hand. A mapped
layout the template does not define is an **error**, never a silent fallback
— see [`docs/usage-pptx.md`](../docs/usage-pptx.md#templates). Checking is
lazy, exactly as with Word style maps: a deck with no section breaks does not
need a section layout to exist.

## Excel placeholder templates

No map file exists for `.xltx`/`.xltm`, and none is needed: a workbook cell's
text is a single string (there is no run-splitting the way Word/PowerPoint
text can be split across runs), so `{{ placeholder }}` substitution is a
direct `str.replace`. `rp-xlsx template FILE --context ctx.json -o out.xlsx`
fills a resolved template's placeholder cells; `rp-xlsx templates inspect
FILE` lists what it found. See
[`docs/usage-xlsx.md`](../docs/usage-xlsx.md#templates).

## What may be committed here

**A template, only if it is ours to redistribute.** A downloaded or corporate
`.dotx`/`.potx`/`.xltx` in git is a licensing question, an opaque diff, and a
debugging hazard at once. Anything added here must be recorded in the table
below; a template with no owner and no canonical location is a liability,
because a stale letterhead is worse than a missing one.

| Template | Format | Owner | Canonical source | Last synced |
|---|---|---|---|---|
| _(none yet)_ | | | | |

**A manifest, always.** `rp-docx templates manifest FILE`, `rp-pptx templates
manifest FILE`, and `rp-xlsx templates manifest FILE` each emit a JSON
description of a template's *shape* — style/layout/sheet names, geometry,
presence flags — carrying **no document/slide/cell text beyond a header row
and declared placeholder cells, no image bytes, no author names, and no path
beyond the template's own basename**. That is a correctness property enforced
by a test in each package, not a convention. Manifests belong in
`packages/rp-docx/tests/fixtures/*.manifest.json`,
`packages/rp-pptx/tests/fixtures/*.manifest.json`, and
`packages/rp-xlsx/tests/fixtures/*.manifest.json`, where each package's
`templates synthesize` rebuilds a structurally equivalent template from them
at test time. It is what lets CI regression-test a confidential template's
shape while the template stays on the machine that holds it. `rp-xlsx`'s
`synthesize` reproduces structure only — themes, fonts, colours, conditional
formatting, and data validation are out of scope, a wider gap than the other
two formats' synthesis leaves, and `docs/usage-xlsx.md` says so.

## Validating against a real template

Word, PowerPoint, and Excel each have their own manual pass, run separately —
[`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §13,
[`rp-pptx-spec.md`](../docs/specs/rp-pptx-spec.md) §13, and
[`rp-xlsx-spec.md`](../docs/specs/rp-xlsx-spec.md) §13:

### Word (`.dotx`)

```sh
cp /path/to/house.dotx templates/local/
uv run rp-docx templates inspect house              # is the style list right?
uv run rp-docx templates stylemap house -o templates/local/house.stylemap.json
$EDITOR templates/local/house.stylemap.json         # the scaffold is a guess
uv run rp-docx create -o out.docx --from-markdown notes.md --template house
# open out.docx in Word and confirm the house styles applied
uv run rp-docx templates manifest templates/local/house.dotx \
    -o packages/rp-docx/tests/fixtures/house.manifest.json
```

### PowerPoint (`.potx`)

```sh
cp /path/to/house.potx templates/local/
uv run rp-pptx templates inspect house               # are layouts/placeholders right?
uv run rp-pptx templates layoutmap house -o templates/local/house.layoutmap.json
$EDITOR templates/local/house.layoutmap.json         # the scaffold is a guess
uv run rp-pptx create -o out.pptx --from-markdown notes.md --template house
# open out.pptx in PowerPoint and confirm the house layouts applied
uv run rp-pptx templates manifest templates/local/house.potx \
    -o packages/rp-pptx/tests/fixtures/house.manifest.json
```

### Excel (`.xltx`)

```sh
cp /path/to/house.xltx templates/local/
uv run rp-xlsx templates inspect house               # are sheets/placeholders right?
uv run rp-xlsx template house --context ctx.json -o out.xlsx
# open out.xlsx in Excel or LibreOffice and confirm the placeholders filled
uv run rp-xlsx templates manifest templates/local/house.xltx \
    -o packages/rp-xlsx/tests/fixtures/house.manifest.json
```

No layout- or style-map step: `rp-xlsx` has no map file to scaffold (see
"Excel placeholder templates" above).

In all three cases, only the last step produces a repository artifact, and it
carries nothing confidential by construction. Everything found in the earlier
steps comes back as a defect report or a spec correction, not as a file.

## Open decision

`robo-papyro-spec.md` §11.1 is unresolved: if the source of truth for these
files is SharePoint, decide whether this directory holds a synced copy or a
pointer to it. Resolve before the first template lands. The manifest loop
above lowers the stakes for all three formats — CI depends on manifests rather
than on the templates themselves — but it does not answer the question.
