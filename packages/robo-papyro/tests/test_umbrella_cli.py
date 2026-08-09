"""The `rp` dispatcher: entry-point discovery and graceful degradation.

The discovery tests fake the entry-point group rather than relying on what
happens to be installed, so they still describe the intended behavior once a
second leaf package exists.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess

import pytest
import typer

from robo_papyro import cli


class TestPackagingContract:
    """What a *published* install gets, which `uv sync` cannot tell you.

    Raised in review: `rp mcp` worked in CI while `pip install robo-papyro`
    would not have had it, because a uv workspace sync installs every member
    regardless of what any member declares. Nothing in the suite looked at the
    declared metadata, so the docs and the packaging could drift apart silently.
    These read the manifest itself.
    """

    @staticmethod
    def _manifest() -> dict:
        import tomllib

        path = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        with open(path, "rb") as handle:
            return tomllib.load(handle)

    @staticmethod
    def _names(requirements: list[str]) -> set[str]:
        """Distribution names, dropping any version specifier."""
        return {re.split(r"[<>=!~\[ ]", item, maxsplit=1)[0] for item in requirements}

    def test_runtime_dependencies_are_the_leaves_and_rp_mcp(self):
        """The documented contract: the umbrella installs the whole suite."""
        assert self._names(self._manifest()["project"]["dependencies"]) == {
            "rp-core",
            "rp-docx",
            "rp-mcp",
            "rp-pdf",
            "rp-pptx",
            "rp-xlsx",
            "typer",
        }

    def test_rp_mcp_is_a_runtime_dependency_and_not_an_extra(self):
        """`pip install robo-papyro` must get `rp mcp`.

        This is the reverse of what Phase 2 shipped. The extra kept starlette
        and uvicorn away from CLI-only users, at the price of an agent
        integration nobody discovers; the suite exists for agentic document
        work, so the servers are baseline and the dependency tree is the
        accepted cost.

        Asserting the *absence* of the extra matters as much as the presence of
        the dependency: re-adding `[project.optional-dependencies] mcp` would
        make `pip install robo-papyro[mcp]` meaningful again and leave the docs
        describing two install paths where there is one.
        """
        manifest = self._manifest()
        assert "rp-mcp" in self._names(manifest["project"]["dependencies"])
        assert "mcp" not in manifest["project"].get("optional-dependencies", {})

    def test_every_workspace_dependency_is_sourced(self):
        """A `rp-*` requirement with no `[tool.uv.sources]` entry resolves from
        an index that has never published it, which fails only at install time."""
        manifest = self._manifest()
        required = self._names(manifest["project"]["dependencies"])
        for extra in manifest["project"].get("optional-dependencies", {}).values():
            required |= self._names(extra)
        sources = set(manifest["tool"]["uv"]["sources"])
        assert {name for name in required if name.startswith("rp-")} <= sources


class FakeEntryPoint:
    def __init__(self, name, value=None, error=None):
        self.name = name
        self._value = value
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._value


def _fake_group(monkeypatch, *entries):
    monkeypatch.setattr(cli, "entry_points", lambda group: list(entries))


class TestDiscover:
    def test_loads_registered_apps(self, monkeypatch):
        _fake_group(monkeypatch, FakeEntryPoint("pdf", typer.Typer()))
        loaded, failed = cli.discover()
        assert [name for name, _ in loaded] == ["pdf"]
        assert failed == []

    def test_sorted_by_name(self, monkeypatch):
        _fake_group(
            monkeypatch,
            FakeEntryPoint("xlsx", typer.Typer()),
            FakeEntryPoint("docx", typer.Typer()),
            FakeEntryPoint("pdf", typer.Typer()),
        )
        loaded, _ = cli.discover()
        assert [name for name, _ in loaded] == ["docx", "pdf", "xlsx"]

    def test_broken_leaf_is_reported_not_raised(self, monkeypatch):
        """A broken leaf package degrades to a warning, not a dead CLI."""
        _fake_group(
            monkeypatch,
            FakeEntryPoint("pdf", typer.Typer()),
            FakeEntryPoint("docx", error=ImportError("no python-docx")),
        )
        loaded, failed = cli.discover()
        assert [name for name, _ in loaded] == ["pdf"]
        assert failed[0][0] == "docx"
        assert "python-docx" in str(failed[0][1])

    def test_non_typer_entry_point_is_rejected(self, monkeypatch):
        _fake_group(monkeypatch, FakeEntryPoint("bogus", value="not an app"))
        loaded, failed = cli.discover()
        assert loaded == []
        assert isinstance(failed[0][1], TypeError)

    def test_nothing_installed_is_not_an_error(self, monkeypatch):
        _fake_group(monkeypatch)
        assert cli.discover() == ([], [])


class TestBuild:
    def test_registers_subcommands(self, monkeypatch):
        _fake_group(monkeypatch, FakeEntryPoint("pdf", typer.Typer()))
        target = typer.Typer()
        installed, failed = cli.build(target)
        assert installed == ["pdf"]
        assert failed == []
        assert [group.name for group in target.registered_groups] == ["pdf"]

    def test_warns_when_nothing_is_installed(self, monkeypatch, capsys):
        cli.warn([], [])
        assert "no robo-papyro subcommands are installed" in capsys.readouterr().err

    def test_warns_per_broken_leaf(self, capsys):
        cli.warn(["pdf"], [("docx", ImportError("boom"))])
        err = capsys.readouterr().err
        assert "could not load the 'docx' subcommand" in err
        assert "boom" in err


class TestNoLeafImports:
    def test_module_does_not_import_leaf_packages(self):
        """Discovery, not imports (spec section 6). If this module ever imports
        a leaf directly, `rp` stops degrading gracefully."""
        tree = ast.parse(pathlib.Path(cli.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "rp_pdf" not in imported
        assert "rp_docx" not in imported
        # rp_core is fine — it is the shared base, not a leaf.
        assert imported <= {"__future__", "sys", "importlib", "typer", "rp_core"}


# --- end-to-end, against the installed console scripts ---


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path_factory.mktemp("umbrella") / "sample.pdf"
    c = reportlab.Canvas(str(path))
    c.setTitle("Sample")
    for i in range(3):
        c.drawString(72, 720, f"Page {i + 1}")
        c.showPage()
    c.save()
    return path


def test_help_lists_installed_subcommands():
    result = _run("rp", "--help")
    assert result.returncode == 0
    assert "pdf" in result.stdout
    assert "doctor" in result.stdout


def test_rp_pdf_and_rp_are_the_same_code_path(sample_pdf):
    through_umbrella = _run("rp", "pdf", "index", sample_pdf)
    direct = _run("rp-pdf", "index", sample_pdf)
    assert through_umbrella.returncode == direct.returncode == 0
    assert json.loads(through_umbrella.stdout) == json.loads(direct.stdout)


def test_exit_codes_survive_the_umbrella(tmp_path):
    """The leaf's exit code must not be flattened on its way through `rp`."""
    not_a_pdf = tmp_path / "fake.pdf"
    not_a_pdf.write_text("not a pdf", encoding="utf-8")
    assert _run("rp", "pdf", "index", not_a_pdf).returncode == 3
    assert _run("rp", "pdf", "text", tmp_path / "missing.pdf").returncode == 1


def test_doctor_reports_across_the_suite():
    result = _run("rp", "doctor")
    assert result.returncode == 0
    names = [row["name"] for row in json.loads(result.stdout)]
    assert names == list(cli.CAPABILITIES)


def test_doctor_covers_more_than_any_single_leaf():
    """`rp doctor` aggregates: it reports on soffice, which no rp-pdf path uses."""
    assert "soffice" in cli.CAPABILITIES
    assert "soffice" not in _run("rp-pdf", "doctor").stdout
