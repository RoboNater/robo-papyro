---
name: powerpoint-toolkit
description: Read, create, and edit PowerPoint decks from the shell with rp-pptx — slide text and titles, tables, images, speaker notes, charts, comments, Markdown conversion, building decks on house templates, filling {{ placeholder }} templates, and deleting or reordering slides. Use whenever a task involves a .pptx or .potx file, or asks for a slide deck or presentation.
---

# PowerPoint decks with `rp-pptx`

`rp-pptx` reads, creates, and edits `.pptx` and `.potx` files. Read commands
print JSON to stdout, so you can parse the result instead of scraping text.

Check it is installed: `rp-pptx --help` (or `rp pptx --help`).

## Start here

```sh
rp-pptx index FILE.pptx
```

Slide count, aspect ratio, the layouts the template offers, per-slide titles,
and properties. The title list tells you which slide is which without reading
the whole deck.

## Reading

| Command | What you get |
|---|---|
| `rp-pptx index FILE` | Geometry, counts, layouts, titles, properties |
| `rp-pptx text FILE [--slides SPEC] [--runs]` | Paragraph text, slide by slide |
| `rp-pptx markdown FILE` | The deck as Markdown, in the dialect `create` reads back |
| `rp-pptx tables FILE [--index N] [--format csv\|md -o DIR]` | Tables, with merge spans |
| `rp-pptx images FILE [--out DIR]` | Image metadata; extracts with `--out` |
| `rp-pptx notes FILE` | Speaker notes |
| `rp-pptx charts FILE` | Chart types, categories, series |
| `rp-pptx comments FILE` | Classic comments — see the warning below |
| `rp-pptx props FILE` | Title, author, dates, keywords |

## Writing

**Never edit an input in place unless you were asked to.** Every editing
command takes `-o OUT.pptx`.

```sh
rp-pptx create -o deck.pptx --from-markdown outline.md --template house
rp-pptx append deck.pptx --markdown more.md -o deck-v2.pptx
rp-pptx replace deck.pptx --map '{"Q3":"Q4"}' -o fixed.pptx
rp-pptx set-notes deck.pptx --slide 2 --text "Mention the revenue line" -o noted.pptx
rp-pptx template house --context ctx.json -o pitch.pptx   # strict by default
rp-pptx slides reorder deck.pptx --order 3,1,2 -o reordered.pptx
rp-pptx slides delete deck.pptx --slides 4 -o trimmed.pptx
```

Setting core properties has **no CLI command** — it is library-only
(`rp_pptx.set_properties`), or the `pptx_set_properties` MCP tool. `rp-pptx
props FILE` reads them.

Markdown → slides: a level-1 heading starts a title slide, a level-2 heading
starts a content slide, and bullets, pipe tables, and fenced code become its
content. `rp-pptx markdown` emits the same dialect, so a round trip works.

## Things that will bite you

**`comments` fails on decks with modern threaded comments.** That part is not
readable yet, and returning an empty list would be indistinguishable from a
deck with no comments — so it exits 3 instead. That is the correct answer, not
a bug to work around: **do not report "no comments"** on such a deck. `index`
stays usable and reports `comment_count: null`. Classic comments are read
normally.

**Slide numbers are presentation order, not filenames.** After a delete or a
reorder, the numbering changes: a second operation must be planned against the
*new* file, not the original. Chain them one at a time and re-check with
`index`.

**`--slides` spec:** `all`, `2`, `3-7`, `-4`, `7-`, `1,3-5,9`, all 1-based.

**Layout resolution never falls back.** If the template has no layout with the
placeholders your content needs, `create` fails and says which — rather than
dropping bullets into a picture placeholder and producing a deck that looks
wrong. `rp-pptx templates list` shows what resolves by name and `rp-pptx templates
inspect NAME` shows its layouts and their placeholders.

**`replace` never touches layouts or masters.** That is design furniture.
Where two keys overlap, the longer match wins. It reports a per-key count —
check it; 0 means the text was not there.

**`.potx` works everywhere `.pptx` does.**

## Reading the outcome

JSON on stdout. Errors on **stderr**, human message first and a JSON envelope
as the last line:

```json
{"error": {"type": "UnsupportedFeatureError", "message": "…", "hint": null, "exit_code": 3}}
```

| Exit | Meaning | What to do |
|---|---|---|
| 1 | Bad arguments — missing file, unknown template, bad slide spec | Fix the call |
| 2 | A required external program is missing | `rp-pptx doctor` |
| 3 | Corrupt, not a deck, or an unsupported feature | Report it; do not retry |

Reading and writing need **no external program**. Only `convert` and `render`
need LibreOffice.

## As a library

```python
from pathlib import Path
from rp_pptx import get_index, get_text, create, replace_text, reorder_slides

index = get_index(Path("deck.pptx"))
create(Path("out.pptx"), markdown="# Title\n\n## Content\n\n- point", template="house")
reorder_slides(Path("deck.pptx"), [3, 1, 2], output=Path("out.pptx"))
```

Full guide: `docs/usage-pptx.md` in the robo-papyro checkout.
