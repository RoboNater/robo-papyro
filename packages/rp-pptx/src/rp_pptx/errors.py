"""Errors this package raises, and the exit codes that come with them.

The hierarchy is two-dimensional on purpose. :class:`RpPptxError` answers "who
raised this" — every error below is one, so ``except RpPptxError`` catches
everything rp-pptx raises deliberately. The ``rp_core`` base each one *also*
inherits answers "what kind of failure is it", and that is what carries the exit
code (parent spec section 4.1): :class:`~rp_core.errors.InputError` is 1,
:class:`~rp_core.errors.CorruptFileError` is 3.

Getting that pairing wrong is subtle and expensive: a package base that is itself
an ``InputError`` quietly asserts "exit 1" about every error under it, and one
that sits outside the ``rp_core`` tree loses ``to_envelope`` altogether.
"""

from __future__ import annotations

from rp_core.errors import CorruptFileError, InputError, RoboPapyroError


class RpPptxError(RoboPapyroError):
    """Base for every error rp-pptx raises deliberately.

    Carries no exit code of its own — subclasses take theirs from the
    ``rp_core`` class they pair it with.
    """


class MissingFileError(RpPptxError, InputError, FileNotFoundError):
    """The deck, template, or markdown file is not there. Exit 1.

    Also a ``FileNotFoundError``, matching rp-docx: library callers that expect
    the builtin keep catching it, while ``InputError`` is what supplies the exit
    code and the ``type`` the error envelope names.
    """


class InvalidPptxError(RpPptxError, CorruptFileError):
    """Not a PowerPoint package, or one python-pptx cannot open. Exit 3."""


class UnsupportedFeatureError(RpPptxError, CorruptFileError):
    """A readable file using a feature this package cannot yet report on. Exit 3.

    Today this means exactly one thing: modern threaded comments, deferred by
    spec section 7 until a real PowerPoint-authored reference deck can be
    inspected. The taxonomy already reads 3 as "unreadable or unsupported", and
    an error is the only channel the contract has — library functions return
    models and never print, so a warning is precisely what an agent would miss.

    **This class is temporary.** It exists only while the deferral is active, and
    deleting it is part of the follow-up that lands modern-comment support, so a
    stopgap cannot calcify into API surface.
    """


__all__ = [
    "InvalidPptxError",
    "MissingFileError",
    "RpPptxError",
    "UnsupportedFeatureError",
]
