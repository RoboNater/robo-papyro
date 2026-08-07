"""Workspace invariant 1 (parent spec section 10), applied to rp-pptx.

Nothing dispatches on ``COMMAND_NAMES`` at runtime here — rp-pptx does no argv
preprocessing, so unlike rp-pdf a missing name would not be silently parsed as a
filename. The set needs a test for a different reason: to hold the CLI to the
surface ``rp-pptx-spec.md`` section 10 specifies, in **both** directions. A
command in the code but not in the set is an untested addition; one in the set
but not in the code is a documented command that does not exist.

The previous version of this package shipped the constant without the test, and
it already listed a ``set-notes`` command that was never registered — which is
exactly the drift these three assertions exist to catch.
"""

from __future__ import annotations

from rp_pptx.cli import (
    COMMAND_NAMES,
    SLIDES_COMMAND_NAMES,
    TEMPLATES_COMMAND_NAMES,
    _registered,
    app,
    slides_app,
    templates_app,
)


def test_every_registered_command_is_in_command_names():
    assert _registered(app) <= COMMAND_NAMES


def test_command_names_lists_nothing_unregistered():
    assert COMMAND_NAMES <= _registered(app)


def test_the_slides_subcommands_match():
    assert _registered(slides_app) == SLIDES_COMMAND_NAMES


def test_the_templates_subcommands_match():
    assert _registered(templates_app) == TEMPLATES_COMMAND_NAMES


def test_the_command_surface_is_the_one_the_spec_specifies():
    """rp-pptx-spec.md section 10, transcribed. If this fails, one of the two is
    out of date and the spec is the one to check first."""
    assert COMMAND_NAMES == {
        "doctor",
        "index",
        "text",
        "markdown",
        "tables",
        "images",
        "notes",
        "comments",
        "charts",
        "props",
        "create",
        "append",
        "replace",
        "template",
        "set-notes",
        "slides",
        "templates",
        "convert",
        "render",
    }


def test_no_json_flag_on_any_command():
    """Parent spec section 4.6: there is no ``--json`` flag anywhere in the
    suite. JSON is the default and ``--plain`` is the opt-out, so a ``--json``
    would imply the default is something else. rp-pdf enforces this for itself;
    rp-pptx must not reintroduce it."""
    for target in (app, slides_app, templates_app):
        for command in target.registered_commands:
            for parameter in command.callback.__annotations__.values():
                assert "--json" not in str(parameter)


def test_every_read_command_offers_plain():
    """Section 10: ``--plain`` is the human opt-out on every read command."""
    reads = {"index", "text", "tables", "images", "notes", "comments", "charts", "props"}
    for command in app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        if name in reads:
            assert "plain" in command.callback.__annotations__, name
