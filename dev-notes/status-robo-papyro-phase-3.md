# Status — robo-papyro Phase 3 (`rp-xlsx`)

Written against `docs/specs/rp-xlsx-spec.md` v1.0, in the pattern of
`status-robo-papyro-phase-1.md` and `status-robo-papyro-phase-2.5.md`: what
landed, and every place §4–§9 turned out to be wrong or incomplete in
practice.

## BLUF

**Phase 3 is complete.** `rp-xlsx` ships as an independently versioned
distribution reachable as both `rp-xlsx` and `rp xlsx`. It reads workbooks
(index, data, cells, formulas, tables, names, comments, images, charts,
properties, markdown, fidelity), creates and edits them from CSV/JSON/Markdown
and cell-level edits, fills `{{ placeholder }}` templates, and adds, deletes,
renames, and reorders sheets. `rp-mcp` gained an `xlsx.py` tool surface
alongside it, following the same read-always/write-behind-a-write-root shape
as the other three, plus an `xlsx-toolkit` skill. openpyxl does the ordinary
work; LibreOffice is optional and subprocess-only, needed only for `convert`
and `render`.

**§5's documented fallback was not needed.** The spec said: if step 8 (the
templates checkpoint) fights back, ship `list_templates`/`resolve_template`/
`inspect_template`/`fill_template` and defer `build_manifest`/`synthesize`.
The full manifest/synthesis round trip worked, with two real bugs found and
fixed along the way (finding 5 below) — nothing was deferred.

**§6 — the fidelity guard — is the centre of this package, exactly as
specified**, and both of its verified losses (dropped cached formula values,
silently deleted at-risk parts) held against openpyxl 3.1.5 with no surprises
beyond the ones below. The guard, `--allow-lossy`, and `WriteResult.dropped`
all work as designed on the first real workbook this package touched — a
synthetic one, since no real workbook was available (see "Known limits").

### Verification

- `uv run pytest`: **1704 passed, 9 skipped** across the whole workspace (up
  from 1309 before Phase 3 started); of those, 359 are `rp-xlsx` tests and 24
  more are the new `packages/rp-mcp/tests/test_xlsx_server.py`. The 9 skips
  are LibreOffice- and poppler-dependent tests across all packages, skipped by
  functional probe (see "Known limits" — same story as Phase 2.5).
- Coverage on `rp-xlsx`: **95% overall**. §12's definition of done targets
  >85% on `xlsx/`, `ooxml.py`, `fidelity.py`, `refs.py`, and `templates.py`:
  `ooxml.py` 95%, `fidelity.py` 98%, `refs.py` 97%, `templates.py` 97%,
  `xlsx/read.py` 92%, `xlsx/write.py` 98%, `xlsx/sheets.py` 100%,
  `xlsx/tabular.py` 99%, `xlsx/template.py` 100%. `cli.py` is 90%. `models.py`
  and `errors.py` are 100%.
- `rp-mcp`'s new `xlsx.py` tool module: **98%** (two unreached lines are both
  the tail end of a `guarded` decorator's error branch, exercised indirectly
  through the leaf's own tests, not through this module).
- `ruff check` and `ruff format --check` clean across the workspace.
- Nothing binary is committed. Every fixture is generated in `conftest.py`,
  including hand-crafted XML injection via zip repacking for structures
  openpyxl itself cannot create (cached formula values, at-risk parts,
  macros) — the same doctrine `rp-docx`/`rp-pptx` use.
- CI: `rp-xlsx` added to the per-package test matrix, plus xlsx equivalents of
  the umbrella-identity, no-LibreOffice-round-trip, exit-code-taxonomy
  (including `LossyEditError`'s 3, exercised against a workbook with an
  injected `xl/threadedComments/` part), and MCP-surface smokes. All verified
  locally, command by command, before being committed to the workflow.
- License gate: `et-xmlfile` (MIT) allowlisted — openpyxl's only runtime
  dependency, which `openpyxl` itself was approved without.
- Both `rp-xlsx` and `rp xlsx` produce byte-identical JSON on the same input
  (asserted in `test_cli_xlsx.py::TestEntryPoints` and in CI). JSON is the
  default everywhere, `--plain` is the opt-out, there is no `--json` flag, and
  every `ErrorEnvelope` carries the right exit code including `LossyEditError`
  at 3 — all asserted by `test_invariants_xlsx.py`.

## Findings — where §4–§9 turned out to be wrong or incomplete

### 1. openpyxl writes an empty `<v/>` for a value-less formula (§6, new — not in the pre-spec probe note)

The probe note (`dev-notes/phase-3-openpyxl-probe.md`) verified that a save
*drops* a formula's cached value. What it did not check: a formula written by
this package (never opened by a real spreadsheet application, so it has no
cached value at all) still gets a `<v></v>` sibling — empty, not absent — next
to its `<f>`. Harmless to every consumer here (an empty `<v>` reads back as no
value, same as none at all), but worth recording because it means "does this
formula have a `<v>` element" is not the same question as "does this formula
have a value," and a raw-XML reader written against the wrong question would
get it wrong. Confirmed at the step 5 checkpoint; the other four probe
findings (cached-value discard, at-risk-part deletion, `.xltx` retyping
survives a rename, `keep_vba` default) all held exactly as written.

### 2. `ws.tables.items()` yields `(name, ref_string)`, not `(name, Table)` (§4)

The kind of openpyxl API shape that looks right on the first read and is
wrong: `Worksheet.tables` is a `TableList`, and its `.items()` — unlike a
dict's — yields the table's *range reference string* as the value, not the
`Table` object. `get_tables` needed `for name in ws.tables: table =
ws.tables[name]` instead. Left as an inline comment in `xlsx/read.py` rather
than only here, on the theory that the next reader of that exact line is more
likely to trust the code than a status note four files away.

### 3. `set_properties` crashes on a partial update, not a full one (§4)

`CoreProperties`' `created`/`modified` are non-nullable at openpyxl's
serialization layer, so the naive `for field, value in
properties.model_dump().items(): setattr(wb.properties, field, value)` — which
works when every field is given — crashes on save the moment a caller sets
only `author`, because the unset fields come through as `None` and get
assigned. Fixed by iterating `model_dump(exclude_none=True)` instead, matching
`rp-pptx`'s pattern (adapted for this package's field-name mapping, e.g.
`author` → `creator`). Would not have been caught by a fixture that always
supplies every field, which is exactly the kind of test AGENTS.md's "test the
behavior you want, not the behavior you wrote" warns about.

### 4. `ooxml.opened()` leaked its VBA archive handle (§5.3, §7)

A macro-enabled workbook opened with `keep_vba=True` carries a
`workbook.vba_archive` (its own open zip handle over the embedded VBA
project) alongside the workbook itself. The context manager's `finally`
block closed `workbook` but never `workbook.vba_archive`, which surfaced as a
`PytestUnraisableExceptionWarning` on garbage collection — quiet in a single
test run, and exactly the kind of leak that compounds in a long-lived process
like the MCP server. Fixed by closing `vba_archive` explicitly, before
`workbook.close()`, in the same `finally` block.

### 5. Two real bugs in `synthesize()`, found only by round-tripping it against its own manifest (§5.2)

The step 8 checkpoint's round trip is `build_manifest(template)` →
`synthesize(manifest)` → `build_manifest(synthesized)`, asserting the two
manifests match. Both of these were invisible from reading the code and only
showed up once that loop actually ran:

- **openpyxl does not round-trip an empty-string cell value.** Verified via
  raw XML inspection: it writes `<c t="inlineStr"></c>` with no `<is>` child,
  and reads back `None`, indistinguishable from a cell that was never
  written. A manifest's header row built from a *synthesized* file therefore
  disagreed with the manifest built from the original wherever the original
  had an empty header cell. Fixed two ways: `_cell_text()` normalizes a
  whitespace-only value to `""` on read so both sides agree, and the
  `house_like_template` fixture was redesigned to keep its header row itself
  gap-free (title-block placeholders moved below the table, in a dense
  column) rather than fight the openpyxl limitation.
- **A cell with only `.number_format` set, no `.value`, was invisible to the
  "is this column uniform" scan.** The scan skipped `cell.value is None`, so a
  column whose formatting existed without any value in that particular row
  never got picked up as uniform. Fixed by having `synthesize()` write a
  dummy value (`0`) alongside every reconstructed number format, so the
  reconstructed file's own re-scan finds what the original manifest recorded.

### 6. `fill_template`'s "unresolved" semantics were backwards on the first pass (§8)

Copied `rp-pptx`'s exact shape at first: compute `unresolved` from which
*context* keys matched nothing. That inverts the actual question. A
placeholder present in the template but entirely absent from the context
(`context={}` against a template with `{{ client.name }}`) came back
`unresolved: []` — reported as fully resolved, which is the one answer that
must never happen for a `strict=True` caller relying on that list. Fixed by
rewriting to `rp-docx`'s approach instead: call
`templates.find_placeholders(source)` first to get the template's actual
placeholder keys, then check which of *those* are absent from the flattened
context. Worth noting because the two sibling packages disagree here and
`rp-xlsx` deliberately followed the one that is actually correct, not the one
that was `git blame`-closer.

### 7. CSV numeric coercion needs one check, not two sequential ones (§9)

The first pass guarded `int()` against a leading zero (`_INT_RE`) but then
unconditionally tried `float()` as the fallback — and `float("007")` succeeds,
silently returning `7.0` and losing the leading zero anyway. `"1.5.0"` had the
same failure mode from the other direction. Fixed by replacing both attempts
with a single `_NUMBER_RE` checked once, before either conversion, so a value
that does not look like a clean number stays text through both paths rather
than through only one of them.

### 8. A missing return-type annotation silently dropped structured content over MCP (Phase 3 step 11, `rp-mcp`)

Not a leaf finding but caught while building `rp_mcp/xlsx.py`: `xlsx_data`
was written without a `-> list[SheetData]` return annotation (every sibling
tool has one), and the MCP SDK generates a tool's output schema from that
annotation. Without it, the call still succeeded and returned text content,
but `structured_content` came back `None` — invisible unless a test actually
asserts on the structured result rather than just the exit status. Fixed by
adding the annotation; `test_xlsx_server.py` asserts
`result.structured_content is not None` on every read tool for exactly this
reason (via the shared `Driver.structured` helper, which fails loudly rather
than silently comparing `None` to `None` — the same AGENTS.md shape this
project keeps re-learning).

### 9. Smaller corrections

- **A part's filename is not its sheet position**, confirmed rather than
  merely assumed: sheet order lives in `xl/workbook.xml`'s `<sheets>`,
  resolved through relationships to the actual part, exactly the `rp-pptx`
  `p:sldIdLst` trap in a different format. Binds `ooxml.py`/`fidelity.py`
  only — openpyxl's own object model gets this right everywhere else,
  including this package's own `reorder_sheets`/`delete_sheets`.
- **`_replace_in_text` needed the longest-match-first rule stated in §8**
  applied literally, not assumed from the sibling packages' run-splitting
  code — since cell text here is a single string, the three-step run-offset
  dance those two packages need was correctly *not* copied over, but the
  overlap rule under it still had to be, and it is easy to drop by accident
  when deleting the rest of the machinery around it.
- **`sheets delete` needed its own "leave at least one visible sheet" check**
  independent of `fidelity`'s guard — deleting every sheet is not a fidelity
  loss (nothing openpyxl fails to model), it is a workbook that cannot open,
  and the two checks fire for entirely different reasons.

## Known limits

- **Threaded comments are read nowhere.** openpyxl only models classic
  comments (§7's own statement, confirmed). A workbook with only threaded
  comments reports an empty list from `get_comments` — the one outcome
  `rp-pptx`'s §7 forbids for its own modern-comment case, but the right
  answer here for a different reason: unlike a modern PowerPoint deck, a
  workbook with threaded comments is still one whose *cells* read correctly,
  and refusing the whole read would cost far more than it protects. `at_risk`
  carries the rest, so an edit cannot delete them silently even though a read
  cannot show them.
- **No real house workbook was available**, so `templates/` gained no `.xltx`
  and the manifest/synthesis loop was validated only against the three
  synthetic fixtures (`minimal`, `house_like`, `hostile`) §11.2 asks for.
  Same position `rp-docx`/`rp-pptx` were in at their own Phase's end (see
  `rp-docx-spec.md` §13) — a manual validation pass against a real workbook
  is still open work, not blocking work.
- **A part-preserving writer remains out of scope** (§6.3, parent spec §11
  open decision 4). Merging openpyxl's rewritten output back over the
  original zip is the only route to a genuinely lossless edit of a workbook
  carrying pivot caches, slicers, or threaded comments, and it is out of
  scope for the reason §6.3 gives: relationship IDs, content-type overrides,
  and `calcChain.xml` all have to stay consistent with sheet XML openpyxl
  rewrote wholesale, and a half-correct merge produces a file Excel repairs
  on open — a corrupted workbook wearing a green test suite.
- **Formula evaluation stays out of scope in both directions** (§1
  non-goal). `rp-xlsx` reads a formula's text and whatever value was last
  cached; it never computes one, on the theory that a subtly wrong number is
  the worst output this suite could produce.
- **Chart creation stays out of scope** (§1 non-goal, explicit: openpyxl
  *can* author charts, this is a scope decision not a capability limit).
  Charts are read only, same position as `rp-pptx`.
- **LibreOffice tests skip on a functional probe**, not a presence check,
  same as the other two OOXML leaves and for the same reason: this
  container's `soffice` fails every conversion with "source file could not
  be loaded," so a presence check would produce confusing failures instead
  of a clean skip.

## What the next phase inherits

- `rp_core.ooxml` and `rp_core.markdown` needed no changes to serve a third
  OOXML format — `rp-xlsx` is the proof that the Phase 2.5 promotions were
  genuinely generic, not merely generic enough for two formats.
- `CoreProperties` is now `rp_core.models.CoreProperties`, promoted on the
  rule `rp-pptx-spec.md` §3 wrote for its own duplication ("if a third leaf
  needs it, promote it then"). `rp-docx` and `rp-pptx` re-export it from
  their own `models.py` for backward compatibility rather than requiring
  every caller to import from `rp_core` directly.
- `rp-mcp` now serves four formats from one server or four single-format
  ones, with `xlsx_*` the only tool family that exposes `allow_lossy` on
  every write tool that opens an existing file — the MCP-side answer to
  "there is no `--allow-lossy` retry over a tool call the way there is on a
  CLI," recorded so the next leaf that needs a similar override has a
  pattern to follow rather than inventing one.
- The suite's four leaves now cover PDF, Word, PowerPoint, and Excel — the
  document formats named in the original purpose statement are all shipped.
  Any further phase is either a quality-of-life pass across the four (the
  part-preserving-writer decision above, the real-template validation passes
  still open for `rp-docx`/`rp-pptx`/`rp-xlsx`) or a genuinely new format.

## Still open

1. A real house workbook to validate `templates inspect`/`fill_template`
   against, same shape as `rp-docx-spec.md` §13's still-open item.
2. A part-preserving workbook writer, if a real workbook demands a lossless
   edit of a file carrying pivot caches, slicers, or threaded comments
   (parent spec §11 open decision 4).
3. Threaded-comment *reading*, if an agent workflow needs to see them rather
   than merely be warned they exist (§7's stated future work).
