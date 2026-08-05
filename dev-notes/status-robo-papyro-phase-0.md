# Status — robo-papyro Phase 0

**Date:** 2026-08-04 · **Branch:** `claude/robo-papyro-phase-0-2ca2hj` ·
**Driving doc:** [`docs/specs/robo-papyro-spec.md`](../docs/specs/robo-papyro-spec.md) §8

## BLUF

**Phase 0 is complete.** All nine steps landed as eight commits, one per
structural step. `pdfx` is now `rp-pdf` inside a uv workspace, `rp-core` holds
the shared infrastructure, and the `rp` umbrella dispatches to leaf packages by
entry-point discovery. The spec's definition of done is met and verified from a
clean checkout.

The suite went from **202 tests to 309**, all passing on Python 3.11 and 3.13.
`rp-pdf`'s behavior is unchanged except for two things you approved in advance:
the CLI exit-code mapping, and the rename reaching env vars, config filenames,
and cache directories.

**One decision is needed at Phase 1 start**: the error payload shape, which
would otherwise become a shipped contract in two structurally different forms.
Three further items are worth settling but block nothing — see
[Open questions](#open-questions).

## What shipped

```
robo-papyro/
├── pyproject.toml          workspace root — no code; shared ruff/pytest/dev deps
├── ci/                     license gate + its own tests
├── packages/
│   ├── rp-core/            errors, models, pages, binaries, render, doctor, clikit
│   ├── rp-pdf/             the former pdfx, renamed
│   └── robo-papyro/        the `rp` dispatcher
├── docs/specs/             all three specifications
└── templates/              placeholder; §11.2 still open
```

| Step | Scope | Commit |
|---|---|---|
| 1–3 | Workspace scaffold, relocate `pdfx`, rename to `rp_pdf` / `rp-pdf` | `4b81323` |
| 4 | Scaffold `rp-core` as a workspace dependency | `76a39db` |
| 5.1–5.4 | Extract pages, errors, binaries, rasterization | `8e65011` |
| 5.5 | Extract CLI conventions into `clikit`; add `doctor` | `0b8f6b8` |
| 6 | Test `rp-core`'s new behavior | `6a9e740` |
| 7 | `rp` umbrella CLI with entry-point discovery | `edc7937` |
| 8 | Rewrite `AGENTS.md`, `README.md`, `ROADMAP.md`, `docs/usage.md` | `8eeb432` |
| 9 | CI: lint, test matrix, license gate, smoke | `2a25736` |

`rp-pdf` shed five concerns to `rp-core` and gained a `doctor` command. `rp`
discovers subcommands via `importlib.metadata` and never imports a leaf package
— enforced by a test that walks the module's AST.

## Test results

| Suite | Before | After |
|---|---:|---:|
| `rp-pdf` | 202 | 202 |
| `rp-core` | — | +90 |
| `robo-papyro` | — | +15 |
| license gate | — | +16 |
| **Total** | **202** | **309** |

Notes on how this was verified, because the numbers are easy to misread:

- **poppler was installed mid-way**, which un-skipped 75 tests that had been
  passing as skips. To make the comparison honest, the **pre-refactor tree was
  run in its own venv with poppler present** and also gives 202 passed. The
  rasterization rewrite is therefore checked against a real baseline, not
  against an absence.
- Green on **Python 3.11 and 3.13**.
- Green from a **clean `git clone` + `uv sync`**, with `rp --help`, `rp doctor`,
  `rp pdf --help`, `rp-pdf --help`, and `rp-pdf doctor` all responding — the
  spec's definition of done.
- `rp-core` coverage: **98%**.
- `ruff check` and `ruff format --check` clean across `packages` and `ci`.
- License gate: 46 locked packages, all reviewed.

## Behavior changes

### Intentional, per decisions taken before work started

1. **Exit codes.** Previously every CLI error exited `1`. Now `1` for input
   errors, `2` for a missing external binary, `3` for a corrupt or unreadable
   file — spec §4.7, shared across the suite. No existing test covered the `2`
   and `3` paths, so three were added.
2. **The rename reaches user-facing surface**, which spec §8 step 3 does not
   mention:

   | Was | Now |
   |---|---|
   | `PDFX_VLM_*`, `PDFX_CACHE_DIR`, `PDFX_CONFIG` | `RP_PDF_VLM_*`, `RP_PDF_CACHE_DIR`, `RP_PDF_CONFIG` |
   | `PDFX_POPPLER_PATH` | `RP_POPPLER_PATH` (suite-wide; lives in `rp-core`) |
   | `pdfx.toml` | `rp-pdf.toml` |
   | `~/.config/pdfx/`, `~/.cache/pdfx/` | `~/.config/rp-pdf/`, `~/.cache/rp-pdf/` |
   | `PdfxError` | `RpPdfError` |

   Existing config files and exported environment variables break. This was the
   deliberate trade: it is the only cheap moment, and `rp-docx` already assumes
   an `RP_*` convention.

### Incidental

3. **`rp-core` declares `pdf2image` and `pillow`.** It was importing them
   undeclared — a latent packaging bug introduced during the extraction and
   fixed in the same step.
4. **ruff's lint `select` is pinned to `E4, E7, E9, F`.** Newer ruff releases
   widened the implicit default, which flags ~65 pre-existing findings. Pinning
   made a meaningful CI gate possible without rewriting code mid-refactor.

Everything else is byte-identical. `rp pdf index FILE` and `rp-pdf index FILE`
diff clean, and CI asserts that on every run.

## Where the extraction revealed design problems

1. **§5's "thin delegation" for `render_pages` is not achievable as written.**
   §4.5's signature returns `list[Path]`; `rp-pdf`'s function resolves page
   *labels*, names files by label, and returns `RenderedPage` models carrying
   both numbering schemes. None of that can live in a package that "knows
   nothing about PDF." Resolved by splitting: `rp_core.render.rasterize` is the
   primitive (physical pages only, caller-injected naming), and §4.5's
   `render_pages` is a convenience wrapper over it. One pdf2image call site,
   zero behavior change — but a delegation of ~20 lines, not a one-liner.

2. **`clikit` only half-fits `rp-pdf`.** `rp-pdf` is JSON-by-default with
   `--plain` opt-outs; §4.6's `json_option` and `emit` assume `--json` opt-in,
   which is `rp-docx`'s shape. They are written and unit-tested but have no
   Phase 0 consumer. Only `handle_errors` and `doctor_command` are actually used
   by `rp-pdf`.

3. **The error-shape divergence extends past the stream.** `rp-pdf` emits a flat
   `{"error": "msg"}`; the spec's `ErrorEnvelope` is
   `{"error": {type, message, hint, exit_code}}`. `clikit` supports both and
   `rp-pdf` keeps its shape, so `rp-pdf` and `rp-docx` will emit structurally
   different errors. See [Open questions](#open-questions).

4. **§5's binary split lands in the wrong place.** "poppler invocation →
   `binaries.py`" would put `pdftotext`'s `-f/-l/-enc/-upw` flags and form-feed
   page splitting into `rp-core`. Only *discovery* moved; the invocation stayed
   in `rp-pdf` where the PDF-specific knowledge belongs.

5. **`pages.py` leaks a leaf concept into `rp-core`.** `parse_page_labels` is
   PDF page-label logic. §4.3 says move the module, so it moved — but it does
   not belong in a format-agnostic core, and it will look stranger once
   `rp-docx` depends on the same module.

6. **`run_binary(timeout=None)` at the `pdftotext` call site.** §4.4 specifies
   `timeout=120`. `pdftotext` has never been time-limited here and a large PDF
   can legitimately take minutes, so existing behavior won over the spec
   default. A hung `pdftotext` is a real hazard.

7. **Two footguns the workspace itself created**, both now recorded in
   `AGENTS.md`:
   - Any new `rp-pdf` subcommand **must** be added to `COMMAND_NAMES` in
     `cli.py`, or the default-action dispatcher parses it as a filename. This
     bit the `doctor` command during step 5.5.
   - Two packages with same-named test modules collide under pytest's default
     prepend import mode. This bit `test_render.py`, which exists in both
     `rp-core` and `rp-pdf`; `rp-core`'s is now `test_core_render.py`.

## Open questions

| # | Question | Why it matters now |
|---|---|---|
| 1 | Should `rp-pdf` adopt the `ErrorEnvelope` payload, or should `rp-docx` adopt the flat shape? | Whichever way it goes, deciding after Phase 1 means changing a shipped contract. Both are one `clikit` argument today. |
| 2 | Widen ruff's `select` back toward the current default? | ~65 pre-existing findings, mostly auto-fixable. A clean sweep is cheap now and gets expensive as packages multiply. |
| 3 | Give `pdftotext` a real timeout? | It can hang on malformed input. Preserved as-is because a refactor is the wrong place to change it. |
| 4 | Two weak-copyleft transitives, **confined to the `ai` extra** | See below. Lower stakes than the other three, but the only one that may need someone outside the team. |

### On #4, the two MPL-2.0 packages

`certifi` (MPL-2.0, a CA-bundle data package) and `tqdm` (MPL-2.0 AND MIT) are
weak, file-level copyleft rather than fully permissive, and neither is on §7's
approved list. Both were allowlisted, with the reasoning recorded in
`ci/allowed-packages.toml`, on the grounds that MPL-2.0 is the license §7
already accepts for LibreOffice — flagged here because it was not an explicit
call.

**Both enter only through the optional `ai` extra** — `openai` → `httpx` →
`certifi`, and `openai` → `tqdm`. A base install resolves to 24 distributions
containing neither:

```
$ uv pip install rp-core rp-pdf     # no --extra ai
24 distributions, all fully permissive
```

So the default install is clean, and if anyone objects to MPL-2.0 the blast
radius is the VLM review pass, not the toolkit. That also means the fallback is
cheap: drop the `ai` extra rather than re-architect anything.

### Timing

Only **#1** must be settled at Phase 1 start, and not on day one — everything
through `rp-docx`'s `read.py` and `write.py` is indifferent to the error shape;
only `cli.py` (spec §12 step 8) depends on it. **#2** and **#3** are independent
of Phase 1 and can land any time, each as its own small PR. **#4** is the only
item with an external clock: if compliance has to sign off, start that now.

Still open from the spec itself: `templates/README.md` needs an owner and
canonical location per template (§11.2), and archiving
`w528-pdf-extraction-toolkit` is now unblocked (§11.3).

## Next

Phase 1 — `rp-docx`, per [`docs/specs/rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §12.
Note its step 5 stops and reports: `rp-docx templates inspect` must be run
against the real house template so the first `.stylemap.json` is authored by
hand rather than guessed.
