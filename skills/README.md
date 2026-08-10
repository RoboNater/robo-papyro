# Skills

Agent skills for the four robo-papyro CLIs, one per format:

| Skill | Covers | Full guide |
|---|---|---|
| [`pdf-toolkit`](pdf-toolkit/SKILL.md) | `rp-pdf` — read, search, extract, convert | [docs/usage.md](../docs/usage.md) |
| [`word-toolkit`](word-toolkit/SKILL.md) | `rp-docx` — read, create, edit, template | [docs/usage-docx.md](../docs/usage-docx.md) |
| [`powerpoint-toolkit`](powerpoint-toolkit/SKILL.md) | `rp-pptx` — read, create, edit, slide operations | [docs/usage-pptx.md](../docs/usage-pptx.md) |
| [`spreadsheet-toolkit`](spreadsheet-toolkit/SKILL.md) | `rp-xlsx` — read, create, edit, sheet operations | [docs/usage-xlsx.md](../docs/usage-xlsx.md) |

Each is a single `SKILL.md` with YAML frontmatter (`name`, `description`) and
no scripts: the CLIs *are* the interface, and a skill that wrapped them in
helper scripts would be a second surface to keep in sync with the first.

## Skills or MCP?

Both expose the same library, and which one you want depends on the agent:

- **Skills** are for an agent with shell access. Nothing to run, nothing to
  configure, and the agent gets the whole CLI including the parts `rp-mcp`
  deliberately does not expose (rendering, the AI review pass).
- **[`rp-mcp`](../packages/rp-mcp)** is for a client with no shell. It also
  adds a path sandbox, which a shell-using agent does not have and does not
  get from a skill — if confining an agent to a directory matters, that is a
  reason to prefer the server.

They are not alternatives to keep separate: a claim in a skill and the same
claim in `docs/usage-*.md` describe one library, so changing behaviour means
grepping for the claim rather than editing whichever file you were looking at.

## What is in them

Not a command reference — the usage guides are that, and duplicating them would
guarantee drift. Each skill covers the shape of the tool (JSON to stdout,
`--plain` to opt out, errors as an envelope on stderr, the exit-code taxonomy)
and then spends most of its length on **the things that go wrong**, because
those are what an agent cannot infer from `--help`:

- PDF page numbers follow the document's own page labels, not file position.
- `rp-docx replace` reports a per-key count, and a count of 0 is not success.
- `rp-pptx comments` *fails* on modern threaded comments rather than reporting
  none — so an agent must not conclude the deck has no comments.
- Slide numbers change after a delete or a reorder, so chained operations must
  be re-planned against the new file.
- Style and layout resolution never falls back; a missing style is an error
  naming the style, not a document that looks wrong.
- `rp-xlsx` drops every formula's cached value on every write — that is a
  property of the underlying library, not a bug, and `has_cached_values`
  says so up front rather than leaving an agent to discover `None` values.
- `rp-xlsx` refuses an edit that would silently delete a part it cannot
  model (exit 3), rather than dropping threaded comments, pivot caches, or
  similar without saying so; `--allow-lossy` opts in and reports the loss.

## Installing

Copy a skill directory into wherever your agent reads skills from — for Claude
Code, `~/.claude/skills/` for a user-wide skill or `.claude/skills/` in a
project. The skills assume `rp-pdf`, `rp-docx`, `rp-pptx`, and `rp-xlsx` are on
`PATH`; `uv sync` in this checkout puts them there.
