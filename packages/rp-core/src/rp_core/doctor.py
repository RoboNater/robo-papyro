"""Capability reporting: which external binaries are present, and where.

Every optional code path in the suite sits behind one of these. ``doctor`` is
how a user (or an agent) finds out what will work before running it.
"""

from __future__ import annotations

import re

from rp_core.binaries import INSTALL_HINTS, find_binary, run_binary
from rp_core.models import Capability

#: Binaries doctor knows how to report on, and the argument that makes each
#: print its version.
VERSION_FLAGS: dict[str, str] = {
    "soffice": "--version",
    "pdftoppm": "-v",
    "pdftotext": "-v",
    "pdfinfo": "-v",
}

_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*)")


def _version_of(name: str, path) -> str | None:
    """Best-effort version string. Never raises: a binary that is present but
    will not report a version is still a usable binary."""
    try:
        proc = run_binary(path, [VERSION_FLAGS.get(name, "--version")], timeout=15)
    except Exception:
        return None
    # poppler tools print their version banner on stderr, LibreOffice on stdout.
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def capability(name: str) -> Capability:
    """Report on a single binary by name."""
    path = find_binary(name)
    return Capability(
        name=name,
        available=path is not None,
        version=_version_of(name, path) if path is not None else None,
        path=path,
        install_hint=INSTALL_HINTS.get(name, ""),
    )


def report(*names: str) -> list[Capability]:
    """Report on each named binary, in the order given."""
    return [capability(name) for name in names]
