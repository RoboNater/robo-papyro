# Templates

Corporate `.dotx` / `.docx` style templates used by `rp-docx` (Phase 1).

**Status: pending.** No templates have been added yet. `rp-docx` does not exist
yet, so nothing reads this directory.

## What goes here

House templates that `rp_docx.templates.resolve_template()` resolves by bare
name — `memo` resolves to `memo.dotx` here (after `$RP_TEMPLATE_DIR`, which
takes precedence). An optional `<name>.stylemap.json` sits beside each template
and maps logical roles (`h1`, `body`, `bullet`, …) to that template's real style
names; see `docs/specs/rp-docx-spec.md` §5.

## Required per template

Every template added here must be recorded in the table below. A template with
no owner and no canonical location is a liability — a stale letterhead is worse
than a missing one.

| Template | Owner | Canonical source | Last synced |
|---|---|---|---|
| _(none yet)_ | | | |

## Open decision

`robo-papyro-spec.md` §11.2 is unresolved: if the source of truth for these
files is SharePoint, decide whether this directory holds a synced copy or a
pointer to it. Resolve before the first template lands.
