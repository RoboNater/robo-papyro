# Templates

House `.dotx` / `.docx` style templates resolved by `rp-docx`.

**This directory is empty on purpose, and CI never needs anything in it.**
Phase 1 was built and tested without a single real template — see §11.1 of
[`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md). Everything below is for
working with real templates once there are some.

## How resolution works

`rp_docx.templates.resolve_template()` searches, in order:

1. `$RP_DOCX_TEMPLATE_DIR` — one or more directories, separated the way `PATH` is
2. `templates/local/` in the checkout
3. `templates/` in the checkout (this directory)

trying `<name>.dotx` before `<name>.docx`, so `--template memo` finds
`memo.dotx` here. With no template named at all, `$RP_DOCX_TEMPLATE` is used,
and failing that python-docx's bundled default.

`templates/local/` comes first among the two because it is the **gitignored drop
point for real templates** during manual work: when a name exists in both, the
real one is the one meant. Nothing there is ever required for CI.

An optional `<name>.stylemap.json` sits beside each template and maps logical
roles to that template's real style names:

```json
{"h1": "House Heading 1", "h2": "House Heading 2", "body": "RP Body Text",
 "bullet": "House Bullet", "numbered": "House Number", "table": "Table Grid"}
```

`rp-docx templates stylemap FILE` scaffolds one to correct by hand. A mapped
style that the template does not define is an **error**, never a silent
fallback — see [`docs/usage-docx.md`](../docs/usage-docx.md#templates).

## What may be committed here

**A template, only if it is ours to redistribute.** A downloaded or corporate
`.dotx` in git is a licensing question, an opaque diff, and a debugging hazard
at once. Anything added here must be recorded in the table below; a template
with no owner and no canonical location is a liability, because a stale
letterhead is worse than a missing one.

| Template | Owner | Canonical source | Last synced |
|---|---|---|---|
| _(none yet)_ | | | |

**A manifest, always.** `rp-docx templates manifest FILE` emits a JSON
description of a template's *shape* — style names, page geometry, presence flags
— carrying no document text, no image bytes, no author names, and no path beyond
the template's own basename. That is a correctness property enforced by a test,
not a convention. Manifests belong in
`packages/rp-docx/tests/fixtures/*.manifest.json`, where
`templates synthesize` rebuilds a structurally equivalent template from them at
test time. It is what lets CI regression-test a confidential template's shape
while the template stays on the machine that holds it.

## Validating against a real template

The manual pass in [`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §13:

```sh
cp /path/to/house.dotx templates/local/
uv run rp-docx templates inspect house              # is the style list right?
uv run rp-docx templates stylemap house -o templates/local/house.stylemap.json
$EDITOR templates/local/house.stylemap.json         # the scaffold is a guess
uv run rp-docx create -o out.docx --from-markdown notes.md --template house
# open out.docx in Word and confirm the house styles applied
uv run rp-docx templates manifest templates/local/house.dotx \
    -o packages/rp-docx/tests/fixtures/house.manifest.json
```

Only the last step produces a repository artifact, and it carries nothing
confidential by construction. Everything found in the others comes back as a
defect report or a spec correction, not as a file.

## Open decision

`robo-papyro-spec.md` §11.1 is unresolved: if the source of truth for these
files is SharePoint, decide whether this directory holds a synced copy or a
pointer to it. Resolve before the first template lands. The manifest loop above
lowers the stakes — CI depends on manifests rather than on the templates
themselves — but it does not answer the question.
