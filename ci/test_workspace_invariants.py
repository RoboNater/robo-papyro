"""Workspace-level invariants from spec section 10, enforced rather than documented.

The two package-local invariants live with their subjects:

* command registration — `packages/rp-pdf/tests/test_invariants.py`
* no leaf imports in the umbrella — `packages/robo-papyro/tests/test_umbrella_cli.py`,
  class `TestNoLeafImports`

What is left is what belongs to no single package.
"""

from __future__ import annotations

import ast
import pathlib

import rp_core

RP_CORE = pathlib.Path(rp_core.__file__).parent


def test_test_modules_are_imported_by_path_not_by_name(pytestconfig):
    """Invariant 3: same-named test modules in different packages must not collide.

    Under pytest's default "prepend" import mode each tests/ directory goes on
    sys.path and modules are imported by bare basename, so the second
    `test_render.py` in the workspace is silently skipped — which is what
    happened to rp-core's. importlib mode imports each file by path instead.

    Note the spelling: spec section 3 shows this as an ini key
    (`importmode = "importlib"`), but pytest registers `--import-mode` as a
    command-line option only. Setting the ini key raises a PytestConfigWarning
    and changes nothing, so the root config uses `addopts`.
    """
    assert pytestconfig.getoption("importmode") == "importlib"


def _identifiers(tree: ast.AST) -> set[str]:
    """Every name a module defines or refers to — not its prose."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            names.update(arg.arg for arg in node.args.args + node.args.kwonlyargs)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def test_rp_core_models_no_page_labels():
    """Section 10: rp-core contains no format-specific identifier.

    A page *label* — the "iv" or "FM2" a reader displays — is PDF knowledge.
    Phase 0 moved the whole of pages.py into rp-core, label resolution
    included; Phase 0.5 split it back out. This fails if it drifts back.
    rp-core may still say "label" in prose explaining why it does not model
    one, so only identifiers are checked.
    """
    offenders = {}
    for path in sorted(RP_CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = sorted(n for n in _identifiers(tree) if "label" in n.lower())
        if found:
            offenders[path.name] = found
    assert offenders == {}


def test_rp_core_imports_no_leaf_package():
    """Section 10: dependencies are one-way. rp-core is the base, never a consumer."""
    for path in sorted(RP_CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert not {r for r in roots if r.startswith("rp_") and r != "rp_core"}, path.name
