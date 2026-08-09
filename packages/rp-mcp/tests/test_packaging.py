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
"""

from __future__ import annotations

import pathlib

import tomllib

MANIFEST = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _requirement(name: str) -> str:
    with open(MANIFEST, "rb") as handle:
        manifest = tomllib.load(handle)
    matches = [
        item for item in manifest["project"]["dependencies"] if item.split(">")[0].strip() == name
    ]
    assert len(matches) == 1, f"expected exactly one {name} requirement, got {matches}"
    return matches[0]


def test_the_mcp_floor_is_declared():
    """1.x is a licensing regression, not only an API one."""
    assert ">=2.0.0" in _requirement("mcp")


def test_the_mcp_cap_is_declared():
    """The server class was `FastMCP` through 1.x and is `MCPServer` in 2.x, so
    this project does rename its public surface across a major.

    The cap now binds every `pip install robo-papyro` user rather than only
    people who opted into an extra, which is what makes it worth pinning here:
    lifting it is a deliberate act with a test to change, and
    `.github/dependabot.yml` is what raises the question when a new major lands.
    """
    assert "<3" in _requirement("mcp")
