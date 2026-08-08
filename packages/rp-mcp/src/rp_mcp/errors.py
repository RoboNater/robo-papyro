"""Errors rp-mcp raises, and the exit codes that come with them.

The hierarchy is two-dimensional, exactly as in the leaf packages.
:class:`RpMcpError` answers "who raised this" — every error below is one, so
``except RpMcpError`` catches everything rp-mcp raises deliberately. The
``rp_core`` base each one *also* inherits answers "what kind of failure is it",
and that is what carries the exit code (parent spec section 4.1).

Everything here is an :class:`~rp_core.errors.InputError` (exit 1), because
every failure this package originates is about the arguments a caller supplied:
a path outside the sandbox, an output that already exists, a write attempted on
a read-only server. Failures about the *documents* come from the leaves and keep
their own codes (2 for a missing binary, 3 for an unreadable file) on their way
through :func:`rp_mcp.tools.guarded`.
"""

from __future__ import annotations

from rp_core.errors import InputError, RoboPapyroError


class RpMcpError(RoboPapyroError):
    """Base for every error rp-mcp raises deliberately.

    Carries no exit code of its own — subclasses take theirs from the
    ``rp_core`` class they pair it with.
    """


class NoRootsError(RpMcpError, InputError):
    """A sandbox was built with no readable roots at all. Exit 1.

    A server with no roots can read nothing, which is a misconfiguration rather
    than a very safe server: it fails every call with a confusing per-path
    error. Refusing at construction says so once, at the point that can be
    fixed.
    """


class PathNotAllowedError(RpMcpError, InputError):
    """The path resolves outside every root the server was given. Exit 1.

    Raised before any existence check, deliberately: answering "outside the
    sandbox" for a path that is not there and "no such file" for one that is
    would turn the sandbox into an existence oracle for the rest of the disk.
    """


class OutputExistsError(RpMcpError, InputError):
    """The requested output path is already taken. Exit 1.

    The suite never overwrites an input without ``--in-place`` (parent spec
    section 10), and MCP has no ``--in-place``: a tool call names its output and
    that output must be new. Editing in place over MCP would let an agent
    destroy the only copy of a document with a single mistyped argument.
    """


class WritesNotEnabledError(RpMcpError, InputError):
    """A write tool was reached on a read-only server. Exit 1.

    Normally unreachable: the write tools are not *registered* without a write
    root, so an agent never sees them in ``tools/list``. This is the backstop
    for a caller that built a :class:`~rp_mcp.sandbox.Sandbox` itself.
    """


__all__ = [
    "NoRootsError",
    "OutputExistsError",
    "PathNotAllowedError",
    "RpMcpError",
    "WritesNotEnabledError",
]
