"""PDF-specific errors, parented onto the suite-wide hierarchy in ``rp_core``.

Each class keeps the name and meaning it had as a ``pdfx`` error and gains an
exit code from its ``rp_core`` parent (spec section 4.7): input errors exit 1,
a missing external binary exits 2, an unreadable file exits 3.

These are re-exported from :mod:`rp_pdf.core`, which is where they were defined
historically and where callers still import them from.
"""

from __future__ import annotations

from rp_core.errors import (
    CorruptFileError,
    InputError,
    MissingDependencyError,
    RoboPapyroError,
)


class RpPdfError(RoboPapyroError):
    """Base class for rp-pdf errors."""


class InvalidPdfError(RpPdfError, CorruptFileError):
    """The file is not a readable PDF."""


class MissingFileError(RpPdfError, InputError, FileNotFoundError):
    """The named file does not exist.

    Also a ``FileNotFoundError`` so library callers that predate the suite-wide
    hierarchy keep catching it; ``InputError`` is what gives it exit code 1 and
    a ``type`` the error envelope can name.
    """


class PasswordError(RpPdfError, InputError):
    """The PDF is encrypted and the password is missing or wrong."""


class PopplerNotFoundError(RpPdfError, MissingDependencyError):
    """poppler binaries are required (text extraction or rendering) but were not found."""

    def __init__(self, message: str, *, binary: str = "poppler", install_hint: str = "") -> None:
        super().__init__(message, binary=binary, install_hint=install_hint)


class QueryError(RpPdfError, InputError):
    """A search query is empty or not a valid regular expression."""


__all__ = [
    "InvalidPdfError",
    "MissingFileError",
    "PasswordError",
    "PopplerNotFoundError",
    "QueryError",
    "RpPdfError",
]
