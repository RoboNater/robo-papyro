# rp-core

Shared infrastructure for the [robo-papyro](../../README.md) suite. No CLI of
its own, no leaf imports.

| Module | Contents |
|---|---|
| `errors.py` | `RoboPapyroError` hierarchy and its exit-code mapping |
| `models.py` | `Capability`, `ErrorEnvelope`, `RasterImage` |
| `ranges.py` | 1-based inclusive range-spec parsing (pages, sections, slides) |
| `binaries.py` | `soffice` / poppler discovery and invocation |
| `render.py` | any-file → PNG rasterization |
| `doctor.py` | capability report |
| `ooxml.py` | generic OPC/OOXML zip read/repack, content-type read/rewrite, compiled-XPath helper |
| `markdown.py` | shared Markdown block/inline parser (leaves supply their own renderer) |
| `clikit.py` | shared typer conventions |

**`rp-core` imports no leaf package**, and `rp-pdf`, `rp-docx`, and `rp-pptx`
depend on it, never the reverse. It has no PDF-specific or format-specific
knowledge, but `ooxml.py` and `markdown.py` are deliberately not
format-specific either: they hold only the OPC/OOXML and Markdown mechanics
that are genuinely generic across every leaf that needs them. Namespace maps,
content-type strings, and WordprocessingML/PresentationML rendering stay in
`rp-docx` and `rp-pptx`.

Spec: [`docs/specs/robo-papyro-spec.md`](../../docs/specs/robo-papyro-spec.md) §4.
