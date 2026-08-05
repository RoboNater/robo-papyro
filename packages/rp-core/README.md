# rp-core

Shared infrastructure for the [robo-papyro](../../README.md) suite. No CLI of
its own, no format-specific knowledge.

| Module | Contents |
|---|---|
| `errors.py` | `RoboPapyroError` hierarchy and its exit-code mapping |
| `models.py` | `Capability`, `ErrorEnvelope`, `RasterImage` |
| `ranges.py` | 1-based inclusive range-spec parsing (pages, sections, sheets) |
| `binaries.py` | `soffice` / poppler discovery and invocation |
| `render.py` | any-file → PNG rasterization |
| `doctor.py` | capability report |
| `clikit.py` | shared typer conventions |

**`rp-core` imports no leaf package.** It knows nothing about PDF or OOXML;
`rp-pdf` and `rp-docx` depend on it, never the reverse.

Spec: [`docs/specs/robo-papyro-spec.md`](../../docs/specs/robo-papyro-spec.md) §4.
