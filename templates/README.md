# Templates

House `.dotx`/`.docx` (Word, resolved by `rp-docx`) and `.potx`/`.pptx`
(PowerPoint, resolved by `rp-pptx`) style templates.

**This directory is empty on purpose, and CI never needs anything in it.**
Phase 1 (`rp-docx`) and Phase 2.5 (`rp-pptx`) were both built and tested
without a single real template — see §11.1 of
[`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) and §11.1 of
[`rp-pptx-spec.md`](../docs/specs/rp-pptx-spec.md). Everything below is for
working with real templates once there are some.

## How resolution works

Both packages resolve a bare template name against a list of directories,
tried in order, then fall back to a configured or bundled default — but the
two implementations currently differ in two ways worth knowing before you
rely on either: how many directories the `_TEMPLATE_DIR` variable can name,
and how the in-checkout directories are located.

| | `rp-docx` (`rp_docx.templates.template_dirs`) | `rp-pptx` (`rp_pptx.templates._roots`) |
|---|---|---|
| Directory env var | `RP_DOCX_TEMPLATE_DIR` | `RP_PPTX_TEMPLATE_DIR` |
| `_TEMPLATE_DIR` accepts | **Multiple** directories, split on `os.pathsep` (`PATH`-style) | **One** directory only — the whole value is wrapped in a single `Path` |
| In-checkout directories | The nearest ancestor of the current working directory that has a `templates/` next to a `.git` or `pyproject.toml` (walks up from `cwd`) | `Path.cwd() / "templates"` directly — no ancestor search |
| Default-template env var | `RP_DOCX_TEMPLATE` | `RP_PPTX_TEMPLATE` |
| Extensions tried, in order | `.dotx` then `.docx` | `.potx` then `.pptx` |
| Map file | `<name>.stylemap.json` | `<name>.layoutmap.json` |

In practice this means `RP_PPTX_TEMPLATE_DIR` naming more than one directory
(the `PATH`-separated form that works for `RP_DOCX_TEMPLATE_DIR`) silently
resolves to a single, likely-wrong path instead of erroring, and `rp-pptx`
only finds `templates/local/`/`templates/` when run from the checkout root —
`rp-docx` finds them from any subdirectory. Running either CLI from the
repository root, as the examples below do, sidesteps both differences. If you
rely on multiple template directories or run from a subdirectory, treat this
as a known implementation gap rather than a documented feature of `rp-pptx`.

Both packages try, in order:

1. `$RP_DOCX_TEMPLATE_DIR` / `$RP_PPTX_TEMPLATE_DIR`, per the table above
2. `templates/local/`
3. `templates/` (this directory)

so `--template memo` finds `memo.dotx` here, and `--template house` finds
`house.potx`. With no template named at all, `$RP_DOCX_TEMPLATE` /
`$RP_PPTX_TEMPLATE` is used, and failing that the upstream library's own
bundled default (python-docx's or python-pptx's).

An explicit path that does not exist is always an error naming *that path* —
never mistaken for an unresolvable bare name. This matters because the two
failures should not read alike: a typo'd path and a typo'd template name
point the user in different directions.

`templates/local/` comes first among the two in-checkout directories because
it is the **gitignored drop point for real templates** during manual work:
when a name exists in both, the real one is the one meant. Nothing there is
ever required for CI.

## Word style maps

An optional `<name>.stylemap.json` sits beside each `.dotx`/`.docx` template
and maps logical roles to that template's real style names:

```json
{"h1": "House Heading 1", "h2": "House Heading 2", "body": "RP Body Text",
 "bullet": "House Bullet", "numbered": "House Number", "table": "Table Grid"}
```

`rp-docx templates stylemap FILE` scaffolds one to correct by hand. A mapped
style that the template does not define is an **error**, never a silent
fallback — see [`docs/usage-docx.md`](../docs/usage-docx.md#templates).

## PowerPoint layout maps

An optional `<name>.layoutmap.json` sits beside each `.potx`/`.pptx` template
and maps Markdown-conversion roles to that template's real layout names:

```json
{"title": "RP Title", "section": "House Section Break",
 "content": "House Content", "blank": "House Blank"}
```

`rp-pptx templates layoutmap FILE` scaffolds one to correct by hand. A mapped
layout the template does not define is an **error**, never a silent fallback
— see [`docs/usage-pptx.md`](../docs/usage-pptx.md#templates). Checking is
lazy, exactly as with Word style maps: a deck with no section breaks does not
need a section layout to exist.

## What may be committed here

**A template, only if it is ours to redistribute.** A downloaded or corporate
`.dotx`/`.potx` in git is a licensing question, an opaque diff, and a
debugging hazard at once. Anything added here must be recorded in the table
below; a template with no owner and no canonical location is a liability,
because a stale letterhead is worse than a missing one.

| Template | Format | Owner | Canonical source | Last synced |
|---|---|---|---|---|
| _(none yet)_ | | | | |

**A manifest, always.** `rp-docx templates manifest FILE` and
`rp-pptx templates manifest FILE` each emit a JSON description of a
template's *shape* — style or layout names, geometry, presence flags —
carrying **no document/slide text, no image bytes, no author names, and no
path beyond the template's own basename**. That is a correctness property
enforced by a test in each package, not a convention. Manifests belong in
`packages/rp-docx/tests/fixtures/*.manifest.json` and
`packages/rp-pptx/tests/fixtures/*.manifest.json`, where each package's
`templates synthesize` rebuilds a structurally equivalent template from them
at test time. It is what lets CI regression-test a confidential template's
shape while the template stays on the machine that holds it.

## Validating against a real template

Word and PowerPoint each have their own manual pass, run separately —
[`rp-docx-spec.md`](../docs/specs/rp-docx-spec.md) §13 and
[`rp-pptx-spec.md`](../docs/specs/rp-pptx-spec.md) §13:

### Word (`.dotx`)

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

### PowerPoint (`.potx`)

```sh
cp /path/to/house.potx templates/local/
uv run rp-pptx templates inspect house               # are layouts/placeholders right?
uv run rp-pptx templates layoutmap house -o templates/local/house.layoutmap.json
$EDITOR templates/local/house.layoutmap.json         # the scaffold is a guess
uv run rp-pptx create -o out.pptx --from-markdown notes.md --template house
# open out.pptx in PowerPoint and confirm the house layouts applied
uv run rp-pptx templates manifest templates/local/house.potx \
    -o packages/rp-pptx/tests/fixtures/house.manifest.json
```

In both cases, only the last step produces a repository artifact, and it
carries nothing confidential by construction. Everything found in the earlier
steps comes back as a defect report or a spec correction, not as a file.

## Open decision

`robo-papyro-spec.md` §11.1 is unresolved: if the source of truth for these
files is SharePoint, decide whether this directory holds a synced copy or a
pointer to it. Resolve before the first template lands. The manifest loop
above lowers the stakes for both formats — CI depends on manifests rather than
on the templates themselves — but it does not answer the question.
