# Status — robo-papyro Phase 2.5 (`rp-pptx`)

Written against `docs/specs/rp-pptx-spec.md` v1.0, in the pattern of
`status-robo-papyro-phase-1.md`: what landed, and every place §5–§9 turned out
to be wrong or incomplete in practice.

## BLUF

**Phase 2.5 is complete.** `rp-pptx` ships as an independently versioned distribution reachable as both
`rp-pptx` and `rp pptx`. It reads decks (index, text, tables, images, notes,
classic comments, charts, properties, markdown), creates and edits them from
markdown, fills `{{ placeholder }}` templates, and deletes and reorders slides.
python-pptx does the ordinary work; LibreOffice is optional and subprocess-only.

**Both §12 step 2 promotions were taken rather than the documented fallback.**
`rp_core.markdown` now holds the block/inline parser rp-docx hand-rolled, and
`rp_core.ooxml` holds zip read/repack, content-type rewriting, and the
compiled-XPath helper. rp-docx was refactored onto both in the same change and
its 297 tests pass unchanged.

**One sub-scope is deferred: modern threaded comments** (§7). No
PowerPoint-authored reference deck was available, and §11.1 forbids encoding a
guess at the schema. The deferral takes the path §7 specifies — an error, not a
silence — and is detailed below.

### Verification

- `uv run pytest`: **894 passed, 94 skipped**. Of those, 283 are new rp-pptx
  tests; the 94 skips are LibreOffice- and poppler-dependent tests across all
  packages, skipped by functional probe (see "Known limits").
- Coverage on rp-pptx: **95% overall**. §11.3 targets >85% on `pptx/`,
  `ooxml.py` and `templates.py`: `ooxml.py` 98%, `templates.py` 95%,
  `pptx/read.py` 93%, `pptx/write.py` 92%, `pptx/runs.py` 97%,
  `pptx/slides.py` 100%, `pptx/template.py` 100%, `pptx/shapes.py` 100%.
  `cli.py` is 93%. `mcp_server.py` is 0% and is a three-line documented stub.
- `ruff check` and `ruff format --check` clean across the workspace.
- Nothing binary is committed. Every fixture is generated in `conftest.py`.
- CI: `rp-pptx` added to the per-package test matrix, plus pptx equivalents of
  the umbrella-identity, no-LibreOffice-round-trip, and exit-code-taxonomy
  smokes. All three verified locally before commit.
- License gate: `xlsxwriter` allowlisted as BSD-2. python-pptx imports it only
  when *authoring* charts, which this package never does, but the import graph
  carries it.

## Findings — where §5–§9 turned out to be wrong or incomplete

### 1. The `.potx` finding repeated exactly (§5.3)

Verified again against python-pptx 1.0.2, and both halves hold:
`Presentation("x.potx")` raises `ValueError: ... is not a PowerPoint file`, and
`save()` always writes the *presentation* content type. Retyping is load-bearing
in both directions, and `TestContentTypes` asserts it — including that
python-pptx still refuses, so the day it stops, the test fails and `opened()`
can be simplified.

### 2. `synthesize` needs raw XML, and §5.2 understates how much (§5.2, §11.2)

python-pptx can *read* layouts and *rename* them, but it cannot create one, and
it cannot add a master at all — `master.shapes` has no `add_picture` or
`add_textbox` either. §5.2 describes what synthesis must reproduce without
noting that none of it is reachable from the public API.

Resolved rather than deferred. `ooxml.rebuild_masters` does the surgery at the
zip level: it copies the source master for its colour map and theme link,
authors layout parts with exact placeholder inventories, and rewrites
`p:sldMasterIdLst`, the relationships, and the content types together. It is
valid only on a slide-less package, which is exactly what a template is, and
that constraint is what keeps it from also having to rewrite slide rels.

The round trip is asserted: `synthesize(build_manifest(house_like))` comes back
with identical layout names, per-master indices, and placeholder inventories,
including a non-ASCII name and a second master. The same machinery builds the
test fixtures, since the problem is the same one.

### 3. Placeholder types must be OOXML tokens, not enum names (§3)

§3 documents `type: str` with examples `"title"`, `"body"`, `"pic"`, `"tbl"`.
Those are the XML tokens, not python-pptx's enum names — which are `PICTURE` and
`TABLE`. The distinction only bites once synthesis has to write the value *back*
into a layout part. `PP_PLACEHOLDER.to_xml()` is the mapping, and using the
library's own keeps the read and write directions from drifting.

### 4. `shape.shape_type` raises on shapes python-pptx cannot classify (§9)

Not in the spec at all, and it is a whole-file hazard rather than a per-shape
one: `shape_type` raises `NotImplementedError` for anything it does not
recognise, so a single SmartArt frame, ink annotation, or hand-authored shape
anywhere in a deck kills an entire read of it. Found when `build_manifest`
choked on the fixtures' own master text box.

Every classification now keys on the element tag (`p:pic`, `p:grpSp`), which is
unambiguous, cannot raise, and is what the classification is derived from
anyway. Worth carrying into `rp-xlsx` if openpyxl has an equivalent.

### 5. Markdown images should not be a shared block kind (§9, §12 step 2)

§12 step 2 names two additions the promoted parser needs: HTML comment blocks as
nodes, and thematic breaks (which already parsed). Images are not on that list,
but §9 wants a lone image on a slide.

Promoting an `image` block kind would have changed what rp-docx does with an
image line today — it renders the alt text and hyperlink through the inline
parser — and nothing asks for that. So the shared parser gained only `comment`,
and the pptx renderer matches image-only paragraphs itself. If a second leaf
ever needs the same thing, that is the point to promote it.

The heading cap at 4 also turned out to be load-bearing for two packages now:
rp-docx maps levels onto `h1`–`h4` style roles and would `KeyError` above that,
and rp-pptx treats level 3 and deeper alike. It is commented where it lives.

### 6. `create` has no base directory for image paths (§9)

§4's signature takes markdown as *text*, not as a path, so there is nothing to
resolve a relative `![alt](pic.png)` against. Paths resolve against the working
directory, a missing image is an `InputError` naming it rather than a silent
omission, and `docs/usage-pptx.md` states the limit.

A `base_dir` parameter would fix it properly and would change the §4 signature,
so it is recorded here rather than taken unilaterally.

### 7. Part names are not deck order, and filenames are not a contract (§7)

Caught in review, and the mistake was mine twice over. Classic comments were
mapped to slides by parsing `comment<N>.xml` and calling it slide N. That holds
only until a deck is touched — and **this package's own `reorder_slides` breaks
it deliberately**, rewriting `p:sldIdLst` while leaving every part where it is.
Reordering `[3,2,1]` reported every comment against exactly the wrong slide.
Deleting a slide breaks it a second way, by leaving the surviving part numbers
non-contiguous.

The same assumption sat in modern-comment detection, which scanned
`slide<N>.xml` until it hit a gap. After deleting slide 1 the scan found nothing,
`get_comments` fell through to the classic reader, and returned `[]` — the §7
outcome that whole section exists to forbid, reached from a direction the
original defence did not cover.

Both now walk `p:sldIdLst` → relationship → part, and classic is told from modern
by the target's **content type** rather than by its filename or its relationship
type. That matters because the relationship type is precisely the part of the
modern format that could not be verified against a real file, whereas the content
type could.

The other half of the fix is where the deferral is decided: presence is a
package-wide question, placement is a separate and weaker one. A modern part that
cannot be attributed to any slide is still unreadable, so `get_comments` now
raises on presence and uses the slide list only to sharpen the message.

`rp_core.ooxml` gained `resolve_target` and `override_content_types` for this —
both pure OPC mechanics with no format identifier, so they belong in core.

### 8. A layout can exist and still have nowhere to put the content (§5.1)

Also caught in review. §5.1's rule is that a missing layout is an error rather
than a fallback, and the implementation checked the layout *name* — then, if the
layout had no title or body placeholder, silently dropped the content into
nothing. Mapping `content` at a placeholder-less layout produced a slide with the
heading and every bullet quietly discarded, which is the same
silent-wrong-output failure the name check exists to prevent.

Placeholder availability is now checked at the point of use, as laxly as the name
check: only what the slide actually needs is required, so an image-only slide
needs neither placeholder and a section slide with no body does not need a body.

A related wrongness surfaced while fixing it: "the first placeholder with a text
frame" picks the **picture** placeholder on PowerPoint's own "Picture with
Caption" layout, which has a perfectly good body placeholder beside it at the
next index. Body placeholders are now chosen from an allowlist of prose-bearing
types.

### 9. Smaller corrections

- **`get_text` excludes table cells.** §3 does not say either way, but reporting
  cells both here and in `get_tables` doubles every cell in `get_markdown` and
  in any word count built on it. Tables are `get_tables`'s job, where the caller
  also learns the shape of the grid.
- **Merge-origin text depends on how the fixture was built.** python-pptx's
  `merge()` concatenates the swallowed cell's text onto the origin, so a fixture
  that fills before merging produces `"origin\nspanned"` — an artefact of its own
  construction. The fixture merges first, so the assertion encodes §3's contract
  rather than the artefact.
- **`notes_slide` creates the part on access.** `has_notes_slide` has to be
  checked first, or a read quietly grows the package it was only meant to
  inspect. Asserted.
- **A shared "every text frame" helper was the wrong abstraction.** Both callers
  need to treat table cells differently — `get_text` excludes them, and
  `replace_text` needs the table's own index to report a `table:N` location — so
  the helper was deleted and each handles its own.

## The modern-comments deferral (§7)

Taken, and taken the way §7 specifies. Classic comments are **not** part of the
deferral: their format is stable and documented, they need no reference file,
and §7 puts them in scope unconditionally. They are read, with authors,
initials, and dates, and `parent_id` is `None` throughout because classic
comments do not thread.

For modern parts, detected by content type:

- `get_comments` raises `UnsupportedFeatureError` (exit 3) naming the slides
  that carry them, with a hint pointing here. This applies to mixed
  classic/modern decks too — partial results are sacrificed for an error that
  cannot be mistaken for a complete read.
- `get_index` stays total and reports `comment_count: null`.

Returning `[]` is the one outcome §7 forbids, because it is indistinguishable
from a deck with no comments.

**The fixture is honest about what it is.** `modern_comments_deck` writes a part
with the modern content type and nothing else that is trustworthy. §11.1 requires
the generator to be written from a real PowerPoint-authored file, and none was
available, so the fixture does not pretend to reproduce PowerPoint's markup — it
drives the deferral path, which keys on the content type alone, and no test
asserts anything about comment bodies.

**Follow-up to land modern support:** obtain a PowerPoint-authored deck with
threaded comments, record the actual part layout, write the real generator in
`conftest.py`, implement the reader, and **delete `UnsupportedFeatureError`** —
its removal is part of the work, so the stopgap cannot calcify into API surface.

## Known limits

- **Orphaned media after slide deletion.** Media referenced only by a deleted
  slide stays in the package. Invisible bloat, not corruption; garbage-collecting
  shared media is easy to get subtly wrong, and §7 accepts the trade.
- **No reflow or auto-splitting.** Content that outgrows a placeholder overflows
  the slide edge silently. Deciding a section is too long is editorial judgement.
- **Autofit font scaling is not resolved.** A `normAutofit` `fontScale` changes
  what PowerPoint draws; `size_pt` reports the nominal size, which is what the
  file says.
- **WMF/EMF metafiles** report `width_px`/`height_px` as `None`. Extraction still
  writes the bytes and nothing raises.
- **LibreOffice tests skip on a functional probe**, not a presence check. This
  container ships `soffice` that fails every conversion with "source file could
  not be loaded"; rp-docx's equivalents skip here for the same reason. A presence
  check would have turned that into confusing failures.
- **Chart creation is out of scope** (§1). Charts are read only.

## What the next phase inherits

- `rp_core.markdown` and `rp_core.ooxml` are now shared infrastructure. `rp-xlsx`
  gets the zip and content-type mechanics for free; whether it wants the markdown
  parser is a Phase 3 question.
- `mcp_server.py` is a documented stub. Phase 2 claims it; it is roughly three
  lines per tool, because every function already returns a pydantic model. Two
  decisions are Phase 2's: where an MCP client may write, and whether
  `get_comments` raising for modern comments should surface as a tool error or a
  structured partial result.
- §13's manual pass against a real house deck is still open, and is the only
  thing that will confirm `templates inspect` and `templates layoutmap` behave on
  a template nobody here designed. Only step 5 of that pass produces a repository
  artefact, and it carries no confidential content by construction.

## Still open

1. Modern threaded comments (above) — needs one reference file.
2. A `base_dir` for markdown image paths — needs a §4 signature change.
3. §13's validation against a real house template.
