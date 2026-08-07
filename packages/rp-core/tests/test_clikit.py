"""Shared CLI conventions: serialization, error shapes, and exit codes."""

from __future__ import annotations

import io
import json

import pytest
import typer
from pydantic import BaseModel

from rp_core import clikit
from rp_core.errors import CorruptFileError, InputError, MissingDependencyError


class Sample(BaseModel):
    name: str
    count: int
    optional: str | None = None


class TestEmit:
    def test_json_is_the_default(self, capsys):
        clikit.emit(Sample(name="a", count=1))
        assert json.loads(capsys.readouterr().out) == {
            "name": "a",
            "count": 1,
            "optional": None,
        }

    def test_json_list(self, capsys):
        clikit.emit([Sample(name="a", count=1), Sample(name="b", count=2)])
        assert [row["name"] for row in json.loads(capsys.readouterr().out)] == ["a", "b"]

    def test_human_record(self, capsys):
        clikit.emit(Sample(name="a", count=1), plain=True)
        out = capsys.readouterr().out
        assert "name" in out and "a" in out
        assert not out.startswith("{")

    def test_human_table_has_a_header_row(self, capsys):
        clikit.emit([Sample(name="a", count=1), Sample(name="b", count=2)], plain=True)
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].split() == ["name", "count", "optional"]
        assert set(lines[1]) <= {"-", " "}
        assert len(lines) == 4

    def test_none_renders_as_dash(self, capsys):
        clikit.emit([Sample(name="a", count=1)], plain=True)
        assert "-" in capsys.readouterr().out


class TestErrorHandler:
    def test_success_is_transparent(self):
        with clikit.error_handler():
            result = 1 + 1
        assert result == 2

    def test_envelope_to_stderr(self, capsys):
        with pytest.raises(typer.Exit) as excinfo:
            with clikit.error_handler():
                raise CorruptFileError("not a PDF")
        captured = capsys.readouterr()
        assert excinfo.value.exit_code == 3
        assert captured.out == ""
        payload = json.loads(captured.err.splitlines()[-1])
        assert payload["error"]["type"] == "CorruptFileError"
        assert payload["error"]["exit_code"] == 3

    def test_envelope_is_the_only_shape(self, capsys):
        """Spec section 4.1: one serialized error shape, no argument selecting
        another. A flat {"error": message} must not be reachable."""
        with pytest.raises(typer.Exit):
            with clikit.error_handler():
                raise InputError("bad page spec")
        payload = json.loads(capsys.readouterr().err.splitlines()[-1])
        assert payload == {
            "error": {
                "type": "InputError",
                "message": "bad page spec",
                "hint": None,
                "exit_code": 1,
            }
        }

    def test_hint_travels_in_the_envelope(self, capsys):
        with pytest.raises(typer.Exit):
            with clikit.error_handler():
                raise MissingDependencyError(
                    "soffice absent", binary="soffice", install_hint="apt install libreoffice"
                )
        payload = json.loads(capsys.readouterr().err.splitlines()[-1])
        assert payload["error"]["hint"] == "apt install libreoffice"

    def test_human_message_always_on_stderr(self, capsys):
        with pytest.raises(typer.Exit):
            with clikit.error_handler():
                raise MissingDependencyError("soffice absent")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.splitlines()[0] == "soffice absent"

    def test_exit_code_comes_from_the_error(self):
        with pytest.raises(typer.Exit) as excinfo:
            with clikit.error_handler():
                raise MissingDependencyError("absent", binary="soffice")
        assert excinfo.value.exit_code == 2

    def test_also_catches_foreign_exceptions_as_exit_1(self, capsys):
        with pytest.raises(typer.Exit) as excinfo:
            with clikit.error_handler(also=(FileNotFoundError,)):
                raise FileNotFoundError("No such file: x.pdf")
        assert excinfo.value.exit_code == 1
        payload = json.loads(capsys.readouterr().err.splitlines()[-1])
        assert payload["error"] == {
            "type": "FileNotFoundError",
            "message": "No such file: x.pdf",
            "hint": None,
            "exit_code": 1,
        }

    def test_unlisted_exceptions_propagate(self):
        """An unexpected error is a bug, not a user error — it must not be
        swallowed into a tidy exit code."""
        with pytest.raises(ZeroDivisionError):
            with clikit.error_handler():
                raise ZeroDivisionError("division by zero")

    def test_decorator_form(self, capsys):
        @clikit.handle_errors()
        def command():
            raise InputError("nope")

        with pytest.raises(typer.Exit) as excinfo:
            command()
        assert excinfo.value.exit_code == 1
        payload = json.loads(capsys.readouterr().err.splitlines()[-1])
        assert payload["error"]["message"] == "nope"

    def test_decorator_preserves_metadata(self):
        @clikit.handle_errors()
        def command():
            """Docstring typer reads for --help."""

        assert command.__name__ == "command"
        assert command.__doc__ == "Docstring typer reads for --help."


class TestDoctorCommand:
    def test_json_output_is_the_default(self, capsys):
        clikit.doctor_command("python3")(False)
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["name"] == "python3"
        assert payload[0]["available"] is True

    def test_human_table_omits_the_hint_column(self, capsys):
        clikit.doctor_command("python3")(True)
        assert "install_hint" not in capsys.readouterr().out

    def test_missing_binary_hint_goes_to_stderr(self, capsys, monkeypatch):
        from rp_core import doctor

        monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: None)
        clikit.doctor_command("soffice")(True)
        captured = capsys.readouterr()
        assert "soffice" in captured.out
        assert "LibreOffice" in captured.err


class TestParseBool:
    @pytest.mark.parametrize("text", ["1", "true", "TRUE", " yes ", "on"])
    def test_truthy_spellings(self, text):
        assert clikit.parse_bool(text) is True

    @pytest.mark.parametrize("text", ["0", "false", "No", "off"])
    def test_falsy_spellings(self, text):
        assert clikit.parse_bool(text) is False

    @pytest.mark.parametrize("text", [None, "", "  ", "maybe", "2"])
    def test_anything_else_is_unset_not_false(self, text):
        """Unrecognized text falls through to the next source. Resolving it to
        False would let a typo silently switch something off."""
        assert clikit.parse_bool(text) is None


class TestDisplayEnabled:
    """--describe/--progress: flag -> env -> config -> "is stderr a terminal"."""

    def test_the_flag_wins_over_everything(self):
        assert clikit.display_enabled(False, env_value="1", config_value=True) is False
        assert clikit.display_enabled(True, env_value="0", config_value=False) is True

    def test_env_beats_config(self):
        assert clikit.display_enabled(None, env_value="off", config_value=True) is False

    def test_unparseable_env_falls_through_to_config(self):
        assert clikit.display_enabled(None, env_value="perhaps", config_value=True) is True

    def test_config_is_used_when_nothing_else_is_set(self):
        assert clikit.display_enabled(None, config_value=False, stream=io.StringIO()) is False

    def test_a_non_boolean_config_value_is_ignored(self):
        """TOML can hold anything; a string here must not read as truthy."""
        assert clikit.display_enabled(None, config_value="yes", stream=io.StringIO()) is False

    def test_default_is_off_for_a_pipe_and_on_for_a_terminal(self):
        """The property agents depend on: nothing new appears on stderr unless a
        human is watching it."""

        class Tty(io.StringIO):
            def isatty(self):
                return True

        assert clikit.display_enabled(None, stream=io.StringIO()) is False
        assert clikit.display_enabled(None, stream=Tty()) is True


class TestJobDescription:
    entries = [("pages", "all"), ("AI review", "off (--ai to enable)")]

    def test_rows_are_aligned_under_the_title(self):
        lines = clikit.job_lines("rp-pdf markdown — a.pdf", self.entries)
        assert lines[0] == "rp-pdf markdown — a.pdf"
        assert lines[1:] == [
            "  pages      all",
            "  AI review  off (--ai to enable)",
        ]

    def test_a_title_with_no_entries_is_just_the_title(self):
        assert clikit.job_lines("rp-pdf doctor", []) == ["rp-pdf doctor"]

    def test_announce_writes_to_stderr_only(self, capsys):
        """stdout carries results; a description on it would corrupt the JSON."""
        clikit.announce_job("rp-pdf markdown — a.pdf", self.entries)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "AI review" in captured.err


class TestJob:
    def test_describe_off_and_progress_off_writes_nothing(self, capsys):
        with clikit.job("rp-pdf markdown", [("pages", "all")]) as reporter:
            with reporter.step("Working", total=1) as step:
                step.advance()
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", "")

    def test_describe_prints_and_yields_a_silent_reporter(self, capsys):
        with clikit.job("rp-pdf markdown", [("pages", "all")], describe=True) as reporter:
            assert reporter.enabled is False
            with reporter.step("Working"):
                pass
        err = capsys.readouterr().err
        assert err.splitlines() == ["rp-pdf markdown", "  pages  all"]

    def test_progress_yields_a_real_reporter(self):
        stream = io.StringIO()
        with clikit.job("t", progress=True, stream=stream) as reporter:
            assert reporter.enabled is True
            with reporter.step("Working", total=1) as step:
                step.advance()
        assert "Working" in stream.getvalue()

    def test_the_reporter_is_closed_even_when_the_job_raises(self):
        """`job` wraps the work, so its finally is what guarantees no
        half-painted line sits in front of the error message."""
        stream = io.StringIO()
        captured = {}
        with pytest.raises(RuntimeError):
            with clikit.job("t", progress=True, stream=stream) as reporter:
                captured["reporter"] = reporter
                raise RuntimeError("boom")
        assert captured["reporter"]._thread is None
