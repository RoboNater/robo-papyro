# Phase 2.5 status — rp-pptx

## BLUF

Phase 2.5 introduces the independently versioned `rp-pptx` distribution and its
`rp-pptx` / `rp pptx` command surfaces. It provides JSON-first presentation
inspection, slide-range reads, Markdown extraction and authoring, template
resolution and redacted manifests, run-spanning replacement, notes and property
editing, and safe slide delete/reorder operations. The package uses python-pptx
for every core path; LibreOffice remains optional and subprocess-only.

The modern threaded-comment checkpoint could not be completed because no real
PowerPoint-authored reference deck was available. Comment authoring/parsing is
therefore explicitly deferred rather than based on invented XML. Likewise,
python-pptx cannot author masters or layouts, so synthesized template files
preserve geometry and validity but cannot reproduce arbitrary manifest layout
inventories. These are follow-ups, not hidden best-effort behavior.

## Delivered

- Workspace package metadata, standalone and umbrella entry points, and the
  python-pptx/XlsxWriter dependency and license declarations.
- Pydantic models matching the stable API payloads in the specification.
- `.pptx`/`.potx` package validation, lossless content-type retyping, opening,
  and saving.
- Read APIs for overview, text/runs, Markdown, tables, images, speaker notes,
  charts, and core properties, all with 1-based slide range selection.
- Markdown-backed creation and append, replacement across arbitrary run
  boundaries, notes/property updates, and explicit-output-only mutation.
- Slide deletion and complete-permutation reordering through `p:sldIdLst`,
  including refusal to produce an empty deck.
- Template discovery, `.potx` preference, path/name error distinction, lazy
  layout checks, sidecar layout maps, inspection, and redacted manifests.
- JSON-first Typer commands plus `--plain`, documentation, and roadmap update.

## Specification corrections and deferrals

1. The spec's synthesis requirement is beyond python-pptx's public authoring
   model: it cannot create masters or layouts. Synthesis produces a valid
   geometry-equivalent template; exact layout inventory reconstruction needs
   carefully scoped package-XML cloning in a follow-up.
2. Modern comments remain deferred until a genuine PowerPoint-authored sample
   can be inspected. Guessing the evolving extension namespaces would create a
   fixture that tests itself instead of testing PowerPoint compatibility.
3. The proposed format-agnostic OOXML/Markdown promotion was not necessary to
   deliver the leaf and is deferred. The PowerPoint package layer is small and
   does not import another leaf; premature extraction would expand this phase's
   regression surface without changing the public contract.

## Verification status

The refreshed environment resolved and synchronized the complete workspace.
The full suite passes with 594 tests passing and 90 optional-external-tool tests
skipped. Ruff lint and formatting checks, the package build, license gate, CLI
standalone/umbrella identity sweep, static compilation, and repository diff
checks also pass.
