"""The `rp` dispatcher.

Discovery, not imports. This module enumerates the ``robo_papyro.commands``
entry-point group and registers each discovered typer app as a subcommand. It
must never ``import rp_pdf`` or ``import rp_docx`` directly — that is what makes
`rp` degrade gracefully:

* ``rp pdf index FILE`` and ``rp-pdf index FILE`` are the same code path
* with only ``rp-pdf`` installed, ``rp`` exposes just ``pdf``, and says so
* adding ``rp-xlsx`` later needs no change here
* a leaf package that fails to import becomes a warning in ``rp --help``,
  not a broken CLI

**Known gap.** A leaf CLI's own console script may do argv preprocessing before
handing off to typer — ``rp-pdf FILE.pdf`` runs the config's default command
that way. `rp` registers the typer app, not the console script, so
``rp pdf FILE.pdf`` requires an explicit subcommand. Teaching `rp` about it
would mean teaching it leaf-specific knowledge, which is exactly what entry-point
discovery exists to avoid.
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points

import typer

from rp_core import clikit

COMMAND_GROUP = "robo_papyro.commands"

#: Binaries `rp doctor` reports on: the union across the suite. A leaf package
#: that needs none of them simply has nothing to report.
CAPABILITIES = ("soffice", "pdftoppm", "pdftotext", "pdfinfo")

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="robo-papyro — document tooling for agentic coding tools.",
)

app.command("doctor")(clikit.doctor_command(*CAPABILITIES))


def discover() -> tuple[list[tuple[str, typer.Typer]], list[tuple[str, Exception]]]:
    """Load every registered subcommand app, sorted by name.

    Returns ``(loaded, failed)``. A leaf whose import raises is reported rather
    than propagated: one broken package must not take down the whole CLI.
    """
    loaded: list[tuple[str, typer.Typer]] = []
    failed: list[tuple[str, Exception]] = []
    for entry in sorted(entry_points(group=COMMAND_GROUP), key=lambda e: e.name):
        try:
            command = entry.load()
        except Exception as exc:  # a broken leaf degrades to a warning
            failed.append((entry.name, exc))
            continue
        if isinstance(command, typer.Typer):
            loaded.append((entry.name, command))
        else:
            failed.append(
                (entry.name, TypeError(f"expected a typer.Typer, got {type(command).__name__}"))
            )
    return loaded, failed


def build(target: typer.Typer) -> tuple[list[str], list[tuple[str, Exception]]]:
    """Register the discovered subcommands on ``target``."""
    loaded, failed = discover()
    for name, command in loaded:
        target.add_typer(command, name=name)
    return [name for name, _ in loaded], failed


def warn(installed: list[str], failed: list[tuple[str, Exception]]) -> None:
    for name, exc in failed:
        print(f"warning: could not load the '{name}' subcommand ({exc})", file=sys.stderr)
    if not installed:
        print(
            "warning: no robo-papyro subcommands are installed. Install a leaf "
            "package (for example 'uv pip install rp-pdf') to get one.",
            file=sys.stderr,
        )


def main() -> None:
    """Console-script entry point."""
    warn(*build(app))
    app()


if __name__ == "__main__":
    main()
