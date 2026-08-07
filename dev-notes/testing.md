# How to run tests

```bash
uv run pytest
```

That's it — uv ensures the environment matches the lockfile, and every PDF,
Word, and PowerPoint fixture (including templates) is generated on the fly in
each package's `conftest.py` — no binary fixtures are committed anywhere in
the workspace, and no setup is needed. As of this writing the workspace
collects 988 tests total (this count grows as packages gain features — use
`uv run pytest --collect-only -q` to see the current total). With poppler and
a working LibreOffice installed you should see nearly all of them pass; without
either, the tests that depend on them skip (see below).

Useful variations:

```bash
uv run pytest -v                              # list each test by name
uv run pytest packages/rp-pdf                 # one package
uv run pytest packages/rp-docx -k templates   # one package, keyword filter
uv run pytest -k labels                       # only tests matching a keyword across the workspace
uv run pytest -q --tb=short                   # compact output, short tracebacks
```

Things to know:

- Most text, search, render, markdown-AI, and OCR tests in `rp-pdf` need
  poppler (`pdftotext`/`pdftoppm`) on your `PATH` or via the `RP_POPPLER_PATH`
  environment variable — the default text extraction engine shells out to
  `pdftotext` (`dev-notes/issue-1.md`), and the AI/OCR passes render pages.
  These carry `@pytest.mark.requires_poppler` and skip cleanly when poppler is
  absent.
- Tests in `rp-docx` and `rp-pptx` that need Office-format conversion or
  rendering carry `@pytest.mark.requires_soffice`, pointed at `soffice` via
  `PATH` or `RP_SOFFICE_PATH`. This marker probes that LibreOffice can
  actually *convert* a file, not merely that the binary exists — some
  containers ship a `soffice` that fails every conversion with "source file
  could not be loaded" — so a present-but-broken LibreOffice skips these
  tests rather than failing them. **No test in the workspace may require
  LibreOffice to pass.**
- The AI-pass tests (`packages/rp-pdf/tests/test_markdown.py`) and OCR tests
  (`packages/rp-pdf/tests/test_ocr.py`) run against a fake OpenAI-compatible
  endpoint served from a local thread (the `fake_vlm` fixture in `conftest.py`)
  — no network, no real API key, no cost. Nothing in the suite ever calls a
  real model.
- Fixtures that python-docx or python-pptx genuinely cannot produce (tracked
  changes, comments) are still generated rather than committed: `conftest.py`
  writes the XML parts by hand onto an otherwise-generated package. A
  generated fixture cannot drift, so a failing test is always the code.

# Manually testing the VLM features

The automated suite proves the plumbing; whether a *specific model* is good at
refinement/OCR is a judgment call the suite can't make. To exercise the real
thing:

```bash
# Check your OCR setup end-to-end on a synthetic scanned PDF (known text,
# similarity scoring; exits nonzero if OCR produced nothing):
RP_PDF_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... uv run rp-pdf validate-vlm-ocr

# Markdown with AI refinement, then with OCR for scanned pages:
RP_PDF_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run rp-pdf markdown report.pdf -o report.md --ai
RP_PDF_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run rp-pdf markdown scanned.pdf -o scanned.md --ai --ocr
```

Local servers (Ollama, LM Studio, vLLM) work the same way with
`--base-url`/`RP_PDF_VLM_BASE_URL` and no API key.

# Manually testing against a real house template

`rp-docx` and `rp-pptx` both ship without ever seeing a corporate template or
deck. Validating one is a separate, manual pass — see
`docs/specs/rp-docx-spec.md` §13 and `docs/specs/rp-pptx-spec.md` §13, and
`templates/README.md` for the drop point (`templates/local/`, gitignored,
never required by CI).
