"""Shared typer conventions, so the suite's CLIs cannot drift apart.

Everything a CLI does that is not specific to its format lives here: the
``--json`` flag, serialization, error handling with the suite's exit codes, and
the ``doctor`` subcommand factory.

**Two error output shapes.** :func:`error_handler` can emit either the
:class:`~rp_core.models.ErrorEnvelope` from spec section 4.6 (the contract for
new CLIs) or a flat ``{"error": "<message>"}`` object on stdout. The flat form
exists because ``rp-pdf`` shipped with it as its agent-facing contract before
the suite existed; it is preserved deliberately, not by accident. New packages
use the envelope.
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
from rp_core.errors import RoboPapyroError

#: The standard ``--json`` flag. Use it verbatim so every CLI spells it the same.
json_option = Annotated[
    bool,
    typer.Option("--json", help="Emit the result as JSON instead of a human-readable table"),
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


def emit(result: BaseModel | list[BaseModel] | dict, as_json: bool) -> None:
    """Write ``result`` to stdout: JSON when ``as_json``, else a plain table."""
    if as_json:
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
def error_handler(
    *,
    as_json: bool = True,
    envelope: bool = True,
    stream: str = "stderr",
    also: tuple[type[BaseException], ...] = (),
) -> Iterator[None]:
    """Turn a :class:`RoboPapyroError` into structured output and an exit code.

    ``envelope`` selects the section 4.6 :class:`ErrorEnvelope` shape; set it
    False for the flat ``{"error": message}`` form. ``stream`` is where the
    structured output goes (``"stdout"`` or ``"stderr"``); the human-readable
    message always goes to stderr. ``also`` names extra exception types to
    treat as user-facing errors — for exceptions that predate the hierarchy,
    such as ``FileNotFoundError``.
    """
    try:
        yield
    except (RoboPapyroError, *also) as exc:
        exit_code = getattr(exc, "exit_code", 1)
        if as_json:
            if envelope and isinstance(exc, RoboPapyroError):
                payload = exc.to_envelope().model_dump(mode="json")
            else:
                payload = {"error": str(exc)}
            print(json.dumps(payload), file=sys.stdout if stream == "stdout" else sys.stderr)
        print(str(exc), file=sys.stderr)
        raise typer.Exit(exit_code) from exc


def handle_errors(
    *,
    envelope: bool = True,
    stream: str = "stderr",
    also: tuple[type[BaseException], ...] = (),
) -> Callable:
    """Decorator form of :func:`error_handler`, for whole commands."""

    def decorate(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with error_handler(envelope=envelope, stream=stream, also=also):
                return func(*args, **kwargs)

        return wrapper

    return decorate


def doctor_command(*capabilities: str) -> Callable[[bool], None]:
    """Build a ``doctor`` subcommand reporting on the named binaries.

    Register it with ``app.command("doctor")(doctor_command("soffice", ...))``.
    """

    def doctor(as_json: json_option = False) -> None:
        """Report which optional external tools are installed."""
        report = doctor_module.report(*capabilities)
        if as_json:
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
