"""Workspace invariant 1 (parent spec section 10), applied to rp-docx.

`rp-pdf` needs ``COMMAND_NAMES`` at runtime: its console script rewrites argv to
inject a default command, and a subcommand missing from the set is silently
parsed as a *filename*. rp-docx does no argv preprocessing, so nothing dispatches
on its set — which is exactly why the set needs a test of its own. Parent spec
section 10 requires the invariant to cover this CLI too, and the failure it
guards against here is different: the CLI drifting away from the surface
`rp-docx-spec.md` section 10 specifies, in either direction.

A command added to the code but not to the spec's list shows up as an untested
addition; one removed from the code but left in the list shows up as a
documented command that is not there.
"""

from __future__ import annotations

from rp_docx.cli import COMMAND_NAMES, TEMPLATES_COMMAND_NAMES, _registered, app, templates_app


def test_every_registered_command_is_in_command_names():
    assert _registered(app) <= COMMAND_NAMES


def test_command_names_lists_nothing_unregistered():
    assert COMMAND_NAMES <= _registered(app)


def test_the_templates_subcommands_match_too():
    assert _registered(templates_app) == TEMPLATES_COMMAND_NAMES


def test_the_command_surface_is_the_one_the_spec_specifies():
    """rp-docx-spec.md section 10, transcribed. If this fails, one of the two is
    out of date and the spec is the one to check first."""
    assert COMMAND_NAMES == {
        "doctor",
        "index",
        "text",
        "markdown",
        "tables",
        "images",
        "comments",
        "changes",
        "props",
        "create",
        "append",
        "replace",
        "template",
        "accept",
        "reject",
        "templates",
        "convert",
        "render",
    }


def test_no_json_flag_on_any_command():
    """Parent spec section 4.6: there is no --json flag anywhere in the suite.

    Two tools differing on the shape of every *successful* call would be a worse
    inconsistency than any error-path difference, because it hits the common
    path. rp-pdf enforces this for itself; rp-docx must not reintroduce it.
    """
    for target in (app, templates_app):
        for command in target.registered_commands:
            for parameter in command.callback.__annotations__.values():
                assert "--json" not in str(parameter)
