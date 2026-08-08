"""What every tool in every server shares: the error bridge and the argument types.

**The error bridge is the important part.** An MCP client sees a failure as a
string, and a suite error is a structured thing with a type, a hint, and an exit
code (parent spec section 4.1). :func:`guarded` keeps both: it raises a
``ToolError`` whose text is the human-readable message followed by the
:class:`~rp_core.models.ErrorEnvelope` as the final line — the same ordering
``rp_core.clikit.error_handler`` writes to stderr, for the same reason. An agent
that has learned to read the last line of a failed ``rp-pdf`` run reads the last
line of a failed tool call and finds the same keys.

Nothing here re-implements a leaf's error handling. The leaves already raise
:class:`~rp_core.errors.RoboPapyroError` subclasses carrying their own exit
codes, and :func:`guarded` passes those through untouched — a missing binary
still says 2, an unreadable file still says 3.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from rp_core.errors import RoboPapyroError, envelope_for

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from rp_mcp.sandbox import Sandbox

F = TypeVar("F", bound=Callable[..., Any])


def error_text(exc: BaseException) -> str:
    """A suite error as a tool-error body: message, then envelope, last line.

    The envelope goes last so it stays findable when the message itself runs to
    several lines, which is the same rule the CLIs follow on stderr.
    """
    return f"{exc}\n{envelope_for(exc).model_dump_json()}"


def guarded(func: F) -> F:
    """Turn any :class:`~rp_core.errors.RoboPapyroError` into a ``ToolError``.

    Applied *under* ``@server.tool()`` so the schema is still generated from the
    wrapped function's signature — ``functools.wraps`` copies ``__annotations__``
    and sets ``__wrapped__``, which is what ``inspect.signature`` follows. The
    invariant test asserts the generated input schemas match the signatures, so
    this cannot rot silently.

    Only suite errors are caught. Anything else is a bug in this package or a
    leaf, and a bug should arrive as a traceback in the server log rather than
    as a tidy message that reads like an expected outcome.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except RoboPapyroError as exc:
            raise ToolError(error_text(exc)) from exc

    return wrapper  # type: ignore[return-value]


#: A file the server reads. Relative paths are taken against the first root, so
#: a client configured with ``--root /docs`` can say ``"report.pdf"``.
PathArg = Annotated[
    str,
    Field(description="Path to the file. Absolute, or relative to the server's first root."),
]

#: A file the server creates. Never an existing path.
OutputArg = Annotated[
    str,
    Field(
        description="Path for the new file. Absolute, or relative to the server's write root. "
        "Must not exist — these tools never overwrite."
    ),
]

#: A directory the server writes into. Created if absent.
OutputDirArg = Annotated[
    str | None,
    Field(
        description="Directory to extract files into, under the server's write root. "
        "Omit to return metadata only, with nothing written."
    ),
]

#: The suite's range spec, spelled identically in every CLI (parent spec §4.3).
PagesArg = Annotated[
    str,
    Field(
        description="Page spec: 'all', '5', '3-7', '-4' (up to 4), '7-' (7 to the end), "
        "or a mixed list like '1,3-5,9'. Interpreted against the PDF's page labels "
        "unless physical is true."
    ),
]

SlidesArg = Annotated[
    str,
    Field(
        description="Slide spec, 1-based: 'all', '2', '3-7', '-4', '7-', or '1,3-5,9'.",
    ),
]

PhysicalArg = Annotated[
    bool,
    Field(
        description="Number pages by 1-based physical position instead of the document's "
        "own page labels."
    ),
]

PasswordArg = Annotated[
    str | None,
    Field(description="Password for an encrypted PDF. Omit for an unencrypted one."),
]


def _looks_like_a_path(text: str) -> bool:
    """The rule both leaves use to tell a template path from a template name.

    ``rp_docx.templates.resolve_template`` and
    ``rp_pptx.templates.resolve_template`` each spell this inline: a suffix or a
    separator means the caller wrote a path. It is restated here rather than
    imported because here it decides *whether the sandbox applies*, and a
    security boundary that depends on a leaf's private helper is one refactor
    away from silently widening. The invariant tests assert the two agree.
    """
    return bool(Path(text).suffix or os.sep in text or (os.altsep and os.altsep in text))


def sandboxed_template(sandbox: Sandbox, value: str | None) -> str | Path | None:
    """A template argument, with any *path* form confined to the sandbox.

    A bare name (``"memo"``) is passed through for the leaf to look up in its
    template directories — those are server-side configuration, deliberately
    outside the roots, exactly like the bundled default. A path form is resolved
    like any other input, so a tool call cannot reach a ``.dotx`` the server was
    never pointed at.
    """
    if value is None:
        return None
    return sandbox.resolve_input(value) if _looks_like_a_path(str(value)) else value


__all__ = [
    "OutputArg",
    "OutputDirArg",
    "PagesArg",
    "PasswordArg",
    "PathArg",
    "PhysicalArg",
    "SlidesArg",
    "error_text",
    "guarded",
    "sandboxed_template",
]
