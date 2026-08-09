# robo-papyro

The meta-distribution: installs the suite — `rp-core`, `rp-pdf`, `rp-docx`,
`rp-pptx`, and [`rp-mcp`](../rp-mcp) — and provides the umbrella `rp` command.

**The MCP servers are included, not optional.** `pip install robo-papyro` gets
`rp mcp` and the MCP SDK with it. The alternative was an extra, which keeps an
ASGI stack away from CLI-only users at the price of an agent integration nobody
discovers; for a suite built for agentic document work that is the wrong trade.
Install a leaf directly if you want only the document toolkit.

```bash
rp --help              # lists whichever subcommands are installed
rp doctor              # external-tool capability report across the suite
rp pdf index FILE      # same code path as `rp-pdf index FILE`
rp docx index FILE.docx      # same code path as `rp-docx index FILE.docx`
rp pptx index FILE.pptx      # same code path as `rp-pptx index FILE.pptx`
```

`rp` finds its subcommands through the `robo_papyro.commands` entry-point group,
never by importing leaf packages. A package registers itself with:

```toml
[project.entry-points."robo_papyro.commands"]
pdf = "rp_pdf.cli:app"
```

**One difference from the leaf CLIs.** `rp-pdf FILE.pdf` runs the config's
`[default].command` via argv rewriting in its console script. `rp` registers the
typer app rather than the script, so `rp pdf FILE.pdf` needs an explicit
subcommand — `rp pdf index FILE.pdf`.

Spec: [`docs/specs/robo-papyro-spec.md`](../../docs/specs/robo-papyro-spec.md) §6.
