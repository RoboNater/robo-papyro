# rp-docx

Word document toolkit for the [robo-papyro](../../README.md) suite: a
JSON-first library and CLI for reading, creating, and editing `.docx` files.

```sh
rp-docx index report.docx            # structure, counts, headings, properties
rp-docx text report.docx --runs      # paragraphs, optionally with run formatting
rp-docx markdown report.docx         # via mammoth
rp-docx create -o out.docx --from-markdown notes.md --template memo
rp-docx template memo.dotx --context ctx.json -o filled.docx
```

Structured read commands (`index`, `text`, `tables`, `images`, `comments`,
`changes`, `props`) emit JSON by default; `--plain` is the human opt-out.
`markdown` is a conversion command and emits Markdown instead — there is no
`--json` flag anywhere in the suite, but conversion output was never JSON to
begin with. Errors go to stderr as an `rp_core` `ErrorEnvelope`, with the exit
code carried by the error class: 1 for input errors, 2 for a missing external
binary, 3 for an unreadable file.

Full documentation: [`docs/usage-docx.md`](../../docs/usage-docx.md).
Specification: [`docs/specs/rp-docx-spec.md`](../../docs/specs/rp-docx-spec.md).
