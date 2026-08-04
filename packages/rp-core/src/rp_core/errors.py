"""Exception hierarchy shared by every robo-papyro package, and the exit codes
the CLIs report for each.

Exit codes (spec section 4.7, all CLIs):

===  ==========================================
  0  success
  1  user or input error
  2  missing external dependency
  3  corrupt or unsupported file
===  ==========================================

Every error carries :meth:`~RoboPapyroError.to_envelope`, so a CLI can serialize
it the same way regardless of which package raised it. A raw ``FileNotFoundError``
from a subprocess must never reach the user — wrap it.
"""

from __future__ import annotations

from rp_core.models import ErrorDetail, ErrorEnvelope


class RoboPapyroError(Exception):
    """Base class for every error the suite raises deliberately."""

    exit_code: int = 1

    #: Actionable next step for the user, when there is one.
    hint: str | None = None

    def to_envelope(self) -> ErrorEnvelope:
        """Structured form of this error, for ``--json`` output."""
        return ErrorEnvelope(
            error=ErrorDetail(
                type=type(self).__name__,
                message=str(self),
                hint=self.hint,
                exit_code=self.exit_code,
            )
        )


class InputError(RoboPapyroError):
    """Bad arguments, bad page spec, unresolvable name — the user's to fix."""

    exit_code = 1


class MissingDependencyError(RoboPapyroError):
    """An external binary (soffice, pdftoppm, ...) is required but absent."""

    exit_code = 2

    def __init__(self, message: str, *, binary: str = "", install_hint: str = "") -> None:
        super().__init__(message)
        self.binary = binary
        self.install_hint = install_hint
        self.hint = install_hint or None


class CorruptFileError(RoboPapyroError):
    """The file is unreadable, malformed, or not the format it claims to be."""

    exit_code = 3


class ConversionError(RoboPapyroError):
    """An external conversion tool failed, or produced no output file."""

    exit_code = 3
