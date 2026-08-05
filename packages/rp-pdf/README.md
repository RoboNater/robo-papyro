# rp-pdf

PDF read/extract/render for the [robo-papyro](../../README.md) suite. JSON-first
library and CLI for text, tables, images, search, Markdown conversion, and page
rendering.

- **Import:** `rp_pdf` · **CLI:** `rp-pdf`, also reachable as `rp pdf`
- **Spec:** [`docs/specs/rp-pdf-spec.md`](../../docs/specs/rp-pdf-spec.md)
- **Usage:** [`docs/usage.md`](../../docs/usage.md)

```bash
uv sync                      # from the workspace root
rp-pdf index document.pdf
rp-pdf text document.pdf --pages 1-5 --plain
```

Shared infrastructure — page-spec parsing, error/exit-code conventions, external
binary discovery, rasterization — lives in `rp-core`. Don't reimplement it here.
