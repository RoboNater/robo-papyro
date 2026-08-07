# rp-pptx

PowerPoint reading, authoring, templating, and slide operations for
[robo-papyro](https://github.com/RoboNater/robo-papyro).

JSON-first: every read command emits a complete pydantic model, so a tool with no
native document capability can operate on `.pptx` and `.potx` files through a
plain CLI. Reachable as both `rp-pptx` and `rp pptx`.

```sh
uv run rp-pptx index deck.pptx
uv run rp-pptx create -o out.pptx --from-markdown notes.md --template house
uv run rp-pptx slides reorder deck.pptx --order 3,1,2 -o reordered.pptx
```

No external binary is needed to read, create, edit, or restructure a deck.
LibreOffice is required only for `convert` and `render`; `rp-pptx doctor` reports
what is installed.

Full guide: [docs/usage-pptx.md](../../docs/usage-pptx.md).
Specification: [docs/specs/rp-pptx-spec.md](../../docs/specs/rp-pptx-spec.md).
