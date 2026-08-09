"""The `mcp` pin is a licensing constraint; assert it rather than describe it.

Four documents say the floor matters — the parent spec's §7.1 correction,
`rp-mcp-spec.md` §2, `ROADMAP.md`, and this package's own manifest comment. None
of them would notice the pin being loosened. `mcp` 1.x reaches `certifi`
(MPL-2.0) through `httpx`, and `rp-mcp` is in the license gate's base install
path, so dropping the floor puts weak copyleft there and makes both `extra:ai`
tags in `ci/allowed-packages.toml` stale in the same run.

The gate catches that eventually — but only after a resolve actually selects a
1.x release, which a lockfile prevents for as long as the lock stands. This
fails at the manifest.

**These assert the boundary, not the spelling.** The first version of this file
tested `">=2.0.0" in requirement` and `"<3" in requirement`, which is a check on
the characters rather than on what they mean: `mcp>=2.0.0,<30` contains the
substring `<3` and would have passed while admitting every major this pin exists
to exclude. Raised in review, and it is the same mistake AGENTS.md already names
— assert the observable the guarantee constrains, which here is *which releases
resolve*, so that is what these parametrize over.

`packaging` is not declared anywhere in this workspace; it arrives with pytest,
which is sufficient for a test module and nothing else.
"""

from __future__ import annotations

import pathlib

import pytest
import tomllib
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

MANIFEST = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _specifier(name: str) -> SpecifierSet:
    """The parsed version constraint `rp-mcp` declares for one dependency."""
    with open(MANIFEST, "rb") as handle:
        manifest = tomllib.load(handle)
    matches = [
        requirement
        for item in manifest["project"]["dependencies"]
        if (requirement := Requirement(item)).name == name
    ]
    assert len(matches) == 1, f"expected exactly one {name} requirement, got {matches}"
    return matches[0].specifier


#: (version, is it allowed) — the boundary in both directions.
MCP_VERSIONS = [
    ("1.0.0", False),  # floor: 1.x reaches certifi (MPL-2.0) through httpx
    ("1.99.99", False),
    ("2.0.0", True),  # the floor itself resolves
    ("2.999.999", True),  # any 2.x, however far it goes
    ("3.0.0", False),  # cap: `FastMCP` → `MCPServer` says majors rename things
    ("30.0.0", False),  # `<30` would satisfy a substring check for "<3"
]


@pytest.mark.parametrize(("version", "allowed"), MCP_VERSIONS, ids=[v for v, _ in MCP_VERSIONS])
def test_the_mcp_pin_admits_2_x_and_nothing_else(version, allowed):
    """2.x resolves; 1.x and 3.0 do not.

    The cap now binds every `pip install robo-papyro` user rather than only
    people who opted into an extra, which is what makes it worth pinning here:
    lifting it is a deliberate act with a test to change, and
    `.github/dependabot.yml` is what raises the question when a new major lands.
    """
    specifier = _specifier("mcp")
    assert specifier.contains(version) is allowed, (
        f"`mcp{specifier}` {'rejects' if allowed else 'admits'} {version}"
    )


def test_the_mcp_pin_is_bounded_at_both_ends():
    """A one-sided constraint passes every case above that it happens to cover;
    this fails outright when either bound is dropped."""
    operators = {specifier.operator for specifier in _specifier("mcp")}
    assert {">=", "<"} <= operators
