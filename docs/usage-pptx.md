# PowerPoint (`rp-pptx`)

`rp-pptx` reads, creates, edits, and restructures `.pptx` presentations and
`.potx` templates. Structured read commands (`index`, `text`, `tables`,
`images`, `notes`, `comments`, `charts`, `props`) emit JSON on stdout by
default; add `--plain` for human-readable output. There is no `--json` flag —
JSON *is* the default for these. `convert` and `render` follow the same
convention: they write the requested artifacts to disk and report JSON result
metadata to stdout by default, same as any other command. `markdown` is the
one command whose stdout differs by design: with no `-o` it prints Markdown
itself; given `-o FILE` it writes the file and reports a JSON `WriteResult`
(the output path) to stdout instead of the Markdown.

Reachable two ways, which are the same code:

```sh
uv run rp-pptx index deck.pptx
uv run rp pptx index deck.pptx
```

## Reading

```sh
rp-pptx index    deck.pptx                       # geometry, counts, layouts, titles
rp-pptx text     deck.pptx --slides 1-3          # paragraphs, with outline levels
rp-pptx text     deck.pptx --runs                # down to per-run formatting
rp-pptx tables   deck.pptx --format md           # also: json (default), csv
rp-pptx images   deck.pptx -o ./img              # metadata, and the bytes if -o
rp-pptx notes    deck.pptx
rp-pptx comments deck.pptx --author "Ada Lovelace"
rp-pptx charts   deck.pptx
rp-pptx props    deck.pptx --plain
rp-pptx markdown deck.pptx -o deck.md
```

`--slides` takes the suite's range syntax: `all`, `5`, `3-7`, `-4` (up to slide
4), `7-` (slide 7 to the end), and mixed lists combining any of those
(`1,3-5,9`, `-2,8-`). Every read that returns per-slide content accepts it, so
asking what is on slide 12 does not mean fetching all ninety.

**Indices count across the deck, not across the selection.** A table numbered 4
in a whole-deck read is still 4 under `--slides 3`.

## Creating and editing

```sh
rp-pptx create    -o deck.pptx --from-markdown notes.md --template house
rp-pptx append    deck.pptx --markdown more.md -o bigger.pptx
rp-pptx replace   deck.pptx --map '{"{{ name }}":"Ada"}' -o filled.pptx
rp-pptx set-notes deck.pptx --slide 3 --text "Pause here" --in-place
rp-pptx template  house --context '{"client":"Acme"}' -o pitch.pptx
rp-pptx slides delete  deck.pptx --slides 4-6 -o trimmed.pptx
rp-pptx slides reorder deck.pptx --order 3,1,2 -o reordered.pptx
```

**Every editing command needs `-o` or `--in-place`.** It will not guess a
filename and it will not overwrite the input silently. `--map` and `--context`
take either inline JSON or a path to a JSON file.

`--order` must be a complete permutation of the deck's slides; anything else is
an error naming what is missing, duplicated, or out of range. `slides delete`
refuses to leave zero slides.

## Markdown → slides

`create` maps a markdown document onto a slide sequence deterministically:

| Markdown | Becomes |
|---|---|
| first `#` | the title slide; a paragraph straight after it is the subtitle |
| later `#` | a section-break slide |
| `##` | a content slide, the heading as its title |
| `---` | an explicit slide break, same layout, no title |
| `###` and deeper | a **bold lead-in bullet**, not a new slide |
| `- item`, nested | bullets at outline levels 0–8 |
| GFM pipe table | a native table |
| fenced code | a monospace text box |
| `![alt](path.png)` | a picture; alone on a slide it uses the `blank` layout |
| `<!-- ... -->` | that slide's speaker notes (the Marp convention) |

`markdown` emits this same dialect, so a deck round-trips back through `create`.

`append` uses the same rules with one substitution: a leading `#` opens a
*section* slide, because the deck already has a title. Leading unheaded content
opens a new untitled slide rather than joining the existing last one, and no
existing slide's content, notes, or order is touched.

Two limits worth knowing:

- **No reflow, no auto-splitting.** Slides do not scroll. Content that outgrows
  its placeholder overflows the slide edge silently. Count your bullets with
  `rp-pptx text` on the result if it matters; deciding a section is too long is
  editorial judgement and out of scope.
- **Image paths resolve against the working directory**, not against the
  markdown file, because `create` takes markdown as text rather than as a path.
  A missing image is an error, never a silent omission.

## Templates

House templates are the normal path. `create` and `template` resolve a name
against `RP_PPTX_TEMPLATE_DIR`, then `templates/local/`, then `templates/`,
trying `.potx` before `.pptx`. `RP_PPTX_TEMPLATE` names the default.

```sh
rp-pptx templates list
rp-pptx templates inspect house
rp-pptx templates layoutmap house.potx -o house.potx.layoutmap.json
rp-pptx templates manifest house.potx -o tests/fixtures/house.manifest.json
rp-pptx templates synthesize house.manifest.json -o rebuilt.potx
```

House decks rarely use PowerPoint's layout names, so markdown roles are mapped
through a `<template>.layoutmap.json` sitting beside the template:

```json
{
  "title": "RP Title",
  "section": "House Section Break",
  "content": "House Content",
  "blank": "House Blank"
}
```

`templates layoutmap` scaffolds one by guessing from layout names. **It is a
convenience, never authoritative** — check every role. A role that names a
missing layout fails loudly at the point of use, listing what the template does
have; it never silently falls back to something else. And the check is lazy: a
deck with no section breaks does not need a section layout to exist.

A **manifest** describes a template's shape — layout names, placeholder
inventory, geometry, presence flags — and is redacted by construction: no slide
text, no image bytes, no author names, no path beyond the basename. That is what
makes it safe to commit, so CI can exercise a confidential template's shape via
`synthesize` without the file ever leaving the machine that holds it.

Aspect ratio has one rule worth stating: `create` forces 16:9 when you supply no
template, and an explicitly supplied template always wins on geometry — even if
it is the same file the default would have resolved to.

## Comments

Classic comments are read normally. **Modern threaded comments are not supported
yet**: a deck carrying them makes `rp-pptx comments` fail with exit 3 naming the
affected slides, rather than returning an empty list that cannot be told from a
deck with no comments. `rp-pptx index` still works on such a deck and reports
`comment_count: null`. See `dev-notes/status-robo-papyro-phase-2.5.md`.

## Converting and rendering

```sh
rp-pptx convert deck.pptx --to pdf -o deck.pdf
rp-pptx render  deck.pptx -o ./slides --dpi 150 --slides 1-5
```

These need LibreOffice (and poppler for rendering); `rp-pptx doctor` reports what
is installed. Nothing else in this package needs an external binary — reading,
creating, editing, templating, and slide operations all work without one.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | user or input error — bad path, bad slide spec, unknown template, missing `-o` |
| 2 | a required external binary is missing |
| 3 | the file is corrupt, or uses a feature this version cannot read |

Errors go to stderr as an `ErrorEnvelope`; results go to stdout. Both are JSON,
and the envelope shape is the same across every tool in the suite.
