# robo-papyro — Workspace & Architecture Specification

**Version:** 1.6
**Status:** Phases 0, 0.5, 1, 2, and 2.5 complete · Phase 3 (`rp-xlsx`) future work
**Companion documents:** `rp-docx-spec.md` v1.3 · `rp-pptx-spec.md` v1.0 · `rp-mcp-spec.md` v1.0 (all implemented — see the matching notes in `dev-notes/`)

**Changes from v1.5:** §1 and §6 reverse the packaging decision v1.5 recorded — `rp-mcp` is a **runtime dependency** of `robo-papyro`, not the `mcp` extra, so a published install has `rp mcp`. The extra kept an ASGI stack away from CLI-only users; it also kept the agent integration behind a step nobody takes, which is the wrong trade for a suite built for agentic document work. §6 states the measured cost and the pin that now rides on it. §7.1's reasoning is untouched: the license gate seeds the base install path from every workspace member, so this changes nothing the gate sees.

**Changes from v1.4:** §1, §3, and §9 record Phase 2 (`rp-mcp`) as complete and add the distribution, its package tree, and its spec · §9's Phase 2 row names `rp-mcp-spec.md` where it said `TBD` · §11.2 corrects what a separate distribution actually buys: the license gate computes the base install path from *every* workspace member, so `rp-mcp` puts the MCP SDK tree into it, and §7.1 holds because the SDK is floored at 2.x (1.x reaches `certifi`/MPL-2.0 through `httpx`) rather than because the distribution boundary excludes it · §7 adds the `mcp` 2.x tree to the approved set · §1 and §6 correct "installs the others": `robo-papyro` installs the document leaves, and `rp-mcp` is opt-in via the `mcp` extra, which is what the published wheel actually declares.

**Changes from v1.3:** §1, §3, §9, and §10 record Phase 2.5 (`rp-pptx`) as complete rather than specified, and Phase 2 as the sole remaining "next" phase, now scoped to include `rp-pptx`'s MCP server alongside `rp-pdf`'s and `rp-docx`'s · §1 and §4 correct "`rp-core` knows nothing about PDF or OOXML" to describe the actual boundary: `rp_core.ooxml` and `rp_core.markdown` hold generic, format-agnostic OPC/OOXML and Markdown-parsing mechanics, promoted out of `rp-docx` once `rp-pptx` needed the same grammar (`rp-pptx-spec.md` §12 step 2); WordprocessingML/PresentationML knowledge itself stays in the leaves · §3's layout gains `rp_core`'s `ooxml.py`/`markdown.py` and the `rp-pptx` package tree.

**Changes from v1.2:** §9 inserts Phase 2.5 (`rp-pptx`), promoted out of the Phase 3 bundle now that Phase 1 has proven the leaf pattern it reuses; Phase 3 narrows to `rp-xlsx` · §1 and §3 add the `rp-pptx` distribution and its spec · §7 adds `XlsxWriter` (BSD-2-Clause), python-pptx's dependency, to the approved list.

**Changes from v1.1:** §3 corrects the pytest import-mode setting, which was given as an ini key that does not exist · §4.3 states the semantics of the open-ended range forms it already listed · §4.6 corrects the `emit` signature · §7.1 defines "base install path" and requires the gate to enforce §7.1 in both directions · §8 adds step 8 and moves the base-path check from manual verification to gate enforcement · §9 records `rp-mcp` as a Phase 2 distribution · §11.2 notes what keeps the blast radius small.

**Changes from v1.0:** §2 settled and expanded to record the full rename surface · §4.1 adopts `ErrorEnvelope` as the single error contract · §4.3 splits page parsing between core and leaf · §4.4 revises timeout policy and narrows the binary split · §4.5 introduces `rasterize` as the primitive beneath `render_pages` · §4.6 switches to JSON-by-default and drops the opt-in path · §5 rewritten to describe what was actually extracted · §7 adds a weak-copyleft policy · §8 marked complete and replaced by a Phase 0.5 plan · §10 adds three enforced workspace invariants.

---

## 1. Overview

`robo-papyro` is a document tooling suite giving agentic coding tools a stable, scriptable interface to PDF and Office document formats. It is a single repository containing several independently versioned Python distributions.

| Distribution | Import name | CLI | Purpose |
|---|---|---|---|
| `rp-core` | `rp_core` | — | Shared infrastructure: binary discovery, rasterization primitive, error/exit-code contract, range parsing, generic OPC/OOXML mechanics, shared Markdown parsing, CLI conventions |
| `rp-pdf` | `rp_pdf` | `rp-pdf` | PDF read/extract/render |
| `rp-docx` | `rp_docx` | `rp-docx` | Word document read/write/edit |
| `rp-pptx` | `rp_pptx` | `rp-pptx` | PowerPoint deck read/write/edit (Phase 2.5) |
| `rp-mcp` | `rp_mcp` | `rp-mcp` | MCP servers exposing the three leaves to agents (Phase 2) |
| `robo-papyro` | `robo_papyro` | `rp` | Meta-distribution: installs the whole suite, `rp-mcp` included, and provides the umbrella `rp` dispatcher |

`rp-mcp` is the one distribution that imports the leaves. It is a consumer sitting above them, not a peer: nothing in `rp-pdf`, `rp-docx`, or `rp-pptx` imports `rp_mcp`, so the dependency direction stays one-way. Its own spec is `rp-mcp-spec.md`.

**Rationale for one repo, several distributions:** corporate overhead (license scan, SBOM, security review, CI onboarding) is charged per repo. Workspace path dependencies resolve with nothing but git — no internal package index required. Cross-cutting changes land atomically in one PR. Separate distributions keep version histories independent and keep `rp-pdf` users from installing `python-docx`.

**Dependency direction is strictly one-way.** Leaf packages never import each other. Only `robo-papyro` depends on the leaves, and it does so through entry-point discovery rather than direct imports. `rp-core` knows nothing PDF- or format-specific — but it does own the mechanics that are genuinely generic across OOXML formats (package zip read/repack, content-type rewriting, the compiled-XPath helper) and across Markdown (the shared block/inline parser), promoted out of `rp-docx` once `rp-pptx` needed the same grammar (§9, `rp-pptx-spec.md` §12 step 2). WordprocessingML and PresentationML knowledge itself never leaves `rp-docx` and `rp-pptx` respectively — see §4 note below.

### Non-goals
- Rendering fidelity guarantees — LibreOffice does the converting; we don't chase pixel parity
- Collaborative/real-time editing
- Legacy binary `.doc` support (not present in the target corpus)
- Google Docs / Office 365 API integration

---

## 2. Naming (settled in Phase 0)

The former `pdfx` import name and CLI are now `rp_pdf` and `rp-pdf`. The rename was taken to the full user-facing surface, on the grounds that a fresh repo with no external consumers is the only cheap moment:

| Was | Now |
|---|---|
| `PDFX_VLM_*`, `PDFX_CACHE_DIR`, `PDFX_CONFIG` | `RP_PDF_VLM_*`, `RP_PDF_CACHE_DIR`, `RP_PDF_CONFIG` |
| `PDFX_POPPLER_PATH` | `RP_POPPLER_PATH` (suite-wide, lives in `rp-core`) |
| `pdfx.toml` | `rp-pdf.toml` |
| `~/.config/pdfx/`, `~/.cache/pdfx/` | `~/.config/rp-pdf/`, `~/.cache/rp-pdf/` |
| `PdfxError` | `RpPdfError` |

**Convention going forward:** suite-wide settings are `RP_*` and live in `rp-core`; package-specific settings are `RP_PDF_*` / `RP_DOCX_*` and live in the leaf. `rp-docx` follows this without exception.

---

## 3. Repository Layout

```
robo-papyro/
├── pyproject.toml                  # workspace root, no code
├── uv.lock                         # single lockfile for the whole workspace
├── .gitignore
├── .python-version
├── README.md
├── ROADMAP.md
├── AGENTS.md                       # workspace rules for agentic tooling
├── LICENSE
├── .github/workflows/ci.yml        # lint, test matrix, license gate, smoke
├── ci/
│   ├── allowed-packages.toml       # license allowlist + recorded reasoning
│   └── tests/
├── dev-notes/
├── docs/
│   ├── specs/
│   │   ├── robo-papyro-spec.md     # this document
│   │   ├── rp-docx-spec.md
│   │   ├── rp-pdf-spec.md
│   │   └── rp-pptx-spec.md
│   └── usage.md
├── packages/
│   ├── rp-core/
│   │   ├── pyproject.toml
│   │   ├── src/rp_core/
│   │   │   ├── __init__.py
│   │   │   ├── errors.py           # exception hierarchy + envelope conversion
│   │   │   ├── models.py           # Capability, ErrorDetail, ErrorEnvelope
│   │   │   ├── ranges.py           # generic 1-based range parsing
│   │   │   ├── binaries.py         # discovery + guarded invocation
│   │   │   ├── render.py           # rasterize primitive + render_pages wrapper
│   │   │   ├── doctor.py           # capability report
│   │   │   ├── ooxml.py            # generic OPC/OOXML zip, content-type, xpath mechanics (added Phase 2.5)
│   │   │   ├── markdown.py         # shared Markdown block/inline parser (added Phase 2.5)
│   │   │   └── clikit.py           # shared typer conventions
│   │   └── tests/
│   ├── rp-pdf/
│   │   ├── pyproject.toml
│   │   ├── src/rp_pdf/
│   │   └── tests/
│   ├── rp-docx/                    # Phase 1 — complete
│   ├── rp-pptx/                    # Phase 2.5 — complete
│   ├── rp-mcp/                     # Phase 2 — complete
│   │   ├── pyproject.toml
│   │   ├── src/rp_mcp/             # sandbox, tools, {pdf,docx,pptx}.py, server, cli
│   │   └── tests/
│   └── robo-papyro/
│       ├── pyproject.toml
│       ├── src/robo_papyro/
│       └── tests/
├── skills/                         # agent skills for the three CLIs (Phase 2)
└── templates/                      # corporate .dotx/.docx and .potx/.pptx style templates
    └── README.md                   # provenance + owner per template
```

### Workspace configuration

Root `pyproject.toml` holds no code. It carries workspace members, the dev dependency group, and shared lint/test configuration:

```toml
[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["pytest>=8,<9", "pytest-cov", "ruff==<pinned>"]

[tool.pytest.ini_options]
addopts = ["--import-mode=importlib"]   # see §10, invariant 3

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
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

---

## 4. `rp-core` Specification

### 4.1 `errors.py` — one error contract for the suite

```python
class RoboPapyroError(Exception):
    exit_code: int = 1
    def to_envelope(self) -> ErrorEnvelope: ...

class InputError(RoboPapyroError):              # bad args, bad range spec   -> 1
class MissingDependencyError(RoboPapyroError):  # external binary absent     -> 2
    binary: str
    install_hint: str
class CorruptFileError(RoboPapyroError):        # unreadable/unsupported     -> 3
class ConversionError(RoboPapyroError):         # external tool failed       -> 3
class SubprocessTimeout(RoboPapyroError):       # external tool timed out    -> 3
```

Leaf packages subclass these where format-specific context helps (`RpPdfError`, `RpDocxError`), but must not introduce a parallel hierarchy.

**`ErrorEnvelope` is the single serialized error shape across every CLI in the suite.** `rp-pdf`'s legacy flat `{"error": "msg"}` payload is retired in Phase 0.5.

```python
class ErrorDetail(BaseModel):
    type: str          # "InputError", "MissingDependencyError", ...
    message: str
    hint: str | None
    exit_code: int

class ErrorEnvelope(BaseModel):
    error: ErrorDetail
```

Rationale: the primary consumer is an agent deciding what to do next. A flat string discards the `type` and `exit_code` that the taxonomy in §4.7 exists to expose, and two shapes would force every skill and MCP wrapper to branch on which tool failed. A raw `FileNotFoundError` or `subprocess.TimeoutExpired` must never reach the user.

### 4.2 `models.py`

```python
class Capability(BaseModel):
    name: str                 # "soffice" | "pdftoppm" | "pdftotext"
    available: bool
    version: str | None
    path: Path | None
    install_hint: str
```

Plus `ErrorDetail` and `ErrorEnvelope` from §4.1.

### 4.3 `ranges.py` — generic only

`rp_core.ranges` parses 1-based inclusive integer range specs and nothing else: `"3"`, `"1-5"`, `"1,3,7-9"`, `"-4"`, `"7-"` → `list[int]`. It serves PDF pages, docx sections, pptx slide selection, and a future sheet selection in `rp-xlsx`.

**An omitted endpoint takes the corresponding bound**: `"-4"` is `1..4` and `"7-"` is `7..count`. These two forms were listed here from v1.0 but never implemented — v1.0 described them as part of a module it was directing us to move rather than rewrite, and the module had never accepted them. Phase 0.5 adds them. A bare `"-"` is rejected: it would mean `1..count`, which `"all"` already says, so it is far likelier a typo, and silently selecting an entire document is an expensive way to discover that. Leaf packages that resolve a spec against their own naming — `rp_pdf.pages` against page labels — support the same two forms, so a spec does not change meaning depending on whether a document happens to be labelled.

**PDF page-label resolution stays in `rp-pdf`.** v1.0 §4.3 said to move `pages.py` wholesale; Phase 0 did so and correctly flagged that `parse_page_labels` is PDF-domain logic sitting in a format-agnostic core. Phase 0.5 splits the module: the generic parser becomes `rp_core.ranges`, and label handling returns to `rp_pdf.pages`. Do this before `rp-docx` imports the module and the misplacement calcifies.

### 4.4 `binaries.py` — discovery and guarded invocation

```python
find_binary(name: str) -> Path | None
require_binary(name: str) -> Path              # raises MissingDependencyError
run_binary(path: Path, args: list[str], *,
           timeout: int | None = None) -> CompletedProcess
soffice_convert(source: Path, to: str, outdir: Path, *,
                timeout: int = 300) -> Path
```

**Discovery only.** `rp-core` locates binaries and wraps invocation with timeout and error handling. It does not know any tool's flags. `pdftotext`'s `-f/-l/-enc/-upw` handling and form-feed page splitting live in `rp-pdf`, where the PDF-specific knowledge belongs. v1.0 §5 implied otherwise; Phase 0 drew the line correctly and this revision ratifies it.

**Timeout policy.** No subprocess may run unbounded. `timeout=None` resolves to `RP_SUBPROCESS_TIMEOUT` if set, otherwise **600 seconds** — generous enough for a large legitimate `pdftotext` run, bounded enough that a hang surfaces. v1.0's 120s default was too aggressive for real PDFs and was correctly rejected during Phase 0; unbounded is nonetheless not an acceptable end state, because a hung subprocess behind an MCP tool call blocks an agent with no signal and no Ctrl-C. Timeouts raise `SubprocessTimeout`, never `subprocess.TimeoutExpired`.

**`soffice_convert` requirements:**
- Always pass `-env:UserInstallation=file:///tmp/robo-papyro-<uuid4>` and clean up the profile dir afterward. Parallel invocations sharing a profile collide silently and return success with no output file — the worst failure mode in the pipeline, and agents parallelize.
- Always pass `--headless --norestore --invisible`.
- Verify the expected output file exists after the call. A zero exit code is not sufficient evidence of success — raise `ConversionError` if the file is missing.

### 4.5 `render.py` — primitive plus convenience wrapper

```python
rasterize(pdf: Path, output_dir: Path, *, dpi: int = 150,
          pages: list[int] | None = None,
          name_for: Callable[[int], str] | None = None,
          fmt: str = "png") -> list[Path]

render_pages(source: Path, output_dir: Path, *, dpi: int = 150,
             pages: str | None = None, fmt: str = "png") -> list[Path]
```

`rasterize` is the primitive: physical page numbers only, caller-injected file naming, one pdf2image call site. Leaf packages build on it when they need control over numbering or output names.

`render_pages` is a convenience wrapper for the simple case — parse a range spec via `ranges.py`, rasterize, return paths. If `source` is not a PDF, route through `soffice_convert(..., to="pdf")` into a temp dir first.

`rp-pdf`'s own render command resolves page *labels*, names files by label, and returns `RenderedPage` models carrying both numbering schemes. None of that can live in a format-agnostic core, so it wraps `rasterize` in roughly twenty lines rather than delegating in one. This is expected, not a defect — v1.0 §4.5 was wrong to describe it as a thin delegation.

`rp-docx` and `rp-pptx` both use `render_pages` directly and need nothing more.

### 4.6 `clikit.py` — JSON by default

Shared typer conventions so the CLIs cannot drift:

- `plain_option` — the standard `--plain` flag definition
- `emit(model, plain: bool = False)` — JSON to stdout by default; human-readable table when `--plain`. The default is part of the contract: a caller that passes no flag must get JSON without having to think about it
- `handle_errors` decorator — catches `RoboPapyroError`, writes `ErrorEnvelope` to stderr, exits with `err.exit_code`
- `doctor_command(*capabilities)` — factory producing a `doctor` subcommand for any CLI

**The suite is JSON-by-default with `--plain` opt-out**, matching `rp-pdf`'s existing shape. v1.0 specified `--json` opt-in for `rp-docx`, which would have made the two tools differ on the shape of every *successful* call — a worse inconsistency for agent consumers than differing error payloads, since it affects the common path rather than the exception path. The unused opt-in `json_option` and `emit(as_json=...)` variants written in Phase 0 are deleted in Phase 0.5 rather than carried as dead code.

### 4.7 Exit codes (all CLIs)

`0` success · `1` user/input error · `2` missing external dependency · `3` corrupt file, failed conversion, or timeout.

---

## 5. `rp-pdf` — What Was Extracted

For reference; Phase 0 is complete. `rp-pdf` shed five concerns to `rp-core` and gained a `doctor` command.

| Concern | Disposition |
|---|---|
| Range parsing | Moved to `rp_core.ranges`; PDF label logic returns to `rp_pdf.pages` in Phase 0.5 |
| Error classes | Moved to `rp_core.errors`; `RpPdfError` subclasses it |
| Binary discovery | Moved to `rp_core.binaries` |
| Rasterization | Moved to `rp_core.render.rasterize`; `rp-pdf` wraps it |
| CLI error handling and exit codes | Moved to `rp_core.clikit` |
| `pdftotext` invocation and flags | **Stayed** in `rp-pdf` — PDF-specific |
| pypdf / pdfplumber logic, `rp_pdf/models.py`, command surface | **Stayed** |

`rp-pdf`'s public behavior is unchanged apart from the rename surface in §2, the exit-code taxonomy in §4.7, and the error payload change in §4.1.

---

## 6. The `rp` Umbrella CLI

`robo-papyro` is a meta-distribution depending on `rp-core`, `rp-pdf`, `rp-docx`, `rp-pptx`, and `rp-mcp`, providing a single `rp` command that dispatches to each.

**`rp-mcp` is a runtime dependency, not an extra.** `pip install robo-papyro` installs the whole suite, and `rp mcp` appears through the same entry-point discovery as every other subcommand. Phase 2 shipped it as the `mcp` extra and this reverses that: an extra keeps the MCP SDK away from users who only run CLIs, but it puts the agent integration behind a step most people never discover, and the agent integration is what this suite is for. `rp-mcp`'s own "deliberate second install" framing therefore describes the *leaves* — `uv pip install rp-pdf` still pulls nothing MCP-related — and no longer describes the umbrella.

The cost is real and stated rather than hidden. A published install goes from **33 packages to 54 on Linux and macOS**, and from 34 to 56 on Windows, which additionally resolves `pywin32` and `colorama`. (56 is also the number `ci/license_gate.py` prints, but that figure is the platform *union* — the graph with every marker taken as true — and is not what any one machine installs. The two agreeing is a coincidence of this particular tree, not the same measurement.) The additions include an ASGI stack — `starlette`, `uvicorn`, `sse-starlette` — that a CLI-only user never executes.

**One addition is compiled, not pure Python.** `rpds-py`, reached through `jsonschema`, is a Rust extension and needs a toolchain on any platform it publishes no wheel for. This matters here because making `rp-mcp` unconditional changes install *risk* and not only package count. It is not a new kind of exposure — `lxml`, `pillow`, `cryptography`, `pypdfium2` and `pydantic-core` are all compiled and all predate this change — but it is one more, and the earlier draft of this section claiming the additions were "all pure Python" was simply wrong.

None of the additions are weak copyleft, and installing a server is not running one — `rp-mcp` offers stdio only and starts nothing implicitly.

Two things now ride on this that did not before, and both are asserted rather than described:

- **The packaging shape.** `TestPackagingContract` in `packages/robo-papyro/tests/test_umbrella_cli.py` reads the manifest and requires `rp-mcp` among the runtime dependencies *and* no `mcp` extra — a workspace `uv sync` installs every member regardless of what any member declares, so nothing else in the suite would notice this drifting.
- **The `mcp` pin.** `rp-mcp`'s `mcp>=2.0.0,<3` now constrains every `robo-papyro` install rather than only people who opted in. `packages/rp-mcp/tests/test_packaging.py` asserts both ends of it, and `.github/dependabot.yml` exists so a new major arrives as a pull request instead of going unnoticed — an upper bound is a bet that somebody will look, and nothing here was making that bet good.

**Discovery, not imports.** `robo_papyro/cli.py` enumerates the `robo_papyro.commands` entry-point group via `importlib.metadata` and registers each discovered typer app as a subcommand. It must not import `rp_pdf`, `rp_docx`, or `rp_pptx` directly — enforced by a test that walks the module's AST.

Consequences, all desirable:
- `rp pdf index FILE` and `rp-pdf index FILE` are the same code path, asserted by CI
- If only `rp-pdf` is installed, `rp` exposes just `pdf` and says so in `--help`
- Adding `rp-xlsx` later requires no change to `robo_papyro`
- A broken leaf degrades to a warning in `rp --help` rather than breaking the CLI

`rp doctor` aggregates capability reports across all discovered subcommands.

---

## 7. Licensing (repo-wide)

**Approved (fully permissive):** python-docx (MIT), lxml (BSD-3), mammoth (BSD-2), pypdf (BSD-3), pdfplumber (MIT), pdf2image (MIT), openpyxl (MIT), python-pptx (MIT), XlsxWriter (BSD-2, enters as python-pptx's dependency), typer (MIT), pydantic (MIT), Pillow (MIT-CMU), pytest/ruff (MIT).

**Approved for `rp-mcp` (Phase 2):** `mcp` 2.x (MIT) and its tree — `mcp-types` (MIT), `httpx2`/`httpcore2` (BSD-3), `truststore` (MIT), `starlette`/`sse-starlette`/`uvicorn`/`click` (BSD-3), `jsonschema`/`referencing`/`rpds-py`/`jsonschema-specifications`/`attrs`/`PyJWT` (MIT), `opentelemetry-api`/`python-multipart` (Apache-2.0), `pywin32` (PSF-2.0, Windows only). Each license was read from the project's published metadata, not inferred from a sibling. **The 2.x floor is a §7.1 constraint**: `mcp` 1.x reaches `certifi` (MPL-2.0) through `httpx`, which the base-path check below rejects.

**Forbidden:** `docxtpl` (LGPL-2.1-only), `pandoc` (GPL), `PyMuPDF`/`fitz` (AGPL), Aspose/Spire (commercial).

### 7.1 Weak-copyleft policy

MPL-2.0 and comparable file-level copyleft are **permitted for unmodified transitive dependencies** and **barred from the base install path**. This ratifies the Phase 0 allowlisting of `certifi` (MPL-2.0) and `tqdm` (`MPL-2.0 AND MIT`) as explicit policy rather than an undocumented exception.

Reasoning:
- MPL-2.0 obligations attach to distributing *modified* copies of covered files. The suite does neither.
- `tqdm`'s expression is `AND`, not `OR` — a mixture, meaning MPL genuinely applies to part of it. It cannot be treated as MIT. It is permitted under this policy, not under the approved list.
- Both enter only through the optional `ai` extra (`openai` → `httpx` → `certifi`; `openai` → `tqdm`), and both were still reachable only that way after Phase 2 added `rp-mcp` — but only because `mcp` was taken at 2.x. The gate asserts this rather than any count recorded here by hand; it prints the base path's real size on every run.

**Requirements:** every weak-copyleft entry in `ci/allowed-packages.toml` records the license, the path by which it enters, and why it is acceptable. A weak-copyleft package appearing in the base install path fails the gate regardless of allowlisting. Strong copyleft (GPL, LGPL, AGPL) is never allowlisted as a Python dependency.

**"Base install path"** means the union of the runtime dependencies of the published distributions, resolved with no optional extras and excluding `dependency-groups.dev`. It is what someone gets from `uv pip install rp-core rp-pdf` with no `--extra`, and it is the only part of the graph this policy is strict about.

The license gate enforces §7.1 **in both directions**:

1. **Base path is clean.** No weak-copyleft package may appear in the base install path. Allowlisting does not exempt it — the allowlist answers "what license is this?", not "may it ship in the default install?".
2. **Tags are true.** Every allowlist entry tagged `extra:<name>` must be verifiably unreachable from the base path. This fails independently of whether the package is otherwise allowed, so a tag going stale is caught even when nothing else is wrong.

Tags in `ci/allowed-packages.toml` are **checked claims about the dependency graph, not annotations**. The distinction matters because the graph moves and the comment does not: `certifi` and `tqdm` are acceptable today only because nothing in the base path reaches them, and that is a fact about `uv.lock` rather than about either package.

### 7.2 Subprocess-only external binaries

No linkage, no license propagation. Both optional; every path requiring one sits behind a capability check and raises `MissingDependencyError` with install instructions.

| Binary | License | Needed for |
|---|---|---|
| LibreOffice (`soffice`) | MPL-2.0 | `convert`, `render` of Office formats |
| poppler-utils (`pdftoppm`, `pdftotext`) | GPL-2.0 | rasterization, text extraction |

---

## 8. Phase 0.5 — Remediation Plan

Phase 0 (§8 of v1.0) is complete: 309 tests green on Python 3.11 and 3.13, `rp-core` at 98% coverage, clean-checkout definition of done verified.

Phase 0.5 settles the decisions Phase 0 surfaced, before Phase 1 builds on them. Steps 1–4 must land before `rp-docx` work begins; steps 5–8 are independent and can land any time as separate PRs.

**Step 1 — Adopt `ErrorEnvelope` in `rp-pdf`.**
Retire the flat `{"error": "msg"}` payload. Delete the dual-shape support in `clikit` — one shape, no argument. Update `rp-pdf` tests asserting the old payload. Verify the `2` and `3` exit paths emit correct `type` and `exit_code`.

**Step 2 — Switch `clikit` to JSON-by-default.**
Delete `json_option` and the opt-in `emit` variant. `plain_option` and `emit(model, plain=...)` become the only surface. `rp-pdf` already behaves this way; this makes it the enforced suite convention rather than a leaf's local habit.

**Step 3 — Split `pages.py`.**
Generic range parsing → `rp_core.ranges` per §4.3. PDF page-label resolution → `rp_pdf.pages`. Move tests with their subjects. No behavior change.

**Step 4 — Reconcile specs.**
This document and `rp-docx-spec.md` are revised to v1.1. Confirm `docs/specs/rp-pdf-spec.md` reflects the rename surface, the exit-code taxonomy, and the error payload change.

**Step 5 — Subprocess timeout policy.**
Implement §4.4: `RP_SUBPROCESS_TIMEOUT`, 600s default, `SubprocessTimeout` raised as exit code 3. Apply at the `pdftotext` call site, currently unbounded. Test with a mocked subprocess; do not require a real hang.

**Step 6 — ruff.**
Pin the ruff version in workspace dev deps — the moving implicit default was the root cause of the Phase 0 workaround, and pinning `select` only treated the symptom. Then widen `select` to `["E", "F", "W", "I", "UP", "B"]` in two commits: `--fix` mechanical first, manual remainder second, so review stays tractable.

**Step 7 — Workspace invariants as tests.**
Convert the two `AGENTS.md` notes from Phase 0 into enforced checks per §10.

**Step 8 — Enforce §7.1 in the license gate.**
`ci/license_gate.py` computes the base install path and fails on any weak-copyleft package found there. Separately, assert every extra-tagged allowlist entry is unreachable from the base path, so a tag going stale fails the build. Tag format is `extra:<name>`; `certifi` and `tqdm` become `extra:ai`. Independent of Phase 1, same group as steps 5–7.

**Definition of done:** suite green; `rp-pdf` and `rp-core` emit identical error structure; no `--json` flag remains anywhere in the suite; `rp_core` contains no PDF-specific identifier; base install path in `uv.lock` verified by the gate to be free of weak copyleft.

---

## 9. Phasing

| Phase | Scope | Driving doc | Status |
|---|---|---|---|
| **0** | Workspace, rename, extract `rp-core`, `rp` umbrella | v1.0 §8 | Complete |
| **0.5** | Contract decisions and extraction cleanup | §8 above | Complete |
| **1** | `rp-docx`: templates, docx read/write/template, CLI | `rp-docx-spec.md` §12 | Complete — no house template was needed |
| **2.5** | `rp-pptx`: templates, pptx read/write/template, slide operations, CLI | `rp-pptx-spec.md` §12 | Complete — landed before Phase 2, per `dev-notes/status-robo-papyro-phase-2.5.md`; no house deck was needed |
| **2** | `rp-mcp`: a fourth distribution holding the MCP servers for `rp-pdf`, `rp-docx`, and `rp-pptx`; skills in `skills/` | `rp-mcp-spec.md` | Complete — see `dev-notes/status-robo-papyro-phase-2.md`. "FastMCP" is `MCPServer` in the SDK's 2.x line |
| **3** | `rp-xlsx` (openpyxl) | TBD | Future work |

---

## 10. Constraints for All Phases

- **Permissive licenses only**, per §7. Weak copyleft is transitive-and-optional only, and the license gate proves it rather than trusting a comment. If a forbidden dependency seems necessary, stop and ask.
- **Core logic never prints and never imports typer.** Library functions return pydantic models; CLI modules do all formatting.
- **One-way dependencies.** `rp-core` imports no leaf package and contains no format-specific identifier. Leaf packages do not import each other.
- **Don't reimplement `rp-core`.** Range parsing, binary discovery, rasterization, error envelopes, exit codes, generic OPC/OOXML zip mechanics, and the shared Markdown block/inline parser have exactly one implementation.
- **All user-facing indices are 1-based** — pages, paragraphs, tables, sections, slides.
- **JSON is the default output**; `--plain` is the human opt-out. No `--json` flag exists in the suite.
- **Never overwrite an input file** unless `--in-place` is passed explicitly.
- **No external binary is required** for any core read/write path.
- **No unbounded subprocess.** Every invocation goes through `run_binary` with a resolved timeout.

### Workspace invariants (enforced by tests, not documentation)

1. **Command registration.** `rp-pdf`'s default-action dispatcher parses an unrecognized subcommand as a filename, so any new subcommand must appear in `COMMAND_NAMES` in `cli.py`. This bit the `doctor` command during Phase 0. A test asserts every registered typer command is present in `COMMAND_NAMES`.
2. **No leaf imports in the umbrella.** A test walks `robo_papyro/cli.py`'s AST and fails on any import of a leaf package.
3. **Test module collision.** Same-named test modules in different packages collide under pytest's default prepend import mode — this bit `test_render.py`. Root config sets `addopts = ["--import-mode=importlib"]`; there is no ini key for import mode, so the obvious `importmode = "importlib"` is silently ignored, and the test asserts the *effective* mode rather than the config text. Distinct names remain good practice but are no longer load-bearing. A consequence worth knowing: a test module's directory is no longer on `sys.path`, so test modules share helpers through `conftest.py` fixtures rather than by importing each other.

`AGENTS.md` should reference these tests rather than restate the rules; agents skim prose and run suites.

---

## 11. Open Decisions

1. **Template provenance** — `templates/README.md` needs an owner and canonical location per template. If the source of truth is SharePoint, decide whether the repo holds a synced copy or a pointer; a stale letterhead is worse than a missing one. ~~**This is on the critical path for Phase 1 step 5.**~~ **No longer on any critical path.** Phase 1 shipped without a house template, and the manifest/synthesis loop (`rp-docx-spec.md` §5.2) means CI depends on committed JSON describing a template's shape rather than on the template itself. Still worth answering before the first real template lands — see `templates/README.md` — but nothing is blocked on it.
2. **Compliance sign-off on §7.1** — if anyone outside the team must ratify the weak-copyleft policy, start that now. The fallback if it is rejected is dropping the `ai` extra, not re-architecting. Keeping the fallback that cheap is the point of the §7.1 gate check.

   **Correction (Phase 2).** The second half of that sentence — that putting MCP in its own distribution keeps whatever the SDK drags in "out of the base install path by construction" — is not true as written, and it matters because it reads like a guarantee. The gate computes the base install path from the runtime dependencies of *every* workspace member, so `rp-mcp` being a separate distribution isolates `rp-pdf`'s dependency graph (`uv pip install rp-pdf` still pulls nothing MCP-related) without isolating the gate's input at all. What keeps §7.1 satisfied is the version floor: `mcp` 1.x depends on `httpx` → `certifi` (MPL-2.0), which the gate rejects in the base path and which would also invalidate both `extra:ai` tags; `mcp` 2.x uses `httpx2` + `truststore` and pulls no weak copyleft. `rp-mcp` pins `mcp>=2.0.0,<3` for that reason as much as for the `FastMCP` → `MCPServer` rename.
3. **Archiving `w528-pdf-extraction-toolkit`** — unblocked; do it once Phase 0.5 is green.
