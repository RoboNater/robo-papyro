"""Workspace invariant 1 (spec section 10): command registration.

`rp-pdf FILE.pdf` with no subcommand runs the config's `[default].command`.
The dispatcher decides whether the first token is a subcommand by looking it up
in `COMMAND_NAMES`, so a command registered with typer but missing from that
set is silently parsed as a *filename* — the user gets "No such file: doctor"
instead of the command they asked for. This bit `doctor` during Phase 0.
"""

from __future__ import annotations

import typer.main

from rp_pdf.cli import COMMAND_NAMES, _inject_default_command, app


def registered_command_names() -> set[str]:
    return {
        command.name or typer.main.get_command_name(command.callback.__name__)
        for command in app.registered_commands
    }


def test_every_registered_command_is_in_command_names():
    assert registered_command_names() <= COMMAND_NAMES


def test_command_names_lists_nothing_unregistered():
    """The other direction: a stale entry would shadow a real filename."""
    assert COMMAND_NAMES <= registered_command_names()


def test_a_registered_command_is_not_parsed_as_a_filename():
    """The consequence the set exists to prevent, checked end to end."""
    for name in sorted(registered_command_names()):
        assert _inject_default_command(["rp-pdf", name]) == ["rp-pdf", name]


def test_a_filename_still_gets_the_default_command():
    assert _inject_default_command(["rp-pdf", "report.pdf"]) == ["rp-pdf", "index", "report.pdf"]
