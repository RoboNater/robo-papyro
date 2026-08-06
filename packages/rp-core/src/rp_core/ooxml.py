"""OOXML package mechanics that no format owns.

Promoted out of ``rp_docx.ooxml`` by rp-pptx-spec section 12 step 2, once a
second leaf needed the same three things: reading parts out of the package zip,
writing a modified package back, and running XPath with a namespace map that is
actually complete.

**The invariant that keeps this in core** (robo-papyro-spec section 10: no
format-specific identifier in ``rp_core``): namespace maps and content-type
strings are *arguments*. Nothing here mentions ``w:``, ``p:``, ``a:``,
``word/``, or ``ppt/``, and nothing here raises a format-specific error — a
missing part is ``None`` and a malformed one is a plain ``ValueError``, because
only the leaf knows whether that means "corrupt .docx" or "corrupt .pptx" and
which exit code goes with it. Leaves keep their own ``check_readable``, their own
error classes, and their own namespace maps.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Callable, Collection, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

__all__ = [
    "CONTENT_TYPES_PART",
    "compiled_xpath",
    "content_type_from",
    "parse_part",
    "part_names",
    "qualified_name",
    "read_part",
    "repack",
    "retype",
]

#: The one part name that is the same in every OOXML package there is.
CONTENT_TYPES_PART = "[Content_Types].xml"


# --- XPath over a caller-supplied namespace map ------------------------------


def qualified_name(tag: str, namespaces: Mapping[str, str]) -> str:
    """``"w:t"`` → ``"{http://…/main}t"`` — a Clark-notation qualified name."""
    prefix, _, local = tag.partition(":")
    if not local:
        return tag
    try:
        return f"{{{namespaces[prefix]}}}{local}"
    except KeyError as exc:  # a typo'd prefix is a bug in the leaf, not user input
        raise KeyError(f"Unknown XML namespace prefix {prefix!r}") from exc


@lru_cache(maxsize=256)
def _compiled(expr: str, namespaces: tuple[tuple[str, str], ...]) -> etree.XPath:
    return etree.XPath(expr, namespaces=dict(namespaces))


def compiled_xpath(namespaces: Mapping[str, str]) -> Callable[[Any, str], list]:
    """An ``xpath(element, expr)`` function with ``namespaces`` bound.

    Compiled and cached rather than called as ``element.xpath(...)``, because
    **both** python-docx and python-pptx subclass lxml's ``_Element`` and
    override ``xpath`` with a single-argument version binding *their own*
    namespace map — and both of those maps omit namespaces the leaf packages
    need. Going through ``etree.XPath`` means one expression behaves the same
    whether the element arrived from a library object or straight from lxml.

    The map is frozen into a tuple so the cache key is hashable; callers are
    expected to hold the returned function at module level, not rebuild it.
    """
    frozen = tuple(sorted(namespaces.items()))

    def xpath(element: Any, expr: str) -> list:
        return _compiled(expr, frozen)(element)

    return xpath


# --- the package zip ---------------------------------------------------------


def part_names(path: Path) -> list[str]:
    """Every part in the package, in archive order."""
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def read_part(path: Path, name: str) -> bytes | None:
    """One part's bytes, or ``None`` when the package does not contain it.

    ``None`` rather than an exception because plenty of parts are genuinely
    optional — a comments part exists only once someone has commented.
    """
    with zipfile.ZipFile(path) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return None


def parse_part(path: Path, name: str) -> Any | None:
    """One part parsed as XML, or ``None`` when it is absent.

    Raises ``ValueError`` when the part exists but is not well-formed. The leaf
    catches that and re-raises it as its own corrupt-file error, which is the
    one that carries an exit code.
    """
    data = read_part(path, name)
    if data is None:
        return None
    try:
        return etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"{name} is not well-formed XML ({exc})") from exc


def repack(
    source: Path,
    target: Path,
    replacements: Mapping[str, bytes],
    *,
    omit: Collection[str] = (),
) -> Path:
    """Copy the package, substituting the named parts.

    Order and per-entry compression are preserved: some OPC readers expect
    ``[Content_Types].xml`` first, and rewriting a package should not silently
    re-compress the images in it. A replacement whose name is not already in the
    archive is appended, which is how a leaf adds a part it has authored.

    ``omit`` drops parts entirely. Dropping one that something still points at
    produces a broken package, so callers are expected to rewrite the
    referencing rels and content types in the same call — which is why omission
    is a parameter here rather than a separate pass.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    dropped = set(omit)
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w") as out:
        existing = set(archive.namelist())
        for item in archive.infolist():
            if item.filename in dropped and item.filename not in replacements:
                continue
            data = replacements.get(item.filename)
            if data is None:
                data = archive.read(item.filename)
            out.writestr(item, data, compress_type=item.compress_type)
        for name, data in replacements.items():
            if name not in existing:
                out.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return target


# --- content types -----------------------------------------------------------


def content_type_from(path: Path, candidates: tuple[str, ...]) -> str | None:
    """The first of ``candidates`` the package's content types declare.

    ``None`` when it declares none of them — the leaf decides whether that means
    "not my format" or something else, and what to raise about it.
    """
    data = read_part(path, CONTENT_TYPES_PART)
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    return next((candidate for candidate in candidates if candidate in text), None)


def retype(source: Path, target: Path | None, frm: str, to: str) -> Path:
    """Copy the package with content type ``frm`` rewritten to ``to``.

    ``target=None`` retypes in place, staging in a temp directory and moving
    atomically, so an interrupted retype cannot leave a half-written package
    where a template used to be.
    """
    source = Path(source)
    data = read_part(source, CONTENT_TYPES_PART)
    if data is None:
        raise ValueError(f"{source.name} has no {CONTENT_TYPES_PART}; not an OOXML package")
    rewritten = data.replace(frm.encode(), to.encode())

    if target is not None:
        return repack(source, Path(target), {CONTENT_TYPES_PART: rewritten})

    with tempfile.TemporaryDirectory(prefix="rp-retype-") as tmp:
        staged = repack(source, Path(tmp) / source.name, {CONTENT_TYPES_PART: rewritten})
        shutil.move(str(staged), str(source))
    return source
