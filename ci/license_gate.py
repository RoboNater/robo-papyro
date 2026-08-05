#!/usr/bin/env python3
"""Fail the build if uv.lock contains a package that has not been license-checked.

Two independent checks, because they fail for different reasons:

* **Forbidden** — a package the spec names as a blocker (copyleft or
  commercial). Listed explicitly so it can never be added by accident, even if
  someone also adds it to the allowlist.
* **Unreviewed** — a package that is simply not in ``ci/allowed-packages.toml``.
  Not an accusation, just an unanswered question: someone has to look at its
  license and record the answer.

Run with no arguments from the repository root. Exits 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = ROOT / "uv.lock"
ALLOWLIST = ROOT / "ci" / "allowed-packages.toml"

#: Named in docs/specs/robo-papyro-spec.md §7 as blockers. Substring match, so
#: a fork or a differently-cased variant is caught too.
FORBIDDEN = {
    "docxtpl": "LGPL-2.1-only",
    "pymupdf": "AGPL",
    "fitz": "AGPL",
    "pypandoc": "GPL (bundles pandoc)",
    "pandoc": "GPL",
    "aspose": "commercial",
    "spire": "commercial",
    "unoconv": "GPL",
}


def normalize(name: str) -> str:
    return name.lower().replace("_", ".").replace("-", ".")


def workspace_members() -> set[str]:
    return {normalize(p.parent.name) for p in (ROOT / "packages").glob("*/pyproject.toml")}


def locked_packages() -> set[str]:
    with open(LOCKFILE, "rb") as f:
        lock = tomllib.load(f)
    return {normalize(p["name"]) for p in lock.get("package", [])}


def allowed() -> set[str]:
    with open(ALLOWLIST, "rb") as f:
        data = tomllib.load(f)
    return {normalize(name) for section in data.values() for name in section}


def main() -> int:
    if not LOCKFILE.is_file():
        print(f"error: {LOCKFILE} not found; run 'uv sync' first.", file=sys.stderr)
        return 1

    locked = locked_packages()
    permitted = allowed() | workspace_members()

    forbidden_hits = sorted(
        (name, reason)
        for name in locked
        for bad, reason in FORBIDDEN.items()
        if normalize(bad) in name
    )
    unreviewed = sorted(locked - permitted)

    for name, reason in forbidden_hits:
        print(
            f"FORBIDDEN: {name} ({reason}) is in uv.lock. "
            "Copyleft and commercial licenses are blockers in this environment "
            "(docs/specs/robo-papyro-spec.md §7) — remove it, do not allowlist it.",
            file=sys.stderr,
        )
    for name in unreviewed:
        print(
            f"UNREVIEWED: {name} is in uv.lock but not in ci/allowed-packages.toml. "
            "Check its license; if it is permissive, add it there with the license "
            "you found.",
            file=sys.stderr,
        )

    if forbidden_hits or unreviewed:
        print(
            f"\nlicense gate failed: {len(forbidden_hits)} forbidden, "
            f"{len(unreviewed)} unreviewed.",
            file=sys.stderr,
        )
        return 1

    print(f"license gate passed: {len(locked)} packages, all reviewed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
