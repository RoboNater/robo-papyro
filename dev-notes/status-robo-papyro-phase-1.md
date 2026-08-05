# Status — robo-papyro Phase 1 (`rp-docx`)

**Date:** 2026-08-05 · **Branch:** `claude/robo-papyro-phase-1-rp-docx-09z1zi` ·
**Driving doc:** [`docs/specs/rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §12

## BLUF

**Phase 1 is complete — all nine steps.** `rp-docx` exists as the suite's second
leaf: reading, writing, native templating, and the template manifest/synthesis
loop. The suite is at **593 tests** (from 382), green, with 90 skips that are
all "poppler absent" or "LibreOffice cannot convert here". `ruff check` and
`ruff format --check` clean, license gate green, and `rp docx index FILE` is
byte-identical to `rp-docx index FILE`.

Coverage on what §11.3 names: `docx/read.py` 92%, `docx/runs.py` 98%,
`docx/write.py` 95%, `docx/template.py` 97%, `ooxml.py` 97%, `templates.py` 92%.
All above the >85% target. `cli.py` reads at 44% because its tests drive the
installed console script through a subprocess, which coverage does not observe —
the command surface is nonetheless exercised end to end, which is the point.

**No corporate template was needed at any point**, as §12 promised. The three
synthetic templates are built in `conftest.py` and nothing binary is committed.

**The headline finding:** python-docx does not open a `.dotx` at all. §5.3 asked
this to be verified early rather than discovered in step 7; it was, and it
reshaped the package.

## What landed

| Step | Scope |
|---|---|
| 1 | `packages/rp-docx/` as a workspace member; both entry points registered |
| 2 | `models.py` — docx-specific models only; `rp_core`'s are imported |
| 3 | `ooxml.py` — namespaces, package zip, xpath, content-type retyping |
| 4 | `templates.py` — resolution, inspection, StyleMap, manifests, synthesis |
| 5 | `docx/runs.py` — the run-spanning problem, unit-tested standalone |
| 6 | `docx/read.py` — index, text, markdown, tables, images, comments, changes |
| 7 | `docx/write.py`, `docx/template.py` — create, edit, revisions, placeholders |
| 8 | `cli.py` per §10; `mcp_server.py` left a documented stub |
| 9 | Full suite, CLI sweep, docs, CI matrix and smoke steps |

## Findings — where §5–§9 turned out to be wrong or incomplete

The definition of done asks for this list. Six items, roughly in descending
order of how much they changed.

### 1. python-docx cannot open a `.dotx` (§5.3)

§5.3 said to "verify early whether `python-docx` opens `.dotx` without
complaint, and whether it round-trips the content type". The answer to the first
half is **no, it refuses outright**:

```
ValueError: file 'probe.dotx' is not a Word file, content type is
'application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml'
```

The second half is moot as stated, but the useful version of it is that
**retyping is lossless in both directions** — the part list is identical across
a retype → open → save → retype cycle.

Consequence: `retype_as_template` / `retype_as_document` are not a convenience
for fixtures, as §5.3 framed them, but load-bearing infrastructure. Every entry
point that accepts a document goes through `ooxml.opened()`, which retypes a
copy into a temp directory when the input is a template. mammoth needed the same
treatment for `get_markdown`. And `ooxml.save` retypes on the way *out*, because
python-docx always writes the document content type — a file named `.dotx` that
is really a document is one Word opens as an ordinary document, silently editing
what the user meant to keep as a template.

Asserted rather than remembered, in `test_ooxml.py::TestContentTypes`: if a
future python-docx learns to open templates, that test fails and `opened()` can
be simplified, which is worth being told about.

### 2. `StyleMap.code = "Source Code"` breaks Word's own default (§3)

**Spec deviation, deliberate.** §3 gives `code: str = "Source Code"`. That is a
LibreOffice style name; Word ships **no code paragraph style at all**, and
neither does python-docx's bundled default template. Combined with §5.1's
correct "never silently fall back" rule, the specified default makes *every*
Markdown document containing a fenced code block fail on the default template.

Changed to `code: str | None = None`, and only that role. Every other default in
the StyleMap names a style that genuinely exists; a default for this one could
only name a style that might not. `None` means "this template has no code
style", and code blocks render in the body style with a monospace font — the
most a template without one can express. Naming a style still makes it
*required*: `test_write.py::test_a_named_but_missing_code_style_still_fails_loudly`
covers that optional means "may be unset", not "may be wrong".

### 3. Style checking must be lazy, not eager (§5.1)

Related to the above, and worth stating separately because it is a design rule
rather than a default. §5.1 says "if a mapped style is absent from the template,
raise `InputError`". Read as an eager check over the whole `StyleMap` at
template-load time, that rejects python-docx's own default template for a role
most documents never use.

`require_style` is therefore called at the point of use — when a code block is
actually rendered, when an H1 is actually written. A document that contains no
code block does not need a code style. This is what makes the `hostile` fixture
meaningful too: it is missing "Heading 1", so markdown *with* an H1 fails loudly
while markdown without one succeeds.

### 4. `resolve_template` needs a fourth case (§5.1)

§5.1 lists three inputs and one failure. It is missing the common mistake: a
**path-shaped argument that does not exist**. Falling through to case 4 produces
"No template called '../drafts/memo.dotx'. Available: memo, letter…", which
sends the user hunting the template directories for a typo in their own path.

Anything with a suffix or a separator now reports `No such template file: …`
instead.

### 5. Two manifest fields were silently never populated (§3)

Found by the §12 step 4 checkpoint, which is exactly what it exists for.

- `page_margins_twips` recorded only top/bottom/left/right. python-docx spells
  the other two `header_distance` / `footer_distance`, not `*_margin`, so
  reading them as if they were `*_margin` recorded a template's header position
  as *absent* rather than as wrong. `gutter` has no python-docx accessor at all
  and was dropped from the key set rather than left silently missing.
- `default_paragraph_style` was always `null`. python-docx exposes no accessor
  for `w:style/@w:default`; it is read from the XML now.

Both are the kind of defect a checkpoint catches and a passing test suite does
not, because nothing was asserting on fields nobody had looked at.

### 6. Smaller corrections

- **`StyleDef.type`** (§3) — python-docx spells OOXML's `numbering` type `LIST`.
  The models report `numbering`, the name in the file. Also, `_NumberingStyle`
  exposes neither `base_style` nor `builtin`, so both are read defensively.
- **`iter_paragraphs` and lxml proxy identity** (§6) — keying a table lookup on
  `id(element)` is wrong: lxml creates Python proxies on demand and discards
  them once unreferenced, so a recorded `id()` can belong to an unrelated proxy
  by the time it is looked up. The dict holds the elements themselves.
- **`ooxml.xpath` cannot call `element.xpath(...)`** — python-docx subclasses
  `_Element` and overrides `xpath` with a single-argument version binding *its*
  namespace map, which omits several namespaces this package needs. Everything
  goes through a compiled `etree.XPath`.
- **`list_level`** (§3) — numbering can be attached to the paragraph *or*
  inherited from its style, and python-docx's own
  `add_paragraph(style="List Bullet")` produces the second kind. Reading only
  the paragraph's own `w:numPr` reports every style-driven list as not a list.
- **`--in-place`** (§10) — §10's command list omits it, while §10's own Rules
  require never overwriting an input without it. Added to `append`, `replace`,
  `accept`, and `reject`; without `-o` or `--in-place` they refuse rather than
  guess.
- **`images -o DIR`** (§10) — shown as required; made optional, because
  `get_images` supports it and listing a document's images without extracting
  them is genuinely useful.
- **Fenced code blocks** (§9) — not in §9's list, which stops at code *spans*,
  but the `code` role in the StyleMap has no other purpose. Implemented.

## Which hand-made fixture files were needed

§11.3 predicted "2–3 files under `tests/fixtures/`, each < 30 KB" for tracked
changes and comments, which python-docx genuinely cannot produce.

**None were committed.** Both are built in `conftest.py` by replacing a
generated document's body with hand-written XML (`_document_with_body`) and, for
comments, appending `comments.xml` / `commentsExtended.xml` with their
relationships and content-type overrides. This is more work than committing two
binaries, and it is the right trade for the same reason §11.1 gives: a generated
fixture cannot drift, and a failure is always the code. `tests/fixtures/` is
therefore empty, reserved for the `*.manifest.json` files a real template will
produce.

## Notable implementation decisions

**Text editing works at the package level, not through python-docx.** Every
text-mutating operation parses the relevant XML parts, edits them, and repacks.
That is what makes one implementation cover the body, table cells, text boxes,
headers, footers, footnotes, and endnotes uniformly — several of which have no
python-docx representation at all. `write.revisable_parts()` is the list, and
both `replace_text` and the accept/reject pair walk it.

**Overlapping placeholder matches resolve to the longer.** `{{ name }}` and
`{{ name }} suffix` can match at the same offset. Picking arbitrarily would make
the result depend on dict ordering, which no caller can see or control.

**A key that matched nothing is reported with a count of zero.** Omitting it
would force a caller to know whether a missing key means "absent from the
document" or "not attempted".

**`create` keeps the template's body.** A letterhead template's boilerplate is
the reason it exists, and Word's own "new from template" behaves the same way.
Markdown is appended after it.

**`requires_soffice` probes function, not presence.** This container ships a
`soffice` that fails every conversion with "source file could not be loaded". A
presence check turned that into four confusing failures in an environment that
never claimed to support conversion; a one-off functional probe turns it into
four honest skips. AGENTS.md's rule — no test may *require* LibreOffice —
holds either way.

## Known limits

- **Rejecting an inserted paragraph mark does not merge paragraphs.** The
  revision record is removed, which is most of what Word does, but the two
  paragraphs stay separate. §7 does not mention paragraph-mark revisions at all;
  text content is unaffected. Documented in `docs/usage-docx.md`.
- **Nested inline emphasis is not parsed.** `**bold with *italic* inside**`
  yields one bold span. §9's list stops at single spans, and nesting is where a
  hand-rolled parser starts guessing.
- **Inline code spans use a font, not a character style.** Word ships no
  built-in code character style, so requiring one would fail on its own
  defaults.
- **`cli.py` coverage reads low** for the subprocess reason above. If that
  becomes a problem, the fix is a second test module driving the typer app
  in-process — not a change to the CLI.

## Repository housekeeping

- `.coverage` was tracked and churned on every test run; removed from git and
  added to `.gitignore` along with `templates/local/`, which §11.1 requires to
  be gitignored and which was not.
- The license gate gained exactly one entry: **`cobble`**, mammoth's only
  dependency, by mammoth's own author. Its wheel ships no LICENSE file and its
  metadata says only "BSD License"; the project README names 2-Clause BSD, which
  is what the allowlist records. The base install path grew from 26 to 31
  distributions and remains free of weak copyleft.
- CI gains `rp-docx` in the test matrix and four smoke steps: the CLIs respond,
  `rp docx` and `rp-docx` are the same code path, the exit-code taxonomy matches
  `rp-pdf`'s, and **the whole read/write round trip runs with no LibreOffice
  installed** — which is the enforceable form of §10's "no external binary is
  required for any core read/write path".

## What Phase 2 inherits

`mcp_server.py` is a documented stub and deliberately empty: parent §9 puts the
MCP servers in their own `rp-mcp` distribution so the SDK's dependencies stay
out of every leaf's base install path, and starting one here would undo that.
The read surface maps one-to-one onto tools, since every function already
returns a pydantic model. The write surface needs a decision about where an MCP
client may write, which is a Phase 2 question.

## Still open

- **Validation against a real house template** — §13's manual pass. Nothing in
  Phase 1 has seen one. `templates/README.md` now carries the exact command
  sequence.
- **Template provenance** — parent §11.1, unresolved. The manifest loop lowers
  the stakes, since CI depends on manifests rather than on templates, but it
  does not answer where the source of truth lives.
