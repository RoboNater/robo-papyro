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

:class:`~rp_core.models.ErrorEnvelope` is the *only* serialized error shape in
the suite (spec section 4.1). There is no second form and no flag selecting one:
an agent parsing an ``rp-*`` failure sees the same keys whichever tool failed.
"""

from __future__ import annotations

from rp_core.models import ErrorDetail, ErrorEnvelope


class RoboPapyroError(Exception):
    """Base class for every error the suite raises deliberately."""

    exit_code: int = 1

    #: Actionable next step for the user, when there is one.
    hint: str | None = None

    def to_envelope(self) -> ErrorEnvelope:
        """Structured form of this error, as the CLIs serialize it."""
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


class SubprocessTimeout(RoboPapyroError):
    """An external tool ran past its timeout and was killed.

    Distinct from :class:`ConversionError` because the remedy is different: a
    conversion failure is about the file, a timeout is about the clock, and
    ``RP_SUBPROCESS_TIMEOUT`` is the knob. ``subprocess.TimeoutExpired`` must
    never reach the user in its place.
    """

    exit_code = 3


def envelope_for(exc: BaseException) -> ErrorEnvelope:
    """The envelope for any exception a CLI is willing to report.

    Suite errors describe themselves. A foreign exception a CLI has opted into
    catching (see ``clikit.error_handler``'s ``also``) still leaves through the
    one envelope shape, defaulting to exit code 1 — the caller gets the same
    keys either way.
    """
    if isinstance(exc, RoboPapyroError):
        return exc.to_envelope()
    return ErrorEnvelope(
        error=ErrorDetail(
            type=type(exc).__name__,
            message=str(exc),
            hint=getattr(exc, "hint", None),
            exit_code=getattr(exc, "exit_code", 1),
        )
    )
