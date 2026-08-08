"""The path allowlist every MCP tool call goes through.

A CLI is bounded by the person typing it. An MCP server is not: it takes paths
from a model, over a socket, for as long as the client stays connected. So
rp-mcp resolves every path argument through a :class:`Sandbox` before it reaches
a leaf package, and the sandbox is the only place that decides what is legal.

Three rules, and each exists because of a specific way this goes wrong:

* **Containment is checked on the real path.** ``Path.resolve()`` runs first, so
  ``..`` segments are collapsed *and* symlinks are followed before the
  comparison. Checking a lexical path lets ``roots/link`` → ``/etc`` through
  while looking careful — the classic "validating a proxy is worse than
  validating nothing" failure.
* **Reading and writing are separate grants.** Roots make files readable; a
  server writes only when given a write root, and only inside it. The default
  is a read-only server, because reading a document the caller named is what an
  agent asks for nine times in ten, and the tenth should be deliberate.
* **An output path must be new.** The suite never overwrites an input without
  ``--in-place`` (parent spec section 10) and MCP has no ``--in-place``, so
  there is no spelling of "overwrite" here at all. Every write tool names an
  output that does not exist yet.

The write root is added to the readable roots, so an agent can read back what it
just wrote without a second grant.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from rp_mcp.errors import (
    NoRootsError,
    OutputExistsError,
    PathNotAllowedError,
    WritesNotEnabledError,
)
from rp_mcp.models import SandboxInfo

#: Readable roots, ``os.pathsep``-separated (``:`` on POSIX, ``;`` on Windows).
ROOTS_ENV = "RP_MCP_ROOTS"

#: The single writable directory. Unset means a read-only server.
WRITE_ROOT_ENV = "RP_MCP_WRITE_ROOT"


def _split_paths(value: str | None) -> list[Path]:
    """``os.pathsep``-separated paths, empties dropped.

    ``RP_MCP_ROOTS=""`` and an unset variable mean the same thing — no roots
    given — rather than one root named "".
    """
    if not value:
        return []
    return [Path(part) for part in value.split(os.pathsep) if part]


class Sandbox:
    """The set of directories a server may read, and the one it may write.

    Roots are resolved once, at construction: a symlinked root is compared as
    its target, so a path under it is not rejected for the wrong reason.
    """

    def __init__(
        self,
        roots: Iterable[str | Path],
        write_root: str | Path | None = None,
    ) -> None:
        resolved = [Path(root).expanduser().resolve() for root in roots]
        self.write_root = Path(write_root).expanduser().resolve() if write_root else None
        if self.write_root is not None:
            resolved.append(self.write_root)
        # dict.fromkeys rather than set(): deduplicated, order preserved, because
        # roots[0] is what a relative path resolves against and must be stable.
        self.roots: tuple[Path, ...] = tuple(dict.fromkeys(resolved))
        if not self.roots:
            raise NoRootsError(
                f"This server has no readable roots. Pass --root DIR, or set "
                f"{ROOTS_ENV} to an {os.pathsep!r}-separated list of directories."
            )

    @classmethod
    def from_settings(
        cls,
        roots: Iterable[str | Path] | None = None,
        write_root: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Sandbox:
        """Build from explicit settings, falling back to the environment, then cwd.

        The precedence is the suite's usual one — flag, then environment, then
        default — with the working directory as the last resort, so
        ``rp-pdf-mcp`` in a project directory does the obvious thing while
        ``--root`` and ``RP_MCP_ROOTS`` stay available for a client config that
        should not depend on where it was launched.
        """
        environ = os.environ if env is None else env
        chosen = list(roots or []) or _split_paths(environ.get(ROOTS_ENV)) or [Path.cwd()]
        target = write_root if write_root is not None else environ.get(WRITE_ROOT_ENV) or None
        return cls(chosen, target)

    @property
    def writable(self) -> bool:
        """Whether write tools should be registered at all."""
        return self.write_root is not None

    def info(self) -> SandboxInfo:
        """This sandbox as the ``rp_sandbox`` tool reports it."""
        return SandboxInfo(
            roots=list(self.roots),
            write_root=self.write_root,
            writable=self.writable,
        )

    @staticmethod
    def _absolute(path: str | Path, *, base: Path) -> Path:
        """``path`` made absolute against ``base``, with symlinks left alone.

        A ``NUL`` byte reaches the OS layer as ``ValueError`` rather than as a
        path that fails a containment check, so it is turned into the same
        refusal every other illegal path gets.
        """
        try:
            candidate = Path(path).expanduser()
            return candidate if candidate.is_absolute() else base / candidate
        except (OSError, ValueError) as exc:
            raise PathNotAllowedError(f"{path!r} is not a usable path: {exc}") from exc

    def _real(self, path: str | Path, *, base: Path) -> Path:
        """``path`` as an absolute, symlink-resolved path, relative to ``base``."""
        candidate = self._absolute(path, base=base)
        try:
            return candidate.resolve()
        except (OSError, ValueError) as exc:
            raise PathNotAllowedError(f"{path!r} is not a usable path: {exc}") from exc

    def _containing_root(self, resolved: Path) -> Path | None:
        return next((root for root in self.roots if resolved.is_relative_to(root)), None)

    def resolve_input(self, path: str | Path) -> Path:
        """A path a tool may read, or :class:`~rp_mcp.errors.PathNotAllowedError`.

        Existence is *not* checked here. A missing file is the leaf package's
        error to raise, with its own message and exit code, and checking it here
        would make the sandbox report "no such file" for paths outside it — an
        existence oracle for the whole filesystem, one call at a time.
        """
        resolved = self._real(path, base=self.roots[0])
        if self._containing_root(resolved) is None:
            allowed = ", ".join(str(root) for root in self.roots)
            raise PathNotAllowedError(
                f"{resolved} is outside this server's allowed roots ({allowed}). "
                "Start the server with --root DIR to widen them."
            )
        return resolved

    def _writable_target(self, path: str | Path) -> Path:
        if self.write_root is None:
            raise WritesNotEnabledError(
                "This server is read-only. Start it with --write-root DIR (or set "
                f"{WRITE_ROOT_ENV}) to enable the tools that create files."
            )
        resolved = self._real(path, base=self.write_root)
        if not resolved.is_relative_to(self.write_root):
            raise PathNotAllowedError(
                f"{resolved} is outside this server's write root ({self.write_root}). "
                "Every file a tool creates goes there."
            )
        return resolved

    def resolve_output(self, path: str | Path) -> Path:
        """A path a tool may create, with its parent directories made.

        Refuses an existing path of any kind — including a symlink, whether or
        not it points at anything. ``Path.resolve()`` follows a link, so a
        dangling one looks free while a write through it lands on a path the
        caller never named; the *spelled* path is therefore checked with
        ``is_symlink`` (an ``lstat``) before the resolved one is checked for
        existence.

        Parent directories are created, because the alternative is an agent
        having to guess which of its own outputs needs a ``mkdir`` it has no
        tool for. They are only ever created inside the write root.
        """
        resolved = self._writable_target(path)  # also proves write_root is set
        literal = self._absolute(path, base=self.write_root)  # type: ignore[arg-type]
        if literal.is_symlink():
            raise OutputExistsError(
                f"{literal} is a symbolic link. Tools in this server write new files "
                "only: choose a name that is not taken."
            )
        if resolved.exists():
            raise OutputExistsError(
                f"{resolved} already exists. Tools in this server never overwrite: "
                "choose a new name."
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def resolve_output_dir(self, path: str | Path) -> Path:
        """A directory a tool may write *into*, created if absent.

        Unlike :meth:`resolve_output` an existing directory is fine — it is the
        destination, not the artifact. An existing non-directory is not.
        """
        resolved = self._writable_target(path)
        if resolved.exists() and not resolved.is_dir():
            raise OutputExistsError(f"{resolved} exists and is not a directory.")
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved


__all__ = ["ROOTS_ENV", "WRITE_ROOT_ENV", "Sandbox"]
