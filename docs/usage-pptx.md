# PowerPoint (`rp-pptx`)

`rp-pptx` reads, creates, edits, and restructures `.pptx` presentations. Read commands emit JSON by default; add `--plain` for human output.

```sh
rp-pptx index deck.pptx
rp-pptx text deck.pptx --slides 1-3
rp-pptx markdown deck.pptx -o deck.md
rp-pptx create -o briefing.pptx --from-markdown briefing.md
rp-pptx replace deck.pptx --map '{"{{ name }}":"Ada"}' -o filled.pptx
rp-pptx slides reorder deck.pptx --order 3,1,2 -o reordered.pptx
```

Editing commands require either `--out` or explicit `--in-place`. LibreOffice is only needed for conversion and rendering.
