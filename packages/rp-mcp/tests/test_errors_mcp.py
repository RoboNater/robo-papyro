"""The error bridge: suite errors in, tool errors out, envelope intact.

`rp_mcp.tools`' docstring promises three things — the envelope survives, the
exit code survives, and the wrapper does not hide the wrapped signature. Each
one is a claim, so each one is asserted here rather than described.
"""

from __future__ import annotations

import inspect
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from rp_core.errors import CorruptFileError, InputError, MissingDependencyError
from rp_mcp import errors as mcp_errors
from rp_mcp.tools import error_text, guarded


class TestErrorText:
    def test_the_envelope_is_the_last_line(self):
        text = error_text(InputError("bad page spec"))
        assert text.splitlines()[-1].startswith("{")
        assert json.loads(text.splitlines()[-1])["error"]["message"] == "bad page spec"

    def test_a_multi_line_message_still_leaves_the_envelope_last(self):
        """The reason for the ordering: a long message must not bury the envelope."""
        text = error_text(InputError("line one\nline two\nline three"))
        assert json.loads(text.splitlines()[-1])["error"]["type"] == "InputError"

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (InputError("x"), 1),
            (MissingDependencyError("x", binary="pdftotext"), 2),
            (CorruptFileError("x"), 3),
        ],
    )
    def test_the_exit_code_is_carried_through_unchanged(self, exc, code):
        assert json.loads(error_text(exc).splitlines()[-1])["error"]["exit_code"] == code

    def test_a_hint_survives(self):
        envelope = json.loads(
            error_text(
                MissingDependencyError("no poppler", install_hint="apt install poppler-utils")
            ).splitlines()[-1]
        )
        assert envelope["error"]["hint"] == "apt install poppler-utils"


class TestGuarded:
    def test_a_suite_error_becomes_a_tool_error(self):
        @guarded
        def failing():
            raise InputError("nope")

        with pytest.raises(ToolError) as caught:
            failing()
        assert json.loads(str(caught.value).splitlines()[-1])["error"]["type"] == "InputError"

    def test_a_non_suite_error_is_left_alone(self):
        """A bug should arrive as a traceback, not as a tidy expected-looking message."""

        @guarded
        def failing():
            raise ZeroDivisionError("a bug in this package")

        with pytest.raises(ZeroDivisionError):
            failing()

    def test_a_successful_call_is_untouched(self):
        @guarded
        def fine(value: int) -> int:
            return value * 2

        assert fine(21) == 42

    def test_the_signature_survives_the_wrapper(self):
        """What makes `@server.tool()` over `@guarded` generate the right schema."""

        @guarded
        def tool(path: str, pages: str = "all", physical: bool = False) -> str:
            """Docstring that becomes the tool description."""
            return path

        assert list(inspect.signature(tool).parameters) == ["path", "pages", "physical"]
        assert inspect.signature(tool).parameters["pages"].default == "all"
        assert tool.__doc__.startswith("Docstring that becomes")


class TestHierarchy:
    @pytest.mark.parametrize(
        "cls",
        [
            mcp_errors.NoRootsError,
            mcp_errors.OutputExistsError,
            mcp_errors.PathNotAllowedError,
            mcp_errors.WritesNotEnabledError,
        ],
    )
    def test_every_error_is_an_input_error_worth_exit_1(self, cls):
        """The module docstring's claim: everything this package originates is exit 1."""
        assert issubclass(cls, mcp_errors.RpMcpError)
        assert issubclass(cls, InputError)
        assert cls("x").to_envelope().error.exit_code == 1

    def test_the_package_base_carries_no_exit_code_of_its_own(self):
        """Pairing, not inheritance, supplies the code — same rule as the leaves."""
        assert not issubclass(mcp_errors.RpMcpError, InputError)
