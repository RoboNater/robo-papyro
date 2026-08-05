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
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from rp_core import doctor as doctor_module
from rp_core.errors import RoboPapyroError, envelope_for

#: The standard ``--plain`` flag. Use it verbatim so every CLI spells it the same.
plain_option = Annotated[
    bool,
    typer.Option("--plain", help="Human-readable output instead of the default JSON"),
]


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
