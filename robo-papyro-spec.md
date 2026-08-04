# robo-papyro — Workspace & Architecture Specification

**Version:** 1.0
**Status:** Ready for implementation
**Companion document:** `rp-docx-spec.md`

---

## 1. Overview

`robo-papyro` is a document tooling suite giving agentic coding tools a stable, scriptable interface to PDF and Office document formats. It is a single repository containing several independently versioned Python distributions.

| Distribution | Import name | CLI | Purpose |
|---|---|---|---|
| `rp-core` | `rp_core` | — | Shared infrastructure: external-binary wrappers, capability detection, error/exit-code conventions, page-spec parsing, JSON output contract |
| `rp-pdf` | `rp_pdf` | `rp-pdf` | PDF read/extract/render (existing `pdfx` code) |
| `rp-docx` | `rp_docx` | `rp-docx` | Word document read/write/edit |
| `robo-papyro` | `robo_papyro` | `rp` | Meta-distribution: installs the others, provides the umbrella `rp` dispatcher |

**Rationale for one repo, several distributions:** corporate overhead (license scan, SBOM, security review, CI onboarding) is charged per repo. Workspace path dependencies resolve with nothing but git — no internal package index required. Cross-cutting changes land atomically in one PR. Separate distributions keep version histories independent and keep `rp-pdf` users from installing `python-docx`.

**Dependency direction is strictly one-way.** `rp-core` knows nothing about PDF or OOXML. `rp-pdf` and `rp-docx` never import each other. Only `robo-papyro` depends on the leaves, and it does so through entry-point discovery rather than direct imports.

### Non-goals
- Rendering fidelity guarantees — LibreOffice does the converting; we don't chase pixel parity
- Collaborative/real-time editing
- Legacy binary `.doc` support (not present in the target corpus)
- Google Docs / Office 365 API integration

---

## 2. Naming Decision

The existing code uses the import name `pdfx` and CLI `pdfx`. Phase 0 renames these to `rp_pdf` / `rp-pdf` for consistency with the suite.

This is a mechanical rename, and this is the only moment it is cheap — a fresh repo with no external consumers. If you would rather keep `pdfx` as the import name and only change the CLI, say so before Phase 0 starts; mixed naming is tolerable but should be a deliberate choice, not drift.

---

## 3. Repository Layout

Target state after Phase 0:

```
robo-papyro/
├── pyproject.toml                  # workspace root, no code
├── uv.lock                         # single lockfile for the whole workspace
├── .gitignore
├── .python-version
├── README.md                       # workspace overview
├── ROADMAP.md
├── AGENTS.md                       # rewritten for the workspace layout
├── LICENSE
├── .github/workflows/ci.yml        # matrix over packages + license gate
├── dev-notes/
├── docs/
│   ├── specs/
│   │   ├── robo-papyro-spec.md     # this document
│   │   ├── rp-docx-spec.md
│   │   └── rp-pdf-spec.md          # the original pdfx-spec.md, renamed
│   └── ...
├── packages/
│   ├── rp-core/
│   │   ├── pyproject.toml
│   │   ├── src/rp_core/
│   │   │   ├── __init__.py
│   │   │   ├── errors.py           # exception hierarchy + exit-code mapping
│   │   │   ├── models.py           # Capability, ErrorEnvelope
│   │   │   ├── pages.py            # 1-based page-spec parsing (moved from pdfx)
│   │   │   ├── binaries.py         # soffice / pdftoppm discovery + invocation
│   │   │   ├── render.py           # any-file → PNG pipeline
│   │   │   ├── doctor.py           # capability report
│   │   │   └── clikit.py           # shared typer conventions
│   │   └── tests/
│   ├── rp-pdf/
│   │   ├── pyproject.toml
│   │   ├── src/rp_pdf/
│   │   └── tests/
│   ├── rp-docx/                    # created in Phase 1
│   └── robo-papyro/
│       ├── pyproject.toml
│       ├── src/robo_papyro/
│       │   ├── __init__.py
│       │   └── cli.py              # `rp` dispatcher
│       └── tests/
└── templates/                      # corporate .dotx / .docx style templates
    └── README.md                   # provenance + owner per template
```

### Workspace configuration

Root `pyproject.toml` — no code, no `[project]` section beyond metadata:

```toml
[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["pytest>=8", "pytest-cov", "ruff"]

[tool.ruff]
# workspace-wide lint config lives here
[tool.pytest.ini_options]
# workspace-wide test config lives here
```

Each member declares workspace dependencies explicitly — do not rely on inheritance:

```toml
# packages/rp-docx/pyproject.toml
[project]
name = "rp-docx"
dependencies = ["rp-core", "python-docx", "mammoth", "typer", "pydantic", "Pillow"]

[project.scripts]
rp-docx = "rp_docx.cli:app"

[project.entry-points."robo_papyro.commands"]
docx = "rp_docx.cli:app"

[tool.uv.sources]
rp-core = { workspace = true }
```

`uv sync` at the root installs everything editable. `uv build --package rp-docx` produces a wheel with a normal version-pinned `rp-core` requirement.

---

## 4. `rp-core` Specification

### 4.1 `errors.py`

```python
class RoboPapyroError(Exception):
    exit_code: int = 1

class InputError(RoboPapyroError):            # bad args, bad page spec    -> 1
class MissingDependencyError(RoboPapyroError):  # soffice/pdftoppm absent  -> 2
    binary: str
    install_hint: str
class CorruptFileError(RoboPapyroError):      # unreadable/unsupported     -> 3
class ConversionError(RoboPapyroError):       # external tool failed       -> 3
```

Every error carries `.to_envelope() -> ErrorEnvelope` for `--json` output. A raw `FileNotFoundError` from a subprocess must never reach the user.

### 4.2 `models.py`

```python
class Capability(BaseModel):
    name: str                 # "soffice" | "pdftoppm"
    available: bool
    version: str | None
    path: Path | None
    install_hint: str

class ErrorEnvelope(BaseModel):
    error: ErrorDetail        # type, message, hint, exit_code
```

### 4.3 `pages.py` — moved verbatim from pdfx

1-based inclusive page-spec parsing: `"3"`, `"1-5"`, `"1,3,7-9"`, `"-4"`, `"7-"`. Returns `list[int]`. Already written and tested — **move the module and its tests, do not rewrite.**

### 4.4 `binaries.py`

```python
find_binary(name: str) -> Path | None
require_binary(name: str) -> Path              # raises MissingDependencyError
run_binary(path: Path, args: list[str], *, timeout: int = 120) -> CompletedProcess
soffice_convert(source: Path, to: str, outdir: Path) -> Path
```

**`soffice_convert` requirements:**
- Always pass `-env:UserInstallation=file:///tmp/robo-papyro-<uuid4>` and clean up the profile dir afterward. Parallel invocations sharing a profile collide silently and return success with no output file — the worst failure mode in the pipeline, and agents parallelize.
- Always pass `--headless --norestore --invisible`.
- Verify the expected output file exists after the call. A zero exit code is not sufficient evidence of success — raise `ConversionError` if the file is missing.
- Enforce a timeout. LibreOffice hangs indefinitely on some malformed inputs.

### 4.5 `render.py`

```python
render_pages(source: Path, output_dir: Path, *, dpi: int = 150,
             pages: str | None = None, fmt: str = "png") -> list[Path]
```

If `source` is already `.pdf`, go straight to `pdftoppm`. Otherwise route through `soffice_convert(..., to="pdf")` into a temp dir first. `pages` is parsed by `pages.py`. Both `rp-pdf render` and `rp-docx render` become one-line delegations.

### 4.6 `clikit.py`

Shared typer conventions so the CLIs cannot drift:
- `json_option` — the standard `--json` flag definition
- `emit(model, as_json: bool)` — dump pydantic to stdout as JSON, or a human-readable table
- `handle_errors` decorator — catches `RoboPapyroError`, writes `ErrorEnvelope` to stderr when `--json`, exits with `err.exit_code`
- `doctor_command(*capabilities)` — factory producing a `doctor` subcommand for any CLI

### 4.7 Exit codes (all CLIs)

`0` success · `1` user/input error · `2` missing external dependency · `3` corrupt or unsupported file.

---

## 5. `rp-pdf` Migration

`rp-pdf` keeps its public API and CLI surface unchanged apart from the rename. This is a refactor, not a redesign.

**Moves out to `rp-core`:**
- `pages.py` and its tests
- poppler / `pdftoppm` invocation → `binaries.py`
- `render_pages` body → `render.py`; `rp_pdf.render_pages` becomes a thin delegation
- error classes → `errors.py`, subclassed in `rp_pdf` only where PDF-specific context is needed
- CLI `--json` handling and exit codes → `clikit.py`

**Stays:** everything pypdf / pdfplumber / pdf2image-specific, all models in `rp_pdf/models.py`, the whole command surface.

**Acceptance test:** the existing pdfx test suite passes with no changes beyond import paths and the package rename.

---

## 6. The `rp` Umbrella CLI

`robo-papyro` is a meta-distribution: it depends on `rp-core`, `rp-pdf`, and `rp-docx`, and provides a single `rp` command that dispatches to each.

**Discovery, not imports.** `robo_papyro/cli.py` enumerates the `robo_papyro.commands` entry-point group via `importlib.metadata` and registers each discovered typer app as a subcommand. It must not import `rp_pdf` or `rp_docx` directly.

Consequences, all of them desirable:
- `rp pdf index FILE` and `rp-pdf index FILE` are the same code path
- If only `rp-pdf` is installed, `rp` exposes just `pdf` and says so in `--help`
- Adding `rp-xlsx` later requires no change to `robo_papyro`
- A broken leaf package degrades to a warning in `rp --help` rather than breaking the whole CLI

`rp doctor` aggregates capability reports across all discovered subcommands.

Build this at the end of Phase 0, with only `rp-pdf` registered, so the discovery mechanism is proven before a second leaf exists.

---

## 7. Licensing (repo-wide)

Permissive licenses only. Copyleft in the dependency graph is a blocker in this environment.

**Approved:** python-docx (MIT), lxml (BSD-3), mammoth (BSD-2), pypdf (BSD-3), pdfplumber (MIT), pdf2image (MIT), openpyxl (MIT), python-pptx (MIT), typer (MIT), pydantic (MIT), Pillow (MIT-CMU), pytest/ruff (MIT).

**Forbidden:** `docxtpl` (LGPL-2.1-only), `pandoc` (GPL), `PyMuPDF`/`fitz` (AGPL), Aspose/Spire (commercial).

**Subprocess-only external binaries** — no linkage, no license propagation, both optional:

| Binary | License | Needed for |
|---|---|---|
| LibreOffice (`soffice`) | MPL-2.0 | `convert`, `render` of Office formats |
| `pdftoppm` (poppler-utils) | GPL-2.0 | `render` |

Any code path requiring an external binary must sit behind a capability check and raise `MissingDependencyError` with install instructions.

**CI gate:** a job that fails the build if a package outside the approved list appears in `uv.lock`.

---

## 8. Phase 0 — Execution Plan

Starting state: a new `robo-papyro` repo with two commits — the pdfx source verbatim at root, then the spec documents at root.

Work in this order, running the existing test suite after each structural step:

**Step 1 — Workspace scaffold.**
Create the root `pyproject.toml` per §3 (workspace members, dev dependency group, shared ruff/pytest config). Create `packages/`, `docs/specs/`, and `templates/` with a placeholder `README.md` recording that templates are pending.

**Step 2 — Relocate the existing package.**
`git mv` the pdfx tree into `packages/rp-pdf/`: `src/pdfx/` → `packages/rp-pdf/src/rp_pdf/`, `tests/` → `packages/rp-pdf/tests/`, and the existing `pyproject.toml` → `packages/rp-pdf/pyproject.toml`. Move `pdfx-spec.md` → `docs/specs/rp-pdf-spec.md` and this document plus `rp-docx-spec.md` → `docs/specs/`. Leave `.gitignore`, `.python-version`, `README.md`, `ROADMAP.md`, `AGENTS.md`, and `dev-notes/` at root.

**Step 3 — Rename.**
`pdfx` → `rp_pdf` throughout imports, `pdfx` → `rp-pdf` for the CLI entry point and distribution name. Update the moved `pyproject.toml`: strip dev dependencies and shared tool config (those live at root now), set `[project.scripts] rp-pdf = "rp_pdf.cli:app"`, and add the `robo_papyro.commands` entry point. Delete the old `uv.lock` and regenerate with `uv sync` at root. Confirm the suite passes and `rp-pdf --help` works.

**Step 4 — Create `rp-core`.**
Scaffold `packages/rp-core/` per §3 with no code beyond empty modules, wired as a workspace dependency of `rp-pdf`.

**Step 5 — Extract shared modules.**
Move, do not rewrite, in this order, running the `rp-pdf` suite after each:
1. `pages.py` and its tests → `rp_core/pages.py`
2. error classes → `rp_core/errors.py` per §4.1
3. poppler invocation → `rp_core/binaries.py` per §4.4
4. `render_pages` body → `rp_core/render.py` per §4.5
5. CLI `--json` handling and exit codes → `rp_core/clikit.py` per §4.6

Replace each moved implementation in `rp_pdf` with a thin delegation.

**Step 6 — New `rp-core` behavior.**
Write tests in `packages/rp-core/tests/` for the capabilities that did not exist before: `soffice_convert`'s `UserInstallation` isolation, output-file verification, and timeout handling; `require_binary` raising `MissingDependencyError`; `doctor` output. Mock the subprocess — do not require LibreOffice to be installed.

**Step 7 — Umbrella CLI.**
Create `packages/robo-papyro/` per §6 with entry-point discovery. Verify `rp pdf index FILE` and `rp-pdf index FILE` produce identical output, and that `rp --help` lists only what is installed.

**Step 8 — Docs and agent instructions.**
Rewrite `AGENTS.md` for the workspace layout: where packages live, the one-way dependency rule, the "import from `rp-core`, don't reimplement" rule, how to run tests per package, and the approved/forbidden license lists. Update `README.md` and `ROADMAP.md` to describe the suite rather than a single tool.

**Step 9 — CI.**
Add `.github/workflows/ci.yml`: a matrix over package directories running ruff and pytest, plus the license gate from §7.

**Definition of done:** `uv sync` succeeds from a clean checkout; the full suite passes; `rp --help`, `rp doctor`, `rp pdf --help`, and `rp-pdf --help` all work; no package outside the approved list appears in `uv.lock`.

---

## 9. Phasing

| Phase | Scope | Driving doc |
|---|---|---|
| **0** | Workspace scaffold, rename, extract `rp-core`, `rp` umbrella | This document §8 |
| **1** | `rp-docx`: templates, docx read/write/template, CLI | `rp-docx-spec.md` §10 |
| **2** | FastMCP servers for `rp-pdf` and `rp-docx`; skills in `skills/` | TBD |
| **3** | `rp-xlsx` (openpyxl) and `rp-pptx` (python-pptx), same core/CLI split | TBD |

---

## 10. Constraints for All Phases

- **Permissive licenses only.** If a forbidden dependency seems necessary, stop and ask rather than adding it.
- **Core logic never prints and never imports typer.** Library functions return pydantic models; CLI modules do all formatting.
- **One-way dependencies.** `rp-core` imports no leaf package. Leaf packages do not import each other.
- **Don't reimplement `rp-core`.** Page-spec parsing, binary discovery, rendering, error envelopes, and exit codes have exactly one implementation.
- **All user-facing indices are 1-based** — pages, paragraphs, tables, sections.
- **Never overwrite an input file** unless `--in-place` is passed explicitly.
- **No external binary is required** for any core read/write path.

---

## 11. Open Decisions

1. **Import-name rename** (§2) — confirm or veto before Phase 0 starts.
2. **Template provenance** — `templates/README.md` needs an owner and canonical location per template. If the source of truth is SharePoint, decide whether the repo holds a synced copy or a pointer; a stale letterhead is worse than a missing one.
3. **Archiving `w528-pdf-extraction-toolkit`** — do it after Phase 0 merges and the suite is green in the new repo, not before.
