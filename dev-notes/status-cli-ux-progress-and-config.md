# Status — CLI usability: progress, job descriptions, and config round-tripping

Four feature requests from **human** users of a suite designed primarily for
agents, delivered together because they share one constraint. Written in the
pattern of the phase status notes: what was asked, what shipped, and every place
the obvious implementation turned out to be the wrong one.

Not a spec phase. `rp-pdf`'s roadmap entry is
[ROADMAP.md](../ROADMAP.md#progress-job-descriptions-and---save-config-);
the architectural rules this established are in
[AGENTS.md](../AGENTS.md).

## BLUF

**All four are complete and shipped.** The requests, verbatim in substance:

| # | Request | Status |
|---|---|---|
| 1 | Progress indication for long jobs — "the user can't tell if anything is happening at all until the job is done" | ✅ `--progress`, `rp_core.progress` |
| 2 | A description of the job from the selected flags, before it starts, as validation that the options are right | ✅ `--describe`, `rp_pdf.describe` |
| 3 | Write the selected options to a `.toml` so they are reused for the next PDF | ✅ `--save-config PATH` |
| 4 | `docs/usage.md` is unclear whether there is one config file or several, and what the default is named | ✅ docs rewritten |

**The unifying constraint, and the reason 1 and 2 needed no agent-vs-human
mode.** The request raised the possibility of hiding these behind a flag kept
off for agents. That turned out to be unnecessary, and a mode flag would have
been the worse design — something has to *set* it correctly, and the wrong
default is invisible until output is corrupted. Instead:

- everything new is written to **stderr**; stdout is byte-for-byte unchanged
  (asserted directly: `test_markdown_body_on_stdout_is_unaffected` diffs the
  stdout of a described run against a quiet one);
- both display features default to on **only when stderr is a terminal**
  (`clikit.display_enabled` → `isatty`), which is false for an agent, a
  pipeline, a cron job, and CI without anyone configuring anything;
- the library default is a no-op reporter, so `rp_pdf` as an imported package is
  unchanged.

An explicit `--progress`/`--describe` still forces them on for a log, and
`--no-*`, `RP_PDF_PROGRESS`/`RP_PDF_DESCRIBE`, and a `[ui]` config section cover
the rest of the matrix.

### Verification

- `uv run pytest`: **1081 passed, 8 skipped** (988 → 1089 collected; **101 new
  tests**). The 8 skips are LibreOffice-gated and unrelated.
- Coverage on the new and heavily-changed modules: `rp_core/progress.py` 97%,
  `rp_core/clikit.py` 97%, `rp_pdf/config.py` 98%, `rp_pdf/describe.py` 93%.
- `ruff check` and `ruff format` clean across the workspace.
- Exercised by hand end to end, including under a real pty (`pty.fork`) to
  confirm the in-place repaint, the ASCII fallback, and that the JSON on stdout
  still parses while the spinner is running.
- Poppler was installed in the dev container for this work, so the render and
  AI-pass paths **ran** rather than skipping.

---

## 1. Progress indication

### What shipped

`rp_core/progress.py`: `Progress`/`Step` (a callback interface whose base
implementation does nothing), `NULL`, and `StderrProgress`.

Counted steps thread through `to_markdown` (table scan, text extraction,
assembly, page rendering, AI review, OCR), `ocr.transcribe_pages`,
`core.get_images`, `core.get_tables`, `core._page_texts`, and
`rp_core.render.rasterize_pages`. `rp-docx`/`rp-pptx` `convert` and `render` get
the LibreOffice and poppler steps.

### Decisions worth recording

**A callback, not printing — and this is not a loophole in "core never
prints."** AGENTS rule 3 says library functions return models and never write to
a stream. A progress-reporting extractor appears to violate it, and would if it
called `print`. It doesn't: it calls a `Progress` it was handed, defaulting to
one whose methods have empty bodies. The decision that the call means *writing
to stderr* is made in `clikit.job`, in the CLI layer, where every other
formatting decision is made. The rule survives intact, and a library caller with
its own UI can pass its own reporter — documented in `docs/usage.md`.

**The ticking thread is the feature, not a nicety.** The request named the real
symptom: "stuck trying to read a file from a bad network connection." A progress
display driven *by the work* cannot report that, because the work is what has
stopped. `StderrProgress` runs a daemon thread that repaints on an interval, so
the elapsed clock advances while the calling thread is blocked in a socket read
or a subprocess. That is what makes an **indeterminate** step (`Converting with
LibreOffice`, no count possible) worth having at all, and it is directly tested
(`test_the_clock_advances_while_the_caller_is_blocked`).

**Two output shapes, because a redirected stream is not a slow terminal.** On a
terminal: one line rewritten with `\r`, a completed line left behind per stage.
Off one — where `--progress` was explicitly asked for, so a log or CI is the
likely destination — there is nothing to rewrite, so each stage boundary gets
its own line plus a "still working" line every 15s. A log is exactly where a
hung job needs to be diagnosable after the fact; carriage returns there produce
one unreadable mega-line.

**`advance()` in a `finally`.** The AI and OCR passes advance the counter for a
page that *failed* as well as one that succeeded. A count that stalls whenever
the model rejects a page reads as a hang, which is the state this feature exists
to distinguish. Tested (`test_a_rejected_page_still_counts_as_handled`).

**Thread-safety is required, not defensive.** `--jobs N` advances from N worker
threads; one lock guards the counter and every write. Tested with four threads
and 200 advances.

### Trip hazards found on the way

- **rp-core bans the identifier `label`.** `ci/test_workspace_invariants.py`
  fails on any identifier containing "label" in `rp_core/*.py`, because a page
  *label* is PDF knowledge that Phase 0.5 deliberately pushed back into
  `rp-pdf`. A progress step's display string was called `label` on the first
  pass and tripped it. It is `name`. The invariant is right and was left alone;
  AGENTS.md now warns about it so the next person does not rediscover it.
- **`io.StringIO.encoding` is read-only**, so a test stream that claims an
  encoding (the reporter reads it to decide whether the Unicode spinner is
  safe) needs it as a *class* attribute.
- A broken or closed stderr swallows its own error: progress is decoration and
  must never take down a job that was otherwise going to succeed.

---

## 2. Job descriptions

### What shipped

`rp_pdf/describe.py` — pure functions from a command's resolved-options mapping
to `(title, rows)`, printed by `clikit.job` before the work starts.

```
rp-pdf markdown — report.pdf
  pages      all
  engine     poppler (needs pdftotext installed)
  images     skipped (--images-dir DIR to extract and link them)
  AI review  on, model gpt-4o-mini at https://openrouter.ai/api/v1; 4 concurrent, pages rendered at 150 dpi
  OCR        off — pages with no text layer stay empty (--ocr to transcribe them)
  outline    not used (--outline-headings, --outline-context; no-ops without bookmarks)
  cache      on — responses reused from ~/.cache/rp-pdf
  output     report.md
```

### Decisions worth recording

**Options that are *off* are listed, with the flag that turns them on.** The
request asked for "validation that they chose all the options correctly", and
the failure mode there is an option the user *meant* to pass and didn't. A
description that lists only what is enabled cannot answer "did I remember
`--ocr`?". This is also why an unset `--model` is reported as
`unset — RP_PDF_VLM_MODEL or --model is required` rather than omitted: silence
reads as "configured", and it is the commonest first-run failure.

**Resolved values, not typed ones.** The description reports what will actually
happen after flag → env → config → default resolution, including defaults the
user never typed. A description of the command line would not be validation of
anything — the config file is precisely where a surprise comes from.

**One source of truth per command (`cli.Options`).** The description, the run,
and `--save-config` all read the same object, populated one call per option. The
alternative — a second literal listing the same keys for display — drifts, and a
description that quietly disagrees with what runs is worse than none.

---

## 3. `--save-config`

### What shipped

`--save-config PATH` on the six job commands, plus `config.dump_toml`,
`config.save_command_options`, and `config.is_auto_discovered`. The TOML writer
is ~15 lines over `tomllib`'s read-only counterpart; no dependency was added.

### Decisions worth recording

**It saves what you *passed*, not every value it resolved.** The first
implementation wrote the full resolved mapping. That is wrong twice over: it
freezes today's built-in defaults into the user's file, so a later change to a
default silently does not reach them; and the file becomes 15 lines of noise in
which the two decisions that mattered are invisible. Only explicitly-passed
flags are recorded. Environment and existing-config values are recorded by
nobody, deliberately — they already live somewhere that outlasts the run.

**`markdown -o FILE` is refused even when passed explicitly** (`cli.NEVER_SAVED`).
Caught by reading the first generated file: it contained `out = "out.md"`, which
would make the *next* document silently overwrite this one's output. It names
this run's artifact, not a preference. Directory targets (`images --out`,
`render --out`, `tables --csv`) are saved — reusing a directory is the normal
case, and `[render].out` is already a documented setting. The command says which
key it skipped and why rather than dropping it quietly.

**It writes after the run succeeds.** What gets recorded is a command line known
to have worked, not one that was merely typed — a bad `--model` should not be
enshrined as a default. Tested: a failed run writes no file.

**Per-command keys to `[command]`, shared VLM keys to `[vlm]`** — the layout a
hand-written file uses. `--save-config` is a reasonable way to *learn* the
layout, so it should not invent a different one.

**Merged, not clobbered — and it says what it loses.** An existing file's other
sections and keys survive, but the file is rewritten from its parsed contents,
so comments and formatting do not. That is stated on stderr when it applies,
rather than being discovered later.

**`--save-config` takes a path, with no optional-value form.** The natural
spelling is a bare `--save-config` defaulting to `./rp-pdf.toml`. Click supports
optional-value options via `is_flag=False, flag_value=...`; **typer 0.27 accepts
both parameters and forwards neither** (`typer.main` never mentions
`flag_value`), so `--save-config` alone fails with "requires an argument".
Rather than work around it, the path is required and the message reports whether
the path given is one discovery will find. Worth revisiting if typer gains
support.

---

## 4. Configuration-file documentation

The report was that `docs/usage.md` did not say whether there is one config file
or several, or what a default one is called. Both were technically present and
neither was answerable at a glance: the facts lived in an ordered "first match
wins" list that reads as *exactly one file applies*, which is wrong — the
project and user files both apply and merge.

`docs/usage.md` now leads the section with a two-row table (`rp-pdf.toml`
walking up from the cwd; `~/.config/rp-pdf/config.toml`), states that both names
are fixed, that **both apply at once** and merge with the project file winning,
that there is at most one of each, and that `--config` makes one file the only
one read. `README.md` and the `rp_pdf.config` module docstring were brought in
line. `--describe` is pointed at as the runtime answer to "which settings are
actually in play", which is usually the question underneath.

---

## Known limits and future work

- **`validate-vlm-ocr` has no progress or description.** It is a fixed
  three-page synthetic document and two API calls; the machinery would outweigh
  it. Easy to add if it ever grows.
- **`index` and `doctor` have neither**, by choice: near-instant, nothing to
  configure. An option that never helps is still an option to read past.
- **`rp-docx`/`rp-pptx` take `--describe`/`--progress` on `convert` and `render`
  only** — the two commands that shell out. They also have no config file of
  their own, so no `[ui]` section and no `--save-config`; if either grows one,
  `clikit.display_enabled` already takes the `config_value` argument for it.
- **Page-render progress moves once per contiguous run**, not per page: poppler
  rasterizes a whole run in one invocation. The elapsed clock carries liveness in
  between. Per-page granularity would mean one subprocess per page — a real cost
  for a display detail.
- **The heartbeat interval (15s) and tick (0.4s) are module constants**, not
  options. No evidence yet that anyone wants to tune them; a test asserts they
  stay in a sane range so a careless edit is caught.
- **`--save-config` cannot record a value that came from an existing config
  file.** Saving to the *same* file preserves it (the merge does), but saving to
  a different file drops it. Correct under "records what you passed", and
  documented, but worth revisiting if anyone tries to use it to copy a config.
