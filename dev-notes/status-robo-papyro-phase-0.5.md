# Status — robo-papyro Phase 0.5

**Date:** 2026-08-05 · **Branch:** `claude/robo-papyro-phase-0.5-nz2gxb` ·
**Driving doc:** [`docs/specs/robo-papyro-spec.md`](../docs/specs/robo-papyro-spec.md) §8

## BLUF

**Phase 0.5 is complete — all eight steps, ten commits.** The suite is at
**382 tests** (from 309), green on Python 3.11 and 3.13, `ruff check` and
`ruff format --check` clean under the widened rule set, and verified from a
clean `git clone` + `uv sync`. Every item in §8's definition of done is met.

Steps 1–7 landed first; review of that work settled the four spec questions
below and added **step 8**, which turns §7.1's base-install-path rule from a
comment into a gate check. Open-ended range forms (`"-4"`, `"7-"`) were
approved and implemented rather than left rejected. Spec revised to v1.2.

Everything is on one branch rather than separate PRs, because the session was
given a single designated branch. It reads in three parts: `3a11548..218366a`
is the contract work (the Phase 1 blockers), `54aad11..bee38c0` is the
independent work, and the last two commits are the review outcomes.

**Three user-visible contracts changed** and will break anyone scripting
against them: the error payload, `doctor`'s default output, and
`rp-pdf markdown --json`. Details in [Behavior changes](#behavior-changes).

## What landed

| Step | Scope | Commit |
|---|---|---|
| 1 | `ErrorEnvelope` as the suite's only error payload | `3a11548` |
| 2 | JSON by default, `--plain` to opt out; no `--json` anywhere | `38beb2f` |
| 3 | `rp_core.ranges` (generic) / `rp_pdf.pages` (labels) split | `cd1af26` |
| 4 | `rp-pdf-spec.md` reconciled to v1.1; ROADMAP updated | `218366a` |
| 5 | `RP_SUBPROCESS_TIMEOUT`, 600s default, `SubprocessTimeout` | `54aad11` |
| 6 | ruff pinned, `select` widened — mechanical, then manual | `c9a2ec0`, `1072cd1` |
| 7 | Workspace invariants as tests; AGENTS.md points at them | `bee38c0` |
| — | Open-ended range forms `"-4"` and `"7-"` (review outcome) | `c7adea2` |
| 8 | §7.1 enforced by the license gate; spec to v1.2 | `e50a07e` |

### Step 1 — one error contract

`clikit.error_handler` lost `envelope`, `stream`, **and** `as_json`. The last
was not named in the step, but it was the third unreachable output mode and
§4.6 describes exactly one behavior; deleting it applies the same reasoning the
step gives for the flat shape. `error_handler(also=...)` survives — it is the
sanctioned way for a leaf to admit a third-party exception, and `rp-docx` will
need it for `python-docx`'s `PackageNotFoundError`.

`rp_core.errors.envelope_for()` is new: it gives a foreign exception the same
envelope shape, so opting one in through `also=` does not reintroduce a second
payload by the back door.

Two things the step did not ask for but the contract needed:

- **The envelope is written after the human-readable message,** so it is the
  *last* line of stderr. Writing it first looked right until the tests ran:
  pypdf's warnings and rp-pdf's own "interpreting `--pages` using page labels"
  notice both land on stderr before the failure, so "the first line is JSON"
  was false in exactly the cases that matter. "The last line is the envelope"
  holds unconditionally.
- **`rp_pdf.errors.MissingFileError`** replaces the bare `FileNotFoundError`
  `core._open_reader` raised. Otherwise the envelope's `type` — documented in
  §4.1 as `"InputError"`, `"MissingDependencyError"`, … — would have read
  `"FileNotFoundError"`, leaking a Python builtin into the agent-facing
  contract. It subclasses `FileNotFoundError`, so library callers are
  unaffected; this is the same trick `PageSpecError` already used for
  `ValueError`.

Exit paths `2` and `3` verified end to end: `PopplerNotFoundError` →
`{"type": "PopplerNotFoundError", "exit_code": 2}`, `InvalidPdfError` →
`{"type": "InvalidPdfError", "exit_code": 3}`. CI now asserts the envelope's
key set against the built CLI.

### Step 2 — JSON by default

`json_option` and `emit(as_json=...)` are gone; `plain_option` and
`emit(model, plain=False)` are the whole surface. The only real consumer was
`doctor_command`, which is why this is a behavior change rather than a
deletion of dead code — see below.

### Step 3 — the pages split

`rp_core.ranges` holds `parse_range_spec` + `contiguous_runs`;
`rp_pdf.pages` holds `parse_page_labels` and a `parse_pages` wrapper. Tests
moved with their subjects (`test_ranges.py` in rp-core, `test_pages.py` in
rp-pdf).

`parse_range_spec` takes a keyword-only `noun="item"`, used only to build error
messages. With `noun="page"` it reproduces rp-pdf's previous messages
character for character, which is what makes "no behavior change" literally
true rather than approximately true; `rp-docx` will pass `"section"`.

`PageSpec`/`PageSpecError` are aliases of `RangeSpec`/`RangeSpecError`, so
`from rp_pdf import PageSpecError` and `except PageSpecError` are unchanged.
The envelope's `type` for a bad page spec now reads `"RangeSpecError"`.

### Step 4 — specs

`robo-papyro-spec.md` and `rp-docx-spec.md` were already revised (v1.1 and
v1.2). `docs/specs/rp-pdf-spec.md` was not — it was still the pre-workspace
`pdfx` document: `pdfx` names throughout, "exit 1" for every failure, a
`pages.py` the package no longer owns, and no mention of `rp-core`. Revised to
v1.1 with a changelog. The original kickoff prompt is kept verbatim as a
labelled historical appendix rather than silently updated; it is a record of
how the package was built, not instructions for current work.

### Step 5 — timeouts

`run_binary(timeout=None)` now means "the suite default", not "forever" — there
is no longer any way to spell unbounded. `resolve_timeout()` reads
`RP_SUBPROCESS_TIMEOUT`, else 600s. A non-numeric or non-positive value is an
`InputError` rather than a silent fallback: a user who set a limit should not
be left believing an unusable one is in force. Timeouts raise
`SubprocessTimeout` (exit 3). `soffice_convert`'s own limit went 120s → 300s
per §4.4's signature.

Phase 0 created no timeout exception — it reused `ConversionError` — so nothing
needed renaming, but the two tests that asserted `ConversionError` on a timeout
now assert `SubprocessTimeout`.

### Step 6 — ruff

`ruff==0.16.1`, pinned exactly. The floor was the actual root cause of the
Phase 0 workaround: `>=` lets the gate change what it enforces whenever a
release widens ruff's implicit default. `select = ["E", "F", "W", "I", "UP",
"B"]`. 62 findings: 61 fixed mechanically by `--fix` in `c9a2ec0` (42 × UP045
`Optional[X]` → `X | None`, 19 × I001 import sorting), and the single B018 in
`1072cd1` — a test that raised `ZeroDivisionError` by evaluating `1 / 0` as a
bare statement now raises it explicitly.

### Step 7 — invariants as tests

| Rule | Test |
|---|---|
| Every typer command is in `COMMAND_NAMES` | `packages/rp-pdf/tests/test_invariants.py` |
| `robo_papyro/cli.py` imports no leaf | `packages/robo-papyro/tests/test_umbrella_cli.py::TestNoLeafImports` |
| Test modules import by path, not by name | `ci/test_workspace_invariants.py` |
| `rp_core` holds no page-label logic, imports no leaf | `ci/test_workspace_invariants.py` |

The command-registration test checks both directions (nothing registered is
missing, nothing listed is stale) and the consequence end to end: a registered
command must not be rewritten into a filename by the default-action dispatcher.

The fourth row is not one of the three §10 invariants; it is §10's "no
format-specific identifier in `rp-core`" clause plus §8's definition of done,
and it guards the exact regression step 3 fixed. It works on the AST, so
`rp-core` can keep explaining in prose why it does *not* model a page label.

AGENTS.md now carries a table of rule → test instead of restating any of them,
per §10's closing note.

**Switching to importlib import mode required work the step did not mention.**
Eleven rp-pdf test modules did `from conftest import ...`, and `test_search.py`
imported `run_cli` from `test_cli`. Both only ever worked because prepend mode
puts each `tests/` directory on `sys.path` — the same mechanism that causes the
collision the invariant exists to prevent. So: `requires_poppler` is now a real
pytest marker with the skip applied in `conftest`, the shared constants and the
`rp-pdf` subprocess runner are fixtures, and `ci/` is on `pythonpath` because
`license_gate.py` is a module sitting next to its own test.

## Test results

| Suite | Before | After |
|---|---:|---:|
| `rp-core` | 106 | 117 |
| `rp-pdf` | 173 | 207 |
| `robo-papyro` | 14 | 14 |
| license gate + workspace invariants | 16 | 44 |
| **Total** | **309** | **382** |

- Green on **Python 3.11 and 3.13**.
- Green from a **clean `git clone` + `uv sync`**, with `rp --help`, `rp doctor`,
  `rp pdf --help`, `rp-pdf --help`, and `rp-pdf doctor` all responding.
- `rp-core` coverage: **98%** (unchanged; `ranges.py` and `binaries.py` at 100%).
- `ruff check` and `ruff format --check` clean across `packages` and `ci` under
  the widened rule set.
- License gate: 46 locked packages, all reviewed.
- Baselines measured on `origin/main` in a worktree with poppler installed, so
  the comparison is like for like rather than against skipped tests.

## Behavior changes

Three of these break existing callers. All three were the point of the phase,
but they are the kind of thing that should be in a release note.

1. **The error payload moved and changed shape.** Was a flat
   `{"error": "message"}` on **stdout**; is now
   `{"error": {"type", "message", "hint", "exit_code"}}` on **stderr**, written
   as the last line. stdout is now empty on a failed run. Anything parsing
   `rp-pdf`'s errors needs updating.

2. **`doctor` prints JSON by default.** `rp doctor` and `rp-pdf doctor`
   previously printed a table unless given `--json`. The flag is gone; `--plain`
   gives the table. This is the one case where "JSON by default" was not
   already true of `rp-pdf`.

3. **`rp-pdf markdown --json` is now `--full`** (config key `[markdown].json` →
   `[markdown].full`). Its *default* output is unchanged — Markdown still goes
   to stdout, so `rp-pdf markdown f.pdf > out.md` still works. See the spec
   note below; this one is a judgement call.

4. **`pdftotext` can now time out.** It was unbounded; it now fails after 600s
   (or `RP_SUBPROCESS_TIMEOUT`) with exit 3. An operation that used to hang
   forever now fails after ten minutes. `soffice_convert`'s limit went 120s →
   300s, and `run_binary`'s no-argument default went 120s → 600s (no call site
   relied on the old value — `doctor` passes 15s explicitly).

5. **Two error `type` values are new**, for callers switching on them:
   `MissingFileError` for a missing file, and `RangeSpecError` (not
   `PageSpecError`) for a bad page spec. Both are aliases or subclasses at the
   Python level, so `except PageSpecError` / `except FileNotFoundError` still
   work; only the serialized `type` string differs.

6. **`Optional[X]` is now `X | None`** throughout, from ruff UP045. Runtime
   behavior is identical; typer resolves both.

7. **`--pages` accepts open-ended ranges**: `-4` is "up to 4" and `7-` is "7 to
   the end", against page labels as well as physical positions. Purely
   additive — every spec that parsed before still parses the same way. A bare
   `-` is rejected rather than read as "everything".

8. **Allowlist entries may be tables.** `ci/allowed-packages.toml` now takes
   `certifi = { license = "MPL-2.0", tag = "extra:ai" }` alongside the bare
   strings. Only the two weak-copyleft entries need it.

Everything else is unchanged. `rp pdf index FILE` and `rp-pdf index FILE` still
diff clean, and CI still asserts it.

## Where the revised spec was wrong — and how it was resolved

All four went to review on the PR. Every one was accepted; the spec is now
v1.2 and carries the corrections.

### 1. §3 and §10 invariant 3 — `importmode` is not a pytest ini key

§3 showed `importmode = "importlib"` under `[tool.pytest.ini_options]`. pytest
registers `--import-mode` as a **command-line option only**; there is no
matching `addini`. Setting that key produces `PytestConfigWarning: Unknown
config option: importmode` and leaves prepend mode in force — the invariant
would have looked satisfied while doing nothing.

**Resolved:** the working spelling `addopts = ["--import-mode=importlib"]` is
what landed, and §3 and §10 now say so.
`ci/test_workspace_invariants.py` asserts the *effective* mode
(`pytestconfig.getoption("importmode")`), so a wrong spelling fails rather than
passing quietly.

### 2. §4.3 — `"-4"` and `"7-"` had never been accepted

The list of forms was inherited verbatim from v1.0 §4.3, which described a
module it was directing us to move rather than rewrite — and that module had
never taken open-ended ranges. Step 3's "no behavior change" meant they had to
stay rejected for the moment.

**Resolved: implemented.** An omitted endpoint now takes the corresponding
bound — `"-4"` is `1..4`, `"7-"` is `7..count`.

Two judgement calls inside that, both pinned by tests:

- **A bare `"-"` is rejected.** It would mean `1..count`, which `"all"` already
  says, so it is far likelier a typo — and silently selecting a 500-page
  document is an expensive way to find that out. The error names `all`.
- **`rp_pdf.pages` supports the same two forms against page labels.** The
  generic parser alone would have made `--pages 7-` work on an unlabelled PDF
  and fail on a labelled one, which is exactly the kind of "depends what
  document you point it at" behavior the suite is supposed to avoid. Exact
  label matching still wins, so a document labelled `A-1` keeps addressing it.

### 3. §8's definition of done reached a flag that is not an output-format flag

`rp-pdf markdown --json` selected *what* to emit (the whole `MarkdownResult`)
rather than *how*. Renaming it to `--full` satisfied the constraint without
flipping the command's default output, which would have silently filled
`out.md` with JSON for anyone redirecting stdout.

**Resolved:** approach confirmed on review, no change needed.

### 4. §7.1's base-install rule was documented but not enforced

"A weak-copyleft package appearing in the base install path fails the gate" was
a comment in `ci/allowed-packages.toml`, not a check. Nothing stopped the base
path from silently stopping being clean.

**Resolved: step 8.** §7.1 now defines the term and requires enforcement in
both directions, and `ci/license_gate.py` implements it — see
[Step 8](#step-8--71-enforced-by-the-license-gate) below.

### 5. Minor: §4.6's `emit` signature

§4.6 gave `emit(model, plain: bool)`; the implementation is
`emit(result, plain: bool = False)`, because "JSON by default" should be what a
caller gets from `emit(result)` with no thought at all. **Resolved:** §4.6
carries the default and says why.

## Step 8 — §7.1 enforced by the license gate

Two checks, deliberately independent, because they fail for different reasons.

**Base path is clean.** `base_install_path()` walks each locked package's
`dependencies` from the published distributions. uv keeps extras under
`optional-dependencies` and the dev group under `dev-dependencies`, so
following the one key *is* "no extras, no dev group" — nothing to filter, and
nothing to fall out of step with how the extras happen to be declared. Any
weak-copyleft license found on a package in that set fails the build, and
allowlisting does not exempt it: the allowlist answers "what license is this?",
not "may it ship in the default install?".

**Tags are true.** Allowlist entries may now be tables carrying
`tag = "extra:ai"`. Every tagged entry must be unreachable from the base path,
must use the `extra:<name>` form, and must name an extra some distribution
actually declares. This fires independently of the license — an MIT package
with a false tag still fails, because the claim about the graph is what is
being checked. `certifi` and `tqdm` carry the tags; the comment that used to
assert their reachability is gone.

On the weak-copyleft classifier: any weak identifier in an SPDX expression
counts, **including inside an `OR`**. A permissive alternative may well make a
package fine, but that is a judgement for a human to record rather than
something the gate should decide silently. No current dependency has such an
expression.

The gate now reports the base path in its success line:

```
license gate passed: 46 packages, all reviewed; base install path is
26 distributions, free of weak copyleft.
```

26, not the 24 the earlier note quoted: that count was a Linux
`uv pip install rp-core rp-pdf`. The gate's figure adds `robo-papyro` and
Windows-only `colorama`, and is platform-independent by construction — which is
what a license check should be.

## Definition of done (§8)

| Criterion | Status |
|---|---|
| Suite green | 343 passed, Python 3.11 and 3.13, clean checkout |
| `rp-pdf` and `rp-core` emit identical error structure | One `ErrorEnvelope`, one code path; asserted in unit tests and CI smoke |
| No `--json` flag remains anywhere in the suite | `test_no_json_flag_on_any_command` walks every subcommand's `--help`; see spec note 3 |
| `rp_core` contains no PDF-specific identifier | `test_rp_core_models_no_page_labels`, AST-based |
| Base install path in `uv.lock` verified by the gate to be free of weak copyleft | Enforced by `ci/license_gate.py`, in both directions; 26 distributions, none weak-copyleft |

## Still open

- **§11.1 template provenance** — unchanged, and on the critical path for
  Phase 1 step 5.
- **§11.2 compliance sign-off on §7.1** — unchanged; the only item with an
  external clock. The gate check added in step 8 does not change the policy,
  only whether the repo can drift out of compliance with it unnoticed.
- **§11.3 archiving `w528-pdf-extraction-toolkit`** — was blocked on Phase 0.5
  being green. It is green.
- **`rp-mcp`** is recorded in §9 as a Phase 2 distribution isolating MCP's
  dependency tree; the larger spec change for it is a future PR.

## Next

Phase 1 — `rp-docx`, per [`docs/specs/rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §12.
Steps 1–4 unblocked it: the error payload, the output convention, and
`rp_core.ranges` are all settled, so `rp_docx/cli.py` can be written against a
contract that will not move.
