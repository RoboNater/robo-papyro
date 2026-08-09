"""Every command a skill quotes must be one the CLI actually accepts.

`skills/*/SKILL.md` is documentation that an agent will copy *verbatim*, which
makes each quoted command a claim about a command line. Five were wrong on the
first pass: four found only by running them by hand, and one (`--ocr` without
`--ai`) found in review because it needs an API key and so was never run.

This closes the part that can be closed mechanically — a flag that does not
exist on the command it is used with. It cannot catch a *semantic* constraint
like "`--ocr` requires `--ai`"; those stay a matter of reading the spec, which
is now written down in AGENTS.md.

Options are read from the **parsed** click command, never from rendered
`--help`: rich detects `CI`/`GITHUB_ACTIONS` and splits an option's leading
hyphen into its own span, so a text search passes for the wrong reason on
exactly the run that gates a merge.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import typer

from rp_docx.cli import app as docx_app
from rp_mcp.cli import app as mcp_app
from rp_pdf.cli import app as pdf_app
from rp_pptx.cli import app as pptx_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))

#: The console scripts a skill may quote, and the typer app behind each.
APPS = {
    "rp-pdf": pdf_app,
    "rp-docx": docx_app,
    "rp-pptx": pptx_app,
    "rp-mcp": mcp_app,
}

#: `rp <name> ...` reaches the same app through the umbrella's entry points.
UMBRELLA = {"pdf": "rp-pdf", "docx": "rp-docx", "pptx": "rp-pptx", "mcp": "rp-mcp"}

#: A long option, ignoring any trailing prose punctuation.
LONG_OPTION = re.compile(r"^--[a-z][a-z0-9-]*$")

#: Options click provides on every command; never declared by the suite.
UNIVERSAL = {"--help"}


def _command_lines(text: str) -> list[str]:
    """Every quoted invocation in a skill: fenced blocks *and* inline spans.

    Both matter. The fenced blocks hold the worked examples, but the reading
    tables quote commands inline — and `--table`, one of the flags that did not
    exist, was in a table rather than a block.
    """
    fenced = re.findall(r"```(?:sh|bash|console)?\n(.*?)```", text, re.S)
    lines = [line for block in fenced for line in block.splitlines()]
    lines += re.findall(r"`([^`\n]+)`", text)
    return [line.strip() for line in lines if line.strip()]


def _tokens(line: str) -> list[str]:
    """Split an invocation into tokens, dropping documentation punctuation.

    Optional-argument brackets and escaped table pipes are notation, not
    arguments; a trailing `#` comment is not part of the command.
    """
    line = line.split("#", 1)[0]
    line = line.replace("[", " ").replace("]", " ").replace("\\|", "|")
    return line.split()


def _resolve(tokens: list[str]) -> tuple[object, list[str], list[str]] | None:
    """(click command, the path naming it, the remaining tokens), or None.

    Returns None for anything that is not an invocation of a suite CLI, so
    prose in backticks is skipped rather than failed.
    """
    if not tokens:
        return None
    executable, *rest = tokens
    if executable == "rp" and rest and rest[0] in UMBRELLA:
        executable, rest = UMBRELLA[rest[0]], rest[1:]
    if executable not in APPS:
        return None

    command = typer.main.get_command(APPS[executable])
    path = [executable]
    while rest and hasattr(command, "commands"):
        candidate = command.commands.get(rest[0])
        if candidate is None:
            break
        path.append(rest[0])
        command, rest = candidate, rest[1:]
    return command, path, rest


def _declared(command) -> set[str]:
    return {
        option for param in command.params for option in (*param.opts, *param.secondary_opts)
    } | UNIVERSAL


def _cases() -> list[tuple[str, str, str, str]]:
    """(skill name, invocation, command path, flag) for every flag quoted."""
    found = []
    for skill in SKILLS:
        for line in _command_lines(skill.read_text(encoding="utf-8")):
            resolved = _resolve(_tokens(line))
            if resolved is None:
                continue
            command, path, rest = resolved
            for token in rest:
                if LONG_OPTION.match(token):
                    found.append((skill.parent.name, line, " ".join(path), token))
    return found


CASES = _cases()


def test_the_skills_quote_commands_at_all():
    """Guards the guard: a parser that matches nothing would pass vacuously."""
    assert len({case[2] for case in CASES}) >= 10, CASES


@pytest.mark.parametrize(
    ("skill", "line", "path", "flag"),
    CASES,
    ids=[f"{c[0]}:{c[2]}:{c[3]}" for c in CASES],
)
def test_every_flag_a_skill_quotes_exists(skill, line, path, flag):
    command, _, _ = _resolve(_tokens(line))
    declared = _declared(command)
    assert flag in declared, (
        f"{skill} quotes `{line}`, but {path} has no {flag}. "
        f"It accepts: {', '.join(sorted(declared))}"
    )


def test_every_command_a_skill_quotes_exists():
    """A subcommand that does not exist resolves to its parent, leaving a
    leftover word — which is how `rp-docx props --author` would have read."""
    unknown = []
    for skill in SKILLS:
        for line in _command_lines(skill.read_text(encoding="utf-8")):
            tokens = _tokens(line)
            resolved = _resolve(tokens)
            if resolved is None:
                continue
            command, path, rest = resolved
            if len(path) == 1 and rest and not rest[0].startswith("-"):
                unknown.append(f"{skill.parent.name}: `{line}` — no {path[0]} {rest[0]!r} command")
    assert not unknown
