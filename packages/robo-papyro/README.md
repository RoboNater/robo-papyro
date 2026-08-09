# robo-papyro

The meta-distribution: installs the document leaves — `rp-core`, `rp-pdf`,
`rp-docx`, `rp-pptx` — and provides the umbrella `rp` command.

**The MCP servers are opt-in.** `pip install robo-papyro` carries none of the
MCP SDK; `pip install robo-papyro[mcp]` adds [`rp-mcp`](../rp-mcp), and `rp mcp`
appears once it is installed — by that extra or on its own.

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
