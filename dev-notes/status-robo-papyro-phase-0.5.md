# Status — robo-papyro Phase 0.5

**Date:** 2026-08-05 · **Branch:** `claude/robo-papyro-phase-0.5-nz2gxb` ·
**Driving doc:** [`docs/specs/robo-papyro-spec.md`](../docs/specs/robo-papyro-spec.md) §8

## BLUF

**Phase 0.5 is complete — all seven steps, eight commits.** The suite is at
**343 tests** (from 309), green on Python 3.11 and 3.13, `ruff check` and
`ruff format --check` clean under the widened rule set, and verified from a
clean `git clone` + `uv sync`. Every item in §8's definition of done is met.

Steps 1–4 (the Phase 1 blockers) and steps 5–7 are separate commits on one
branch rather than separate PRs, because the session was given a single
designated branch. They can be reviewed as two halves: `3a11548..218366a` is
the contract work, `54aad11..bee38c0` is the independent work.

**Three user-visible contracts changed** and will break anyone scripting
against them: the error payload, `doctor`'s default output, and
`rp-pdf markdown --json`. Details in [Behavior changes](#behavior-changes).

**Three places the revised spec is wrong**, one of which needed a judgement
call I would like confirmed — §8's "no `--json` flag remains anywhere" reaches
a flag that is not an output-format flag. See
[Where the revised spec is wrong](#where-the-revised-spec-is-wrong).

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
| `rp-core` | 106 | 110 |
| `rp-pdf` | 173 | 200 |
| `robo-papyro` | 14 | 14 |
| license gate + workspace invariants | 16 | 19 |
| **Total** | **309** | **343** |

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

Everything else is unchanged. `rp pdf index FILE` and `rp-pdf index FILE` still
diff clean, and CI still asserts it.

## Where the revised spec is wrong

### 1. §3 and §10 invariant 3 — `importmode` is not a pytest ini key

§3's workspace-configuration block shows:

```toml
[tool.pytest.ini_options]
importmode = "importlib"          # see §10, invariant 3
```

pytest registers `--import-mode` as a **command-line option only**; there is no
matching `addini`. Setting that key produces
`PytestConfigWarning: Unknown config option: importmode` and leaves prepend
mode in force — the invariant would have looked satisfied while doing nothing.
The working spelling is `addopts = ["--import-mode=importlib"]`, which is what
landed. `ci/test_workspace_invariants.py` asserts the *effective* mode
(`pytestconfig.getoption("importmode")`) rather than the config text, so a
wrong spelling fails rather than passing quietly. **§3 should be corrected.**

### 2. §4.3 — `"-4"` and `"7-"` have never been accepted

§4.3 lists the forms `rp_core.ranges` parses as `"3"`, `"1-5"`, `"1,3,7-9"`,
`"-4"`, `"7-"`. The last two are open-ended ranges, and no implementation has
ever taken them: `parse_pages("-4", 10)` raises `PageSpecError`, and a test has
asserted that since the `pdfx` days. The list is inherited verbatim from v1.0
§4.3, which described the module it was telling us to *move without rewriting* —
so it was wrong then too, and step 3's "no behavior change" says it must stay
wrong for now.

I kept them rejected and pinned it with two named tests
(`test_open_ended_low_is_rejected`, `test_open_ended_high_is_rejected`) that
point at this note. **This needs a decision:** either §4.3 drops the two forms,
or open-ended ranges become a small feature with its own step. They are cheap
to add (`"-4"` → 1..4, `"7-"` → 7..count) and genuinely useful for "everything
from here on", but adding them silently inside a move would have been wrong.

### 3. §8's definition of done reaches a flag that is not an output-format flag

"No `--json` flag remains anywhere in the suite" collided with
`rp-pdf markdown --json`. That flag does not select a *format*: `markdown`
emits a document, and `--json` asked for the whole `MarkdownResult` — per-page
detail and warnings as well as the Markdown body — instead of just the body.

The two readings lead to different work:

- *Literal §4.6 reading:* make `markdown` JSON-by-default with `--plain` for
  the Markdown. This silently breaks `rp-pdf markdown f.pdf > out.md`, the
  command's primary documented use, by filling the file with JSON. It is also
  not in any step.
- *What I did:* rename the flag to `--full`, keeping its meaning and
  `markdown`'s default output. The literal constraint is satisfied — a test
  walks every subcommand's `--help` and fails on `--json` — and the break is
  loud (unknown option) rather than silent (wrong file contents).

I took the second because the risk is asymmetric, but it is a contract change
made on my own reading of intent, so **please confirm**. If you want the first,
it is a small follow-up.

### 4. §7.1's base-install rule is documented but not enforced

§7.1 says "A weak-copyleft package appearing in the base install path fails the
gate regardless of allowlisting." `ci/allowed-packages.toml` records the policy
and tags `certifi` and `tqdm` as `ai-extra`, but `ci/license_gate.py` does not
compute the base install path, so the rule is a comment rather than a check.
No step in §8 assigns it, so I did not add it — flagging it as a gap rather
than doing unrequested work.

I did **verify** the current state, which is what §8's definition of done asks
for: a base `uv pip install rp-core rp-pdf` resolves to **24 distributions**,
none of them `certifi`, `tqdm`, `httpx`, or `openai`. The base path is clean
today; nothing stops it from silently stopping being clean.

### 5. Minor: §4.6's `emit` signature

§4.6 gives `emit(model, plain: bool)`. Implemented as
`emit(result, plain: bool = False)` — the default matters, because "JSON by
default" should be what a caller gets from `emit(result)` with no thought at
all. Noted only for exactness.

## Definition of done (§8)

| Criterion | Status |
|---|---|
| Suite green | 343 passed, Python 3.11 and 3.13, clean checkout |
| `rp-pdf` and `rp-core` emit identical error structure | One `ErrorEnvelope`, one code path; asserted in unit tests and CI smoke |
| No `--json` flag remains anywhere in the suite | `test_no_json_flag_on_any_command` walks every subcommand's `--help`; see spec note 3 |
| `rp_core` contains no PDF-specific identifier | `test_rp_core_models_no_page_labels`, AST-based |
| Base install path in `uv.lock` free of weak copyleft | Verified: 24 distributions, none weak-copyleft; see spec note 4 |

## Still open

- **§11.1 template provenance** — unchanged, and on the critical path for
  Phase 1 step 5.
- **§11.2 compliance sign-off on §7.1** — unchanged; the only item with an
  external clock.
- **§11.3 archiving `w528-pdf-extraction-toolkit`** — was blocked on Phase 0.5
  being green. It is green.
- The four spec corrections above, of which **spec note 3 wants an explicit
  yes/no** and note 2 wants a decision before `rp-docx` starts using
  `rp_core.ranges`.

## Next

Phase 1 — `rp-docx`, per [`docs/specs/rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §12.
Steps 1–4 unblocked it: the error payload, the output convention, and
`rp_core.ranges` are all settled, so `rp_docx/cli.py` can be written against a
contract that will not move.
