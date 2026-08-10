# Changelog

Notable user-facing changes to robo-papyro are recorded here. The repository contains
independently versioned distributions; a suite release records the exact component versions
that were tested together.

## Unreleased

No changes yet.

## robo-papyro 0.1.0 — 2026-08-10

Initial public beta release of the robo-papyro document tooling suite.

### Component versions

| Distribution | Version |
|---|---:|
| `robo-papyro` | 0.1.0 |
| `rp-core` | 0.1.0 |
| `rp-pdf` | 0.4.0 |
| `rp-docx` | 0.1.0 |
| `rp-pptx` | 0.1.0 |
| `rp-xlsx` | 0.1.0 |
| `rp-mcp` | 0.1.0 |

### Included

- PDF extraction, search, rendering, Markdown conversion, OCR, and optional VLM review.
- DOCX read, create, edit, template, comments, and tracked-change operations.
- PPTX read, create, edit, template, notes, and slide operations.
- XLSX read, create, edit, template, sheet operations, and explicit fidelity safeguards.
- MCP stdio servers for PDF, DOCX, PPTX, and XLSX operations.
- The `rp` umbrella CLI plus the standalone format CLIs.

### Beta status

This is a `0.x` beta release. Core functionality is tested, but CLI and Python interfaces may
change before 1.0. See `docs/releases/robo-papyro-v0.1.0.md` for release-specific notes and
known limitations.
