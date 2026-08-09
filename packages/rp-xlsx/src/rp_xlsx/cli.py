"""Typer CLI wrapping rp_xlsx. Parses args, calls the library, serializes output.

Conventions, all inherited from ``rp_core.clikit`` rather than restated here:

* **JSON to stdout by default**; ``--plain`` is the human opt-out. There is no
  ``--json`` flag anywhere in the suite (parent spec section 4.6).
* Errors are an ``ErrorEnvelope`` on **stderr**, with the exit code carried by
  the error class: 1 for input errors, 2 for a missing external binary, 3 for an
  unreadable or unsupported file.
* **Never overwrite an input file** without ``--in-place``. Every editing command
  insists on ``-o`` or ``--in-place`` and says so rather than guessing.

Built out fully in Phase 3 step 10 (spec section 10); this scaffold registers
only ``doctor`` so the distribution resolves and ``rp xlsx``/``rp-xlsx`` are
reachable while the rest of the package is built.
"""

from __future__ import annotations

import typer

from rp_core import clikit

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rp-xlsx — spreadsheet toolkit (JSON-first library and CLI).",
)

app.command("doctor")(clikit.doctor_command("soffice", "pdftoppm", "pdfinfo"))
