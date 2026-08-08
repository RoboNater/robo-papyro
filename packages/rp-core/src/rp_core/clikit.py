"""Shared typer conventions, so the suite's CLIs cannot drift apart.

Everything a CLI does that is not specific to its format lives here: the
``--plain`` flag, serialization, error handling with the suite's exit codes, and
the ``doctor`` subcommand factory.

**JSON by default, ``--plain`` to opt out.** The suite's primary consumer is a
program, so the machine-readable form is what you get without asking. There is
no ``--json`` flag anywhere in the suite (spec section 4.6): two tools differing
on the shape of every *successful* call would be a worse inconsistency than any
error-path difference, because it hits the common path.

**One error output shape.** :func:`error_handler` writes the
:class:`~rp_core.models.ErrorEnvelope` from spec section 4.1 to stderr and exits
with the error's code. There is no second shape and no argument selecting one:
the primary consumer is an agent deciding what to do next, and it must not have
to know which tool failed in order to find ``type`` and ``exit_code``.

**Human affordances are stderr-only and terminal-gated.** The job description
and the progress line (:func:`job`) exist for the person watching a long run;
they are written to stderr so stdout stays exactly what it was, and they default
to *on only when stderr is a terminal*, so an agent capturing output sees no
change at all. ``--describe``/``--progress`` force them on regardless.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from functools import wraps
from typing import IO, Annotated, Any

import typer
from pydantic import BaseModel

from rp_core import doctor as doctor_module
from rp_core import progress as progress_module
from rp_core.errors import RoboPapyroError, envelope_for

#: The standard ``--plain`` flag. Use it verbatim so every CLI spells it the same.
plain_option = Annotated[
    bool,
    typer.Option("--plain", help="Human-readable output instead of the default JSON"),
]

#: Progress reporting on stderr. Tri-state: unset means "on when stderr is a
#: terminal". Spell it verbatim so every CLI in the suite agrees.
progress_option = Annotated[
    bool | None,
    typer.Option(
        "--progress/--no-progress",
        help="Show a live progress line on stderr while the job runs "
        "(default: on when stderr is a terminal)",
    ),
]

#: The pre-flight job description. Tri-state, same default as ``--progress``.
describe_option = Annotated[
    bool | None,
    typer.Option(
        "--describe/--no-describe",
        help="Print what the job is about to do, from the resolved options, "
        "before it starts (default: on when stderr is a terminal)",
    ),
]

#: A job description: ordered ``(name, value)`` rows under a title.
JobEntries = Sequence[tuple[str, str]]


def to_jsonable(result: BaseModel | list[BaseModel] | dict | Any) -> Any:
    """Pydantic models (or lists of them) as plain JSON-compatible data."""
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [to_jsonable(item) for item in result]
    return result


def dump_json(result: BaseModel | list[BaseModel] | dict, *, indent: int | None = 2) -> None:
    """Write ``result`` to stdout as JSON."""
    print(json.dumps(to_jsonable(result), indent=indent, ensure_ascii=False))


def emit(result: BaseModel | list[BaseModel] | dict, plain: bool = False) -> None:
    """Write ``result`` to stdout: JSON, or a plain table when ``plain``."""
    if not plain:
        dump_json(result)
        return
    data = to_jsonable(result)
    if isinstance(data, dict):
        _print_record(data)
    elif isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
        _print_table(data)
    else:
        print(data)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _print_record(record: dict) -> None:
    width = max((len(k) for k in record), default=0)
    for key, value in record.items():
        print(f"{key:<{width}}  {_cell(value)}")


def _print_table(rows: list[dict]) -> None:
    columns = list(rows[0])
    widths = {c: max(len(c), *(len(_cell(row.get(c))) for row in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(_cell(row.get(c)).ljust(widths[c]) for c in columns))


@contextmanager
def error_handler(*, also: tuple[type[BaseException], ...] = ()) -> Iterator[None]:
    """Turn a :class:`RoboPapyroError` into an ``ErrorEnvelope`` and an exit code.

    Both the human-readable message and the envelope go to stderr, so stdout
    carries only results. **The envelope is written last**, on a single line, so
    that it is the final line of stderr no matter what warnings a command
    printed on its way to failing — that is what makes it findable without
    parsing the whole stream. ``also`` names extra exception types to treat as
    user-facing errors — for a third-party exception a leaf package would
    otherwise let escape as a traceback.
    """
    try:
        yield
    except (RoboPapyroError, *also) as exc:
        envelope = envelope_for(exc)
        print(str(exc), file=sys.stderr)
        print(envelope.model_dump_json(), file=sys.stderr)
        raise typer.Exit(envelope.error.exit_code) from exc


def handle_errors(*, also: tuple[type[BaseException], ...] = ()) -> Callable:
    """Decorator form of :func:`error_handler`, for whole commands."""

    def decorate(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with error_handler(also=also):
                return func(*args, **kwargs)

        return wrapper

    return decorate


def parse_bool(text: str | None) -> bool | None:
    """``"1"``/``"true"``/``"yes"``/``"on"`` → ``True`` and their opposites →
    ``False``, case-insensitively; anything else (including ``None`` and the
    empty string) → ``None``.

    Environment variables are strings, and ``bool("false")`` is ``True`` — a
    tri-state flag read from the environment needs this rather than truthiness.
    Unrecognized text resolves to ``None`` (fall through to the next source)
    rather than to ``False``, so a typo cannot silently disable something.
    """
    if text is None:
        return None
    value = text.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def display_enabled(
    flag: bool | None,
    *,
    env_value: str | None = None,
    config_value: object = None,
    stream: IO[str] | None = None,
) -> bool:
    """Resolve ``--describe``/``--progress``: flag → env → config → terminal.

    The final fallback is the only interesting one: these are affordances for a
    human watching the run, so "is anyone watching" — ``stderr.isatty()`` — is
    the honest default. A piped or redirected stderr, which is what an agent,
    a cron job, and a CI runner all have, turns them off without anyone
    configuring anything.
    """
    if flag is not None:
        return flag
    from_env = parse_bool(env_value)
    if from_env is not None:
        return from_env
    if isinstance(config_value, bool):
        return config_value
    return progress_module.is_interactive(stream)


def job_lines(title: str, entries: JobEntries) -> list[str]:
    """The job description as lines: a title, then aligned ``name  value`` rows."""
    lines = [title]
    width = max((len(name) for name, _ in entries), default=0)
    lines.extend(f"  {name:<{width}}  {value}" for name, value in entries)
    return lines


def announce_job(title: str, entries: JobEntries, *, stream: IO[str] | None = None) -> None:
    """Write the job description to stderr, so stdout keeps carrying only results."""
    out = sys.stderr if stream is None else stream
    for line in job_lines(title, entries):
        print(line, file=out)


@contextmanager
def job(
    title: str,
    entries: JobEntries = (),
    *,
    describe: bool = False,
    progress: bool = False,
    stream: IO[str] | None = None,
) -> Iterator[progress_module.Progress]:
    """Run a job with its description and progress reporting, both optional.

    Prints the description (when ``describe``), then yields the
    :class:`~rp_core.progress.Progress` to hand to the library call — the real
    reporter when ``progress``, otherwise the no-op one, so the call site does
    not branch. The reporter is always closed, including on the error path,
    which is what guarantees a half-painted progress line never ends up in front
    of an error message.

    **The whole job is itself a step**, which is what makes the reporter live
    from the first instruction inside the block rather than from whenever the
    first inner step happens to open. The gap matters: opening the file is a
    blocking read, and a job hung on a dead network mount before it reached any
    counted work would otherwise show nothing at all — the exact failure this
    reporting exists to make visible. Inner steps take over the display while
    they run and hand it back here, so this also reports total elapsed time.
    """
    if describe:
        announce_job(title, entries, stream=stream)
    reporter = progress_module.reporter(progress, stream=stream)
    try:
        with reporter.step(title):
            yield reporter
    finally:
        reporter.close()


def doctor_command(*capabilities: str) -> Callable[[bool], None]:
    """Build a ``doctor`` subcommand reporting on the named binaries.

    Register it with ``app.command("doctor")(doctor_command("soffice", ...))``.
    """

    def doctor(plain: plain_option = False) -> None:
        """Report which optional external tools are installed."""
        report = doctor_module.report(*capabilities)
        if not plain:
            dump_json(report)
            return
        # Install hints are long; show them only for what is actually missing,
        # below the table, rather than as a column that wraps the terminal.
        _print_table(
            [{k: v for k, v in row.items() if k != "install_hint"} for row in to_jsonable(report)]
        )
        missing = [c for c in report if not c.available]
        if missing:
            print("", file=sys.stderr)
            for capability in missing:
                print(f"{capability.name}: {capability.install_hint}", file=sys.stderr)

    return doctor
