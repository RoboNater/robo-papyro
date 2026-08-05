"""Word-specific errors, parented onto the suite-wide hierarchy in ``rp_core``.

Each class gains its exit code from its ``rp_core`` parent (spec section 4.7):
input errors exit 1, a missing external binary exits 2, an unreadable file exits
3. Nothing here raises a bare builtin — a missing file is a
:class:`MissingFileError`, which is *also* a ``FileNotFoundError`` so library
callers keep catching what they expect.

``RpDocxError`` exists so a caller can catch everything this package raises
without also catching ``rp-pdf``'s errors; it deliberately introduces no
parallel hierarchy (spec section 4.1).
"""

from __future__ import annotations

from rp_core.errors import (
    CorruptFileError,
    InputError,
    RoboPapyroError,
)


class RpDocxError(RoboPapyroError):
    """Base class for rp-docx errors."""


class InvalidDocxError(RpDocxError, CorruptFileError):
    """The file is not a readable OOXML Word document."""


class MissingFileError(RpDocxError, InputError, FileNotFoundError):
    """The named file does not exist.

    Also a ``FileNotFoundError`` so library callers that expect the builtin keep
    catching it; ``InputError`` is what gives it exit code 1 and a ``type`` the
    error envelope can name.
    """


class TemplateError(RpDocxError, InputError):
    """A template could not be resolved, or lacks a style the StyleMap needs.

    Deliberately an input error rather than a corrupt-file one: both causes are
    the user's to fix, by naming a different template or correcting its
    stylemap.
    """


class PlaceholderError(RpDocxError, InputError):
    """A ``{{ placeholder }}`` had no value and ``strict`` was set."""


__all__ = [
    "InvalidDocxError",
    "MissingFileError",
    "PlaceholderError",
    "RpDocxError",
    "TemplateError",
]
