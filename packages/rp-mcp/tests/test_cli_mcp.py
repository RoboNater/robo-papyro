"""The launchers: what they build, what they print, and what they refuse to offer.

`serve` blocks forever by design, so these tests replace `MCPServer.run` and
inspect the server that was handed to it. That is the thing worth checking —
a launcher's whole job is turning flags into a correctly-configured server.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
import typer
from mcp.server.mcpserver import MCPServer
from typer.testing import CliRunner

from rp_core.errors import CorruptFileError
from rp_mcp import cli
from rp_mcp.sandbox import ROOTS_ENV, WRITE_ROOT_ENV

runner = CliRunner()


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Records each `MCPServer.run` instead of blocking on it."""
    calls: list[dict] = []

    def fake_run(self, transport="stdio", **kwargs):
        calls.append({"server": self, "transport": transport, "kwargs": kwargs})

    monkeypatch.setattr(MCPServer, "run", fake_run)
    return calls


def _names(server: MCPServer) -> set[str]:
    return {tool.name for tool in anyio.run(server.list_tools)}


class TestToolsCommand:
    def test_json_is_the_default_output(self, docs: Path):
        result = runner.invoke(cli.app, ["tools", "--server", "pdf", "--root", str(docs)])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["name"] == "robo-papyro-pdf"
        assert payload["sandbox"]["roots"] == [str(docs.resolve())]
        assert "pdf_index" in {tool["name"] for tool in payload["tools"]}

    def test_the_listing_reflects_the_sandbox_it_was_given(self, docs: Path, outbox: Path):
        """A read-only server genuinely has fewer tools, and this is how you see it."""
        read = json.loads(
            runner.invoke(cli.app, ["tools", "--server", "docx", "--root", str(docs)]).stdout
        )
        write = json.loads(
            runner.invoke(
                cli.app,
                ["tools", "--server", "docx", "--root", str(docs), "--write-root", str(outbox)],
            ).stdout
        )
        read_names = {tool["name"] for tool in read["tools"]}
        write_names = {tool["name"] for tool in write["tools"]}
        assert "docx_create" not in read_names
        assert "docx_create" in write_names
        assert read_names < write_names

    def test_all_is_the_default_server(self, docs: Path):
        payload = json.loads(runner.invoke(cli.app, ["tools", "--root", str(docs)]).stdout)
        assert payload["name"] == "robo-papyro"
        prefixes = {tool["name"].split("_")[0] for tool in payload["tools"]}
        assert {"pdf", "docx", "pptx"} <= prefixes

    def test_plain_is_the_human_opt_out(self, docs: Path):
        result = runner.invoke(
            cli.app, ["tools", "--server", "pdf", "--root", str(docs), "--plain"]
        )
        assert result.exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)
        assert "robo-papyro-pdf" in result.stdout

    def test_the_roots_environment_variable_is_honoured(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ROOTS_ENV, str(docs))
        payload = json.loads(runner.invoke(cli.app, ["tools", "--server", "pdf"]).stdout)
        assert payload["sandbox"]["roots"] == [str(docs.resolve())]

    def test_the_write_root_environment_variable_is_honoured(
        self, docs: Path, outbox: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ROOTS_ENV, str(docs))
        monkeypatch.setenv(WRITE_ROOT_ENV, str(outbox))
        payload = json.loads(runner.invoke(cli.app, ["tools", "--server", "docx"]).stdout)
        assert payload["sandbox"]["writable"] is True


class TestServe:
    def test_serve_uses_stdio(self, docs: Path, served: list[dict]):
        result = runner.invoke(cli.app, ["serve", "--server", "pdf", "--root", str(docs)])
        assert result.exit_code == 0
        assert served[0]["transport"] == "stdio"

    def test_serve_builds_the_requested_suite_only(self, docs: Path, served: list[dict]):
        runner.invoke(cli.app, ["serve", "--server", "docx", "--root", str(docs)])
        names = _names(served[0]["server"])
        assert "docx_index" in names
        assert not [name for name in names if name.startswith("pdf_")]

    def test_serve_without_a_write_root_registers_no_write_tools(
        self, docs: Path, served: list[dict]
    ):
        runner.invoke(cli.app, ["serve", "--server", "docx", "--root", str(docs)])
        assert "docx_create" not in _names(served[0]["server"])

    def test_repeated_root_flags_all_apply(self, docs: Path, outbox: Path):
        """`--root` is repeatable, and order is preserved — the first is what a
        relative path in a tool call resolves against."""
        result = runner.invoke(
            cli.app,
            ["tools", "--server", "pdf", "--root", str(docs), "--root", str(outbox)],
        )
        assert json.loads(result.stdout)["sandbox"]["roots"] == [
            str(docs.resolve()),
            str(outbox.resolve()),
        ]


class TestSingleSuiteLaunchers:
    @pytest.mark.parametrize(
        ("app", "prefix"),
        [(cli.pdf_app, "pdf_"), (cli.docx_app, "docx_"), (cli.pptx_app, "pptx_")],
    )
    def test_a_bare_invocation_serves(self, app, prefix, docs: Path, served: list[dict]):
        """An MCP client config names a command; making it name a subcommand too
        buys nothing, so these serve with no subcommand at all."""
        result = runner.invoke(app, ["--root", str(docs)])
        assert result.exit_code == 0, result.output
        names = _names(served[0]["server"])
        assert any(name.startswith(prefix) for name in names)
        assert {name.split("_")[0] for name in names} == {prefix.rstrip("_"), "rp"}

    def test_the_write_root_flag_reaches_a_single_suite_launcher(
        self, docs: Path, outbox: Path, served: list[dict]
    ):
        runner.invoke(cli.docx_app, ["--root", str(docs), "--write-root", str(outbox)])
        assert "docx_create" in _names(served[0]["server"])


class TestConventions:
    def _params(self, app: typer.Typer, name: str) -> set[str]:
        """Read the parsed command, never the rendered help.

        rich colorizes under CI and splits an option's leading hyphen into its
        own span, so an absence assertion against `--help` text passes for the
        wrong reason on the only run that gates a merge (AGENTS.md).
        """
        command = typer.main.get_command(app).commands[name]
        return {opt for param in command.params for opt in (*param.opts, *param.secondary_opts)}

    def test_there_is_no_json_flag(self):
        """The suite-wide invariant: JSON is the default, `--plain` opts out."""
        for name in ("tools", "serve", "doctor"):
            assert "--json" not in self._params(cli.app, name)

    def test_tools_has_the_plain_flag(self):
        assert "--plain" in self._params(cli.app, "tools")

    def test_no_transport_option_is_offered(self):
        """stdio only, deliberately — binding a port needs an auth story a path
        allowlist does not provide (see the module docstring)."""
        assert "--transport" not in self._params(cli.app, "serve")

    def test_doctor_is_registered(self, docs: Path):
        result = runner.invoke(cli.app, ["doctor"])
        assert result.exit_code == 0
        assert isinstance(json.loads(result.stdout), list)

    def test_a_suite_error_is_an_envelope_on_stderr_with_its_exit_code(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """`handle_errors` is wired, so a failure looks like every other rp-* failure."""

        def boom(*args, **kwargs):
            raise CorruptFileError("something unreadable")

        monkeypatch.setattr(cli, "build_server", boom)
        result = runner.invoke(cli.app, ["tools", "--root", str(docs)])
        assert result.exit_code == 3
        assert json.loads(result.stderr.splitlines()[-1])["error"]["exit_code"] == 3
