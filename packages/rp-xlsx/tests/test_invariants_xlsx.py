"""Workspace invariant 1 (parent spec section 10), applied to rp-xlsx.

Holds the CLI to the surface docs/specs/rp-xlsx-spec.md section 10
specifies, in **both** directions: a command in the code but not in
COMMAND_NAMES is an untested addition, and one in COMMAND_NAMES but not in
the code is a documented command that does not exist. rp-pptx's equivalent
test module already caught a phantom `set-notes` command this pattern was
written to prevent; the same shape applies here.
"""

from __future__ import annotations

from rp_xlsx.cli import (
    COMMAND_NAMES,
    SHEETS_COMMAND_NAMES,
    TEMPLATES_COMMAND_NAMES,
    _registered,
    app,
    sheets_app,
    templates_app,
)


def test_every_registered_command_is_in_command_names():
    assert _registered(app) <= COMMAND_NAMES


def test_command_names_lists_nothing_unregistered():
    assert COMMAND_NAMES <= _registered(app)


def test_the_sheets_subcommands_match():
    assert _registered(sheets_app) == SHEETS_COMMAND_NAMES


def test_the_templates_subcommands_match():
    assert _registered(templates_app) == TEMPLATES_COMMAND_NAMES


def test_the_command_surface_is_the_one_the_spec_specifies():
    """rp-xlsx-spec.md section 10, transcribed. If this fails, one of the two
    is out of date and the spec is the one to check first."""
    assert COMMAND_NAMES == {
        "doctor",
        "index",
        "data",
        "cells",
        "formulas",
        "tables",
        "names",
        "comments",
        "images",
        "charts",
        "props",
        "markdown",
        "fidelity",
        "create",
        "set",
        "append",
        "replace",
        "template",
        "sheets",
        "templates",
        "convert",
        "render",
    }


def test_no_json_flag_on_any_command():
    """Parent spec section 4.6: there is no ``--json`` flag anywhere in the
    suite. JSON is the default and ``--plain`` is the opt-out, so a
    ``--json`` would imply the default is something else."""
    for target in (app, sheets_app, templates_app):
        for command in target.registered_commands:
            for parameter in command.callback.__annotations__.values():
                assert "--json" not in str(parameter)


def test_every_read_command_offers_plain():
    """Section 10: ``--plain`` is the human opt-out on every read command."""
    reads = {
        "index",
        "data",
        "cells",
        "formulas",
        "tables",
        "names",
        "comments",
        "images",
        "charts",
        "props",
        "fidelity",
    }
    for command in app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        if name in reads:
            assert "plain" in command.callback.__annotations__, name


def test_markdown_has_no_plain_flag():
    """``markdown`` is the one stdout exception (spec section 10, mirroring
    the other two leaves): with no ``-o`` it prints Markdown directly, so
    there is no JSON-vs-plain choice to make."""
    for command in app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        if name == "markdown":
            assert "plain" not in command.callback.__annotations__


def test_allow_lossy_is_present_on_every_command_that_can_open_an_existing_workbook():
    """spec section 6: every function that opens and re-saves an existing
    workbook goes through the guard, and every command reaching such a
    function exposes ``--allow-lossy`` to override it. ``create`` and
    ``template`` are not exceptions -- ``create --template`` opens and
    re-saves the template, and ``template`` always opens the one it fills;
    only a template-*less* ``create`` opens nothing existing, and the flag
    is still present there because the same command handles both cases."""
    edits = {"create", "set", "append", "replace", "template"}
    for command in app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        if name in edits:
            assert "allow_lossy" in command.callback.__annotations__, name
    for command in sheets_app.registered_commands:
        if command.name != "list":
            assert "allow_lossy" in command.callback.__annotations__, command.name


def test_every_editing_command_takes_out_and_in_place():
    """Never overwrite an input file without --in-place (spec section 10)."""
    edits = {"set", "append", "replace"}
    for command in app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        if name in edits:
            assert "out" in command.callback.__annotations__, name
            assert "in_place" in command.callback.__annotations__, name
    for command in sheets_app.registered_commands:
        if command.name != "list":
            assert "out" in command.callback.__annotations__, command.name
            assert "in_place" in command.callback.__annotations__, command.name
