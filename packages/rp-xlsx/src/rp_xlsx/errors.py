"""Errors this package raises, and the exit codes that come with them.

Two-dimensional on purpose, matching every sibling leaf: :class:`RpXlsxError`
answers "who raised this" — every error below is one, so ``except
RpXlsxError`` catches everything rp-xlsx raises deliberately. The ``rp_core``
base each one *also* inherits answers "what kind of failure is it", and that
is what carries the exit code (parent spec section 4.1):
:class:`~rp_core.errors.InputError` is 1, :class:`~rp_core.errors.CorruptFileError`
is 3.
"""

from __future__ import annotations

from rp_core.errors import CorruptFileError, InputError, RoboPapyroError


class RpXlsxError(RoboPapyroError):
    """Base for every error rp-xlsx raises deliberately.

    Carries no exit code of its own — subclasses take theirs from the
    ``rp_core`` class they pair it with.
    """


class MissingFileError(RpXlsxError, InputError, FileNotFoundError):
    """The workbook, template, or interchange file is not there. Exit 1.

    Also a ``FileNotFoundError``, matching the other leaves: library callers
    that expect the builtin keep catching it, while ``InputError`` is what
    supplies the exit code and the ``type`` the error envelope names.
    """


class InvalidXlsxError(RpXlsxError, CorruptFileError):
    """Not a spreadsheet package, or one openpyxl cannot open. Exit 3.

    Covers a corrupt zip (``BadZipFile``), a well-formed zip that is not an
    OOXML spreadsheet package, and openpyxl's own ``InvalidFileException`` —
    including the extension-only refusal for legacy ``.xls``/``.xlsb`` (spec
    section 9). Nothing raises a bare builtin.
    """


class LossyEditError(RpXlsxError, CorruptFileError):
    """A write would silently drop a part openpyxl does not model. Exit 3.

    The centre of this package (spec section 6). Every write path against an
    existing workbook scans it with ``fidelity.scan`` before opening it; a
    write that would drop cached formula values or an unmodelled part (a
    threaded comment, a pivot cache, a slicer, a form control, custom XML)
    raises this instead of silently deleting what it cannot represent.
    ``--allow-lossy``/``allow_lossy=True`` proceeds and reports what was
    dropped in the result instead of raising — the flag never makes the loss
    silent.
    """


__all__ = [
    "InvalidXlsxError",
    "LossyEditError",
    "MissingFileError",
    "RpXlsxError",
]
