#!/usr/bin/env python3
"""Fail the build if uv.lock contains a package that has not been license-checked.

Four independent checks, because they fail for different reasons:

* **Forbidden** — a package the spec names as a blocker (copyleft or
  commercial). Listed explicitly so it can never be added by accident, even if
  someone also adds it to the allowlist.
* **Unreviewed** — a package that is simply not in ``ci/allowed-packages.toml``.
  Not an accusation, just an unanswered question: someone has to look at its
  license and record the answer.
* **Base path is clean** — no weak-copyleft package may appear in the *base
  install path*: the union of runtime dependencies of the published
  distributions, resolved with no optional extras and excluding the dev group.
  Spec §7.1 permits weak copyleft only as a transitive, optional dependency;
  this is what makes that a check rather than a hope.
* **Tags are true** — every allowlist entry tagged ``extra:<name>`` must be
  genuinely unreachable from the base path. A tag is a claim about the
  dependency graph, and graphs move. This fails independently of whether the
  package is otherwise allowed, so a tag going stale is caught even when
  nothing else is wrong.

Run with no arguments from the repository root. Exits 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import re
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

#: File-level copyleft, permitted by §7.1 only as an unmodified transitive
#: dependency outside the base install path. Strong copyleft is in FORBIDDEN.
WEAK_COPYLEFT = {
    "MPL-1.1",
    "MPL-2.0",
    "EPL-1.0",
    "EPL-2.0",
    "CDDL-1.0",
    "CDDL-1.1",
    "CPL-1.0",
    "MS-RL",
    "OSL-3.0",
}

#: Prefix marking an allowlist entry as reachable only through an optional extra.
EXTRA_TAG = "extra:"

_TOKEN = re.compile(r"[^A-Za-z0-9.+\-]+")


def normalize(name: str) -> str:
    return name.lower().replace("_", ".").replace("-", ".")


def weak_copyleft_in(expression: str) -> list[str]:
    """Weak-copyleft identifiers in an SPDX expression.

    Any occurrence counts, including inside an ``OR``. A permissive alternative
    may well make the package fine, but that is a judgement for a human to
    record — the gate's job is to stop it entering the base path unnoticed.
    """
    tokens = {t for t in _TOKEN.split(expression) if t}
    weak = {w.upper() for w in WEAK_COPYLEFT}
    return sorted(t for t in tokens if t.upper() in weak)


def workspace_members() -> set[str]:
    return {normalize(p.parent.name) for p in (ROOT / "packages").glob("*/pyproject.toml")}


def locked() -> dict:
    with open(LOCKFILE, "rb") as f:
        return tomllib.load(f)


def locked_packages(lock: dict) -> set[str]:
    return {normalize(p["name"]) for p in lock.get("package", [])}


def base_install_path(lock: dict) -> set[str]:
    """The union of runtime dependencies of the published distributions.

    Reached by walking each locked package's ``dependencies`` only. uv keeps
    extras under ``optional-dependencies`` and the dev group under
    ``dev-dependencies``, so following the one key is exactly "no extras, no
    dev group" — no filtering required, and nothing to fall out of step with
    how the extras are declared.
    """
    index = {normalize(p["name"]): p for p in lock.get("package", [])}
    seen: set[str] = set()
    queue = sorted(workspace_members())
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        package = index.get(name)
        if package is None:
            continue
        queue.extend(normalize(dep["name"]) for dep in package.get("dependencies", []))
    return seen


def declared_extras(lock: dict) -> set[str]:
    return {
        extra
        for package in lock.get("package", [])
        if normalize(package["name"]) in workspace_members()
        for extra in package.get("optional-dependencies", {})
    }


def allowed() -> dict[str, dict]:
    """Allowlist entries as ``{normalized name: {"license": ..., "tag": ...}}``.

    An entry is either a bare license string or a table, so tagging a package
    does not disturb the sixty that need no tag.
    """
    with open(ALLOWLIST, "rb") as f:
        data = tomllib.load(f)
    entries: dict[str, dict] = {}
    for section in data.values():
        for name, value in section.items():
            entry = {"license": value} if isinstance(value, str) else dict(value)
            entries[normalize(name)] = entry
    return entries


def _forbidden_hits(locked_names: set[str]) -> list[tuple[str, str]]:
    return sorted(
        (name, reason)
        for name in locked_names
        for bad, reason in FORBIDDEN.items()
        if normalize(bad) in name
    )


def _weak_in_base(base: set[str], entries: dict[str, dict]) -> list[tuple[str, str]]:
    hits = []
    for name in sorted(base - workspace_members()):
        entry = entries.get(name)
        if entry is None:  # reported as UNREVIEWED; nothing to classify yet
            continue
        found = weak_copyleft_in(entry["license"])
        if found:
            hits.append((name, ", ".join(found)))
    return hits


def _stale_tags(
    base: set[str], entries: dict[str, dict], extras: set[str]
) -> list[tuple[str, str]]:
    problems = []
    for name, entry in sorted(entries.items()):
        tag = entry.get("tag")
        if tag is None:
            continue
        if not tag.startswith(EXTRA_TAG) or not tag[len(EXTRA_TAG) :]:
            problems.append((name, f"tag {tag!r} is not of the form '{EXTRA_TAG}<name>'"))
            continue
        extra = tag[len(EXTRA_TAG) :]
        if extras and extra not in extras:
            problems.append((name, f"tag names extra {extra!r}, which no distribution declares"))
        elif name in base:
            problems.append((name, f"tagged {tag!r} but it is in the base install path"))
    return problems


def main() -> int:
    if not LOCKFILE.is_file():
        print(f"error: {LOCKFILE} not found; run 'uv sync' first.", file=sys.stderr)
        return 1

    lock = locked()
    locked_names = locked_packages(lock)
    entries = allowed()
    base = base_install_path(lock)

    forbidden_hits = _forbidden_hits(locked_names)
    unreviewed = sorted(locked_names - set(entries) - workspace_members())
    weak_in_base = _weak_in_base(base, entries)
    stale_tags = _stale_tags(base, entries, declared_extras(lock))

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
    for name, licenses in weak_in_base:
        print(
            f"BASE PATH: {name} ({licenses}) is weak copyleft and is reachable from a "
            "base install — no extras, no dev group. §7.1 permits weak copyleft only "
            "as a transitive optional dependency. Move it behind an extra or drop it; "
            "allowlisting does not make this pass.",
            file=sys.stderr,
        )
    for name, problem in stale_tags:
        print(
            f"STALE TAG: {name} — {problem}. Tags in ci/allowed-packages.toml are "
            "checked claims about the dependency graph, not annotations.",
            file=sys.stderr,
        )

    failures = len(forbidden_hits) + len(unreviewed) + len(weak_in_base) + len(stale_tags)
    if failures:
        print(
            f"\nlicense gate failed: {len(forbidden_hits)} forbidden, "
            f"{len(unreviewed)} unreviewed, {len(weak_in_base)} weak copyleft in the "
            f"base path, {len(stale_tags)} stale tags.",
            file=sys.stderr,
        )
        return 1

    print(
        f"license gate passed: {len(locked_names)} packages, all reviewed; "
        f"base install path is {len(base)} distributions, free of weak copyleft."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
