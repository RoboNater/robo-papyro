"""Invariants this package would otherwise only assert in prose.

The important one is :class:`TestEveryPathGoesThroughTheSandbox`. It walks the
*registered* tool list rather than a hand-written one, so a tool added later
that forgets ``sandbox.resolve_input`` fails here without anyone remembering to
add a test — which is the only kind of allowlist check worth having.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any

import pytest

import rp_docx
import rp_mcp
import rp_pptx
import rp_xlsx
from rp_docx.errors import TemplateError
from rp_mcp.sandbox import Sandbox
from rp_mcp.server import ALL_SUITES, build_server
from rp_mcp.tools import _looks_like_a_path

#: Parameters whose value is a path the server must confine. Named rather than
#: sniffed, because a tool that takes a path under some other name is exactly
#: the case a reviewer should have to think about.
PATH_PARAMS = {"path", "output", "output_dir", "template_name"}

#: Placeholder values by JSON-schema type, for filling in a tool's other
#: required arguments so the call reaches the tool body.
FILLERS: dict[str, Any] = {
    "string": "placeholder",
    "integer": 1,
    "number": 1,
    "boolean": False,
    "object": {},
    "array": [],
}


def _filler(schema: dict) -> Any:
    """A value that will pass this parameter's schema, whatever it is.

    A value that *fails* validation would never reach the tool body, so the
    sandbox check under test would not run and the tool would look safe.
    """
    if "enum" in schema:
        return schema["enum"][0]
    if "$ref" in schema or "allOf" in schema:  # a nested model, all fields optional
        return {}
    if "anyOf" in schema:
        return _filler(schema["anyOf"][0])
    return FILLERS.get(schema.get("type", ""), "placeholder")


@pytest.fixture
def server(docs, outbox):
    """A fully writable server, so every tool in the suite is registered."""
    return build_server(Sandbox([docs], write_root=outbox), ALL_SUITES)


def _path_arguments(schema: dict) -> list[str]:
    return [name for name in schema.get("properties", {}) if name in PATH_PARAMS]


def _tool_cases(server, driver) -> list[tuple[str, str, dict]]:
    cases = []
    for tool in driver.listed(server):
        schema = tool.input_schema
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        for target in _path_arguments(schema):
            arguments = {
                name: _filler(spec) for name, spec in properties.items() if name in required
            }
            arguments[target] = "/nowhere-at-all/escape.bin"
            cases.append((tool.name, target, arguments))
    return cases


class TestEveryPathGoesThroughTheSandbox:
    def test_there_are_path_arguments_to_check(self, server, mcp):
        """Guards the guard: a filter that matches nothing passes vacuously."""
        assert len(_tool_cases(server, mcp)) >= 20

    def test_no_tool_accepts_a_path_outside_its_roots(self, server, mcp):
        """A path argument that reaches a leaf unresolved is the whole failure mode.

        Every tool is called with one path argument pointing outside every root
        and the rest filled with placeholders. Whatever else is wrong with the
        call, the answer must be a refusal from the sandbox — not a leaf error
        about a file the server was never given.
        """
        escapes = []
        for name, target, arguments in _tool_cases(server, mcp):
            result = mcp.call(server, name, arguments)
            text = mcp.text(result)
            if not result.is_error:
                escapes.append(f"{name}.{target}: succeeded")
                continue
            last = text.splitlines()[-1]
            if not last.startswith("{"):
                # No envelope means the call never reached the tool body — a
                # schema mismatch in this test, not a verdict about the tool.
                escapes.append(f"{name}.{target}: no envelope ({last})")
                continue
            kind = json.loads(last)["error"]["type"]
            if kind != "PathNotAllowedError":
                escapes.append(f"{name}.{target}: {kind}")
        assert not escapes


class TestNaming:
    def test_every_tool_is_prefixed_by_its_format(self, server, mcp):
        """So a client connected to two of these servers has no collisions."""
        for name in mcp.names(server):
            assert name.startswith(("pdf_", "docx_", "pptx_", "xlsx_", "rp_")), name

    def test_a_single_suite_server_keeps_the_same_prefixes(self, docs, mcp):
        """An agent's habits transfer between the combined and single servers."""
        combined = build_server(Sandbox([docs]), ALL_SUITES)
        single = build_server(Sandbox([docs]), ("pdf",))
        assert mcp.names(single) <= mcp.names(combined)

    def test_an_unknown_suite_is_refused_rather_than_skipped(self, docs):
        with pytest.raises(KeyError):
            build_server(Sandbox([docs]), ("notasuite",))


class TestTemplateNamesAndPaths:
    """`rp_mcp.tools._looks_like_a_path` claims to agree with all four leaves.

    It decides whether the sandbox applies to a template argument, so a
    disagreement is either a hole (a path treated as a name) or a broken
    feature (a name treated as a path). Asserted against what the leaves
    actually do, not against a copy of their source.
    """

    @pytest.mark.parametrize(
        "text", ["memo.dotx", "house.potx", "dir/memo", "./memo", "/tmp/memo.docx"]
    )
    def test_path_shaped_arguments_are_paths_to_all_four(self, text):
        assert _looks_like_a_path(text)
        with pytest.raises(TemplateError, match="No such template file"):
            rp_docx.resolve_template(text)
        with pytest.raises(Exception, match="No such template file"):
            rp_pptx.resolve_template(text)
        with pytest.raises(Exception, match="No such template file"):
            rp_xlsx.resolve_template(text)

    @pytest.mark.parametrize("text", ["memo", "house-letterhead", "quarterly"])
    def test_bare_names_are_names_to_all_four(self, text):
        assert not _looks_like_a_path(text)
        with pytest.raises(TemplateError, match="No template called"):
            rp_docx.resolve_template(text)
        with pytest.raises(Exception, match="Unknown template"):
            rp_pptx.resolve_template(text)
        with pytest.raises(Exception, match="Unknown template"):
            rp_xlsx.resolve_template(text)


class TestDependencyDirection:
    """rp-mcp imports the leaves; nothing imports rp-mcp back (parent spec §10)."""

    @staticmethod
    def _imports(path: pathlib.Path) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    @staticmethod
    def _sources(package) -> list[pathlib.Path]:
        return sorted(pathlib.Path(package.__file__).parent.rglob("*.py"))

    @pytest.mark.parametrize("package", [rp_docx, rp_pptx, rp_xlsx])
    def test_no_leaf_imports_rp_mcp(self, package):
        for source in self._sources(package):
            assert not [name for name in self._imports(source) if name.split(".")[0] == "rp_mcp"], (
                source
            )

    def test_rp_mcp_never_reaches_into_a_leaf_s_cli_layer(self):
        """The library surface is the contract; `cli` and `config` are not it.

        Importing `rp_pdf.config` here would silently make an MCP tool's
        behaviour depend on a *human's* config file, which is precisely the
        coupling the suite's "core never imports the CLI layer" rule prevents.
        """
        banned = {"rp_pdf.cli", "rp_pdf.config", "rp_docx.cli", "rp_pptx.cli", "rp_xlsx.cli"}
        for source in self._sources(rp_mcp):
            assert not (self._imports(source) & banned), source
