# robo-papyro 0.1.0 — Beta

Initial public beta release of robo-papyro.

The suite is ready for beta use, but remains a `0.x` project: behavior is tested and intended
to be useful, while CLI and Python interfaces may still change before 1.0.

## What is included

- `robo-papyro` 0.1.0 — umbrella distribution and `rp` dispatcher
- `rp-core` 0.1.0 — shared infrastructure
- `rp-pdf` 0.4.0 — PDF read/extract/search/render/Markdown tooling
- `rp-docx` 0.1.0 — Word read/create/edit/template tooling
- `rp-pptx` 0.1.0 — PowerPoint read/create/edit/template tooling
- `rp-xlsx` 0.1.0 — Excel read/create/edit/template tooling with fidelity safeguards
- `rp-mcp` 0.1.0 — stdio MCP servers for the four document formats

## Install this exact beta

```sh
git clone https://github.com/RoboNater/robo-papyro.git
cd robo-papyro
git checkout robo-papyro-v0.1.0
uv sync
uv run rp doctor
```

`rp doctor` reports which optional external tools are available. Poppler is required for the
PDF default text engine and rendering. LibreOffice is required only for Office conversion and
rendering; normal DOCX/PPTX/XLSX read and write operations do not require it.

## Known limitations

- This is beta software; compatibility is not guaranteed until 1.0.
- Worksheet rename in `rp-xlsx` is intentionally disabled for now. Spreadsheet references can
  exist in many structures that openpyxl does not safely rewrite, so robo-papyro refuses the
  operation rather than risk silently corrupting references.
- `rp-xlsx` refuses edits to workbooks containing structures known to be lossy under openpyxl
  unless the caller explicitly opts in with `--allow-lossy`; when allowed, the dropped
  structures are reported.
- External-tool-dependent functionality varies with the locally installed Poppler and
  LibreOffice versions.
- The distributions in this monorepo are independently versioned. The component table above
  is the tested set for this suite release.

## Feedback and bug reports

Please use GitHub Issues. Include the command, OS, Python and uv versions, and enough diagnostic
output to reproduce the problem. Do **not** upload confidential, proprietary, personal, or
otherwise sensitive source documents to a public issue. If a reproducer is necessary, prefer a
small sanitized or synthetic document.
