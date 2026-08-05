"""The error hierarchy and its exit-code mapping (spec section 4.7)."""

from __future__ import annotations

import pytest

from rp_core.errors import (
    ConversionError,
    CorruptFileError,
    InputError,
    MissingDependencyError,
    RoboPapyroError,
    SubprocessTimeout,
    envelope_for,
)
from rp_core.ranges import RangeSpecError


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RoboPapyroError("x"), 1),
        (InputError("x"), 1),
        (MissingDependencyError("x"), 2),
        (CorruptFileError("x"), 3),
        (ConversionError("x"), 3),
        (SubprocessTimeout("x"), 3),
    ],
)
def test_exit_codes(error, expected):
    assert error.exit_code == expected


def test_range_spec_error_is_an_input_error():
    """Exit code 1, while staying a ValueError for callers that predate the
    suite-wide hierarchy."""
    error = RangeSpecError("bad spec")
    assert isinstance(error, InputError)
    assert isinstance(error, ValueError)
    assert error.exit_code == 1


def test_envelope_shape():
    envelope = CorruptFileError("not a PDF").to_envelope()
    assert envelope.error.type == "CorruptFileError"
    assert envelope.error.message == "not a PDF"
    assert envelope.error.exit_code == 3
    assert envelope.error.hint is None


def test_envelope_carries_install_hint():
    error = MissingDependencyError("absent", binary="soffice", install_hint="apt install ...")
    assert error.to_envelope().error.hint == "apt install ..."


def test_envelope_is_json_serializable():
    payload = (
        MissingDependencyError("absent", binary="soffice").to_envelope().model_dump(mode="json")
    )
    assert payload["error"]["exit_code"] == 2


class TestEnvelopeFor:
    def test_suite_errors_describe_themselves(self):
        error = CorruptFileError("not a PDF")
        assert envelope_for(error) == error.to_envelope()

    def test_foreign_exceptions_get_the_same_shape(self):
        envelope = envelope_for(FileNotFoundError("No such file: x.pdf"))
        assert envelope.error.type == "FileNotFoundError"
        assert envelope.error.message == "No such file: x.pdf"
        assert envelope.error.exit_code == 1
        assert envelope.error.hint is None
