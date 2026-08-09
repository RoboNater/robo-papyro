"""Template resolution (spec section 5.1).

Only :func:`resolve_template` and its supporting lookups land here in Phase 3
step 7 — ``create()`` needs it. ``inspect_template``, ``build_manifest``, and
``synthesize`` land in step 8, which is checkpointed separately because they
are the least certain part of the phase.

**Resolution follows `rp-docx`'s convention, not `rp-pptx`'s divergent one**
(spec section 5.1): ``RP_XLSX_TEMPLATE_DIR`` splits on ``os.pathsep`` and
searches ancestor repo roots, matching ``RP_DOCX_TEMPLATE_DIR``.
``RP_PPTX_TEMPLATE_DIR`` diverged (a single directory, ``./templates`` only)
and ``AGENTS.md`` records that as a written-up gap rather than a pattern to
repeat.

**``resolve_template(None)`` returns ``None`` here, unlike its two siblings**
(spec section 4). openpyxl ships no bundled workbook to fall back to —
``Workbook()`` is not a template, it is an empty file — so inventing a
default would mean shipping a binary or synthesizing one nobody asked for.
``create(template=None)`` starts from ``openpyxl.Workbook()`` directly.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

import os
from pathlib import Path

from rp_xlsx.errors import TemplateError
from rp_xlsx.ooxml import SUPPORTED_SUFFIXES, TEMPLATE_SUFFIXES

TEMPLATE_DIR_ENV = "RP_XLSX_TEMPLATE_DIR"
DEFAULT_TEMPLATE_ENV = "RP_XLSX_TEMPLATE"

#: `.xltx` before `.xltm` before `.xlsx`, matching the order spec section 5.1
#: gives: a template is what was asked for, and a macro-enabled one is more
#: specific than a plain workbook of the same name.
LOOKUP_SUFFIXES = (*TEMPLATE_SUFFIXES, ".xlsx")

assert set(LOOKUP_SUFFIXES) <= set(SUPPORTED_SUFFIXES)  # keep in sync with ooxml.py


def repo_root(start: Path | None = None) -> Path | None:
    """The nearest ancestor of ``start`` that looks like the project checkout.

    Templates live in ``<repo>/templates/``, which only means anything when
    running from a checkout — an installed wheel has no repo. The marker is a
    ``templates`` directory next to a ``.git`` or ``pyproject.toml``, so an
    unrelated ``templates/`` in some working directory is not mistaken for the
    suite's.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "templates").is_dir() and (
            (candidate / ".git").exists() or (candidate / "pyproject.toml").is_file()
        ):
            return candidate
    return None


def template_dirs() -> list[Path]:
    """Where a bare template name is looked up, in precedence order.

    ``RP_XLSX_TEMPLATE_DIR`` first (it may name several directories, split
    the way ``PATH`` is), then the checkout's ``templates/local/`` and
    ``templates/``. ``local/`` comes first because it is the gitignored drop
    point for the *real* templates (spec section 11.1): when a name exists in
    both, the real one is the one meant.
    """
    dirs: list[Path] = []
    configured = os.environ.get(TEMPLATE_DIR_ENV, "")
    for entry in configured.split(os.pathsep):
        if entry.strip():
            dirs.append(Path(entry.strip()).expanduser())
    root = repo_root()
    if root is not None:
        dirs.extend([root / "templates" / "local", root / "templates"])
    return [d for d in dirs if d.is_dir()]


def _lookup(name: str) -> Path | None:
    for directory in template_dirs():
        for suffix in LOOKUP_SUFFIXES:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def available_template_names() -> list[str]:
    """Bare names :func:`resolve_template` would find, de-duplicated."""
    names: list[str] = []
    for directory in template_dirs():
        for suffix in LOOKUP_SUFFIXES:
            names.extend(path.stem for path in sorted(directory.glob(f"*{suffix}")))
    return sorted(dict.fromkeys(names))


def _looks_like_a_path(value: str) -> bool:
    """Whether the argument is a path the user got wrong, or a name to look up.

    Anything carrying a suffix or a separator was meant as a path (spec
    section 5.1 case 4), and reporting "no template called
    ../drafts/quarterly.xltx" would send the user hunting through the
    template directories for a typo in their own path.
    """
    as_path = Path(value)
    return bool(as_path.suffix) or os.sep in value or (os.altsep and os.altsep in value)


def resolve_template(name_or_path: str | Path | None = None) -> Path | None:
    """Find the template a caller means (spec section 5.1).

    1. An existing path is used as given
    2. A bare name resolves against :func:`template_dirs`, `.xltx` before
       `.xltm` before `.xlsx`
    3. ``None`` uses ``RP_XLSX_TEMPLATE`` if set, else ``None`` — this
       package's considered divergence from its two siblings (module
       docstring)
    4. A path-shaped argument that does not exist raises, naming the *path*
    5. An unresolvable name raises, listing the available templates
    """
    if name_or_path is None:
        configured = os.environ.get(DEFAULT_TEMPLATE_ENV, "").strip()
        return resolve_template(configured) if configured else None

    as_path = Path(name_or_path)
    if as_path.is_file():
        return as_path

    text = str(name_or_path)
    if _looks_like_a_path(text):
        raise TemplateError(f"No such template file: {text}")

    found = _lookup(text)
    if found is not None:
        return found

    names = available_template_names()
    listed = ", ".join(names) if names else "none found"
    raise TemplateError(f"Unknown template {text!r}; available templates: {listed}")


__all__ = [
    "DEFAULT_TEMPLATE_ENV",
    "LOOKUP_SUFFIXES",
    "TEMPLATE_DIR_ENV",
    "available_template_names",
    "repo_root",
    "resolve_template",
    "template_dirs",
]
