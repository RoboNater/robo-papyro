"""The OOXML layer: namespaces, the package zip, and content types.

`python-docx` covers paragraphs, tables, and styles. It covers *none* of
comments, tracked changes, or the `.dotx` content type, and those need the
package opened as what it is — a zip of XML parts. Everything that reaches past
python-docx goes through this module, so there is exactly one namespace map in
the package and exactly one place that knows how a `.docx` is packed.

**The `.dotx` finding.** python-docx does not open a `.dotx` at all. It inspects
``[Content_Types].xml``, sees the template content type, and raises
``ValueError: ... is not a Word file``. Since house templates are the normal path
(spec section 5), every entry point that accepts a template routes through
:func:`opened`, which retypes a copy in a temp directory first. Retyping is
lossless in both directions — the part list is byte-for-byte identical across an
open/save cycle — so this costs a copy and nothing else.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from rp_docx.errors import InvalidDocxError, MissingFileError

#: Every namespace this package resolves, in one place (spec section 7).
NS: dict[str, str] = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}

DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
TEMPLATE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
)

#: Package parts this package reads directly, because python-docx exposes no API
#: for them.
COMMENTS_PART = "word/comments.xml"
COMMENTS_EXTENDED_PART = "word/commentsExtended.xml"
DOCUMENT_PART = "word/document.xml"


def qn(tag: str) -> str:
    """``"w:t"`` → ``"{http://…/main}t"`` — a Clark-notation qualified name."""
    prefix, _, local = tag.partition(":")
    if not local:
        return tag
    try:
        return f"{{{NS[prefix]}}}{local}"
    except KeyError as exc:  # a typo'd prefix is a bug here, not user input
        raise KeyError(
            f"Unknown XML namespace prefix {prefix!r}; add it to rp_docx.ooxml.NS"
        ) from exc


@lru_cache(maxsize=256)
def _compiled(expr: str) -> etree.XPath:
    return etree.XPath(expr, namespaces=NS)


def xpath(element: Any, expr: str) -> list:
    """Run ``expr`` against ``element`` with the package namespace map bound.

    Compiled and cached rather than called as ``element.xpath(...)``, because
    python-docx subclasses ``_Element`` and overrides ``xpath`` with a
    single-argument version that binds *its* namespace map — which omits
    several of the namespaces this package needs. Going through
    ``etree.XPath`` means one expression behaves the same whether the element
    came from python-docx or straight from lxml.
    """
    return _compiled(expr)(element)


def attr(element: Any, name: str, default: str | None = None) -> str | None:
    """A namespaced attribute (``"w:val"``) off ``element``."""
    return element.get(qn(name), default)


# --- the package zip -------------------------------------------------------


def check_readable(path: Path) -> Path:
    """Fail early, and with the right error, on a path that is not a package.

    A missing file is the user's mistake (exit 1); a file that is not a zip is a
    corrupt-or-wrong-format problem (exit 3). python-docx conflates both into
    ``PackageNotFoundError``, so the distinction is drawn here instead.
    """
    path = Path(path)
    if not path.exists():
        raise MissingFileError(f"No such file: {path}")
    if not path.is_file():
        raise MissingFileError(f"Not a file: {path}")
    if not zipfile.is_zipfile(path):
        raise InvalidDocxError(
            f"{path.name} is not a Word document: it is not an OOXML package "
            "(a .docx/.dotx file is a zip archive). A legacy binary .doc is not supported."
        )
    return path


def part_names(path: Path) -> list[str]:
    """Every part in the package, in archive order."""
    check_readable(path)
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def read_part(path: Path, name: str) -> bytes | None:
    """One part's bytes, or ``None`` when the package does not contain it.

    ``None`` rather than an exception because several parts this package reads
    are genuinely optional: ``commentsExtended.xml`` exists only once someone has
    resolved a comment.
    """
    check_readable(path)
    with zipfile.ZipFile(path) as archive:
        try:
            return archive.read(name)
        except KeyError:
            return None


def parse_part(path: Path, name: str) -> Any | None:
    """One part parsed as XML, or ``None`` when it is absent."""
    data = read_part(path, name)
    if data is None:
        return None
    try:
        return etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise InvalidDocxError(f"{path.name}: {name} is not well-formed XML ({exc}).") from exc


def repack(source: Path, target: Path, replacements: dict[str, bytes]) -> Path:
    """Copy the package, substituting the named parts.

    Order and per-entry compression are preserved: some OPC readers expect
    ``[Content_Types].xml`` first, and rewriting a package should not silently
    re-compress the images in it.
    """
    check_readable(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w") as out:
        for item in archive.infolist():
            data = replacements.get(item.filename)
            if data is None:
                data = archive.read(item.filename)
            out.writestr(item, data, compress_type=item.compress_type)
    return target


# --- content types: .docx vs .dotx -----------------------------------------


def content_type(path: Path) -> str:
    """The package's main-document content type.

    This is the only thing that distinguishes a `.dotx` from a `.docx` in
    practice — the parts, the styles, and the markup are otherwise the same.
    """
    data = read_part(path, "[Content_Types].xml")
    if data is None:
        raise InvalidDocxError(
            f"{path.name} has no [Content_Types].xml; it is not an OOXML package."
        )
    text = data.decode("utf-8", "replace")
    if TEMPLATE_CONTENT_TYPE in text:
        return TEMPLATE_CONTENT_TYPE
    if DOCUMENT_CONTENT_TYPE in text:
        return DOCUMENT_CONTENT_TYPE
    raise InvalidDocxError(
        f"{path.name} is an OOXML package but not a Word one — its content types name "
        "neither a document nor a template main part."
    )


def is_template(path: Path) -> bool:
    """Whether the package declares itself a template (`.dotx`)."""
    return content_type(path) == TEMPLATE_CONTENT_TYPE


def _retype(path: Path, output: Path | None, frm: str, to: str) -> Path:
    data = read_part(path, "[Content_Types].xml")
    assert data is not None  # content_type() below would have raised
    rewritten = data.replace(frm.encode(), to.encode())

    if output is not None:
        return repack(path, Path(output), {"[Content_Types].xml": rewritten})

    # In place: write beside the original and replace atomically, so an
    # interrupted retype cannot leave a half-written package where a template
    # used to be. This is the only path in the package that rewrites its input,
    # and callers reach it only for a file they just created themselves.
    with tempfile.TemporaryDirectory(prefix="rp-docx-retype-") as tmp:
        staged = repack(path, Path(tmp) / path.name, {"[Content_Types].xml": rewritten})
        shutil.move(str(staged), str(path))
    return path


def retype_as_template(path: Path, output: Path | None = None) -> Path:
    """Rewrite the main-document content type to the template one (`.dotx`).

    A no-op copy when it already is one. ``output=None`` retypes in place.
    """
    return _retype(path, output, DOCUMENT_CONTENT_TYPE, TEMPLATE_CONTENT_TYPE)


def retype_as_document(path: Path, output: Path | None = None) -> Path:
    """Rewrite the main-document content type to the document one (`.docx`)."""
    return _retype(path, output, TEMPLATE_CONTENT_TYPE, DOCUMENT_CONTENT_TYPE)


@contextmanager
def opened(path: Path) -> Iterator[Any]:
    """A python-docx ``Document`` for a `.docx` **or** a `.dotx`.

    python-docx rejects the template content type outright, so a template is
    retyped into a temporary copy first and opened from there. The document is
    yielded rather than returned because the temporary copy has to outlive it:
    python-docx keeps the package open for lazy part access.

    Use this everywhere instead of ``docx.Document(path)``. Calling python-docx
    directly works right up until someone passes a template, which is the normal
    path in this package rather than the exception.
    """
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    path = check_readable(path)
    with tempfile.TemporaryDirectory(prefix="rp-docx-open-") as tmp:
        target = path
        if is_template(path):
            target = retype_as_document(path, Path(tmp) / f"{path.stem}.docx")
        try:
            yield docx.Document(str(target))
        except PackageNotFoundError as exc:
            raise InvalidDocxError(
                f"{path.name} could not be opened as a Word document: {exc}"
            ) from exc
        except ValueError as exc:
            raise InvalidDocxError(f"{path.name} is not a readable Word document: {exc}") from exc


def save(document: Any, output: Path) -> Path:
    """Save a python-docx ``Document``, honouring a `.dotx` output extension.

    python-docx always writes the document content type, so a file named
    ``.dotx`` would otherwise be a document wearing a template's extension —
    which Word opens as an ordinary document, silently editing what the user
    meant to keep as a template.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    if output.suffix.lower() == ".dotx":
        retype_as_template(output)
    return output


__all__ = [
    "COMMENTS_EXTENDED_PART",
    "COMMENTS_PART",
    "DOCUMENT_CONTENT_TYPE",
    "DOCUMENT_PART",
    "NS",
    "TEMPLATE_CONTENT_TYPE",
    "attr",
    "check_readable",
    "content_type",
    "is_template",
    "opened",
    "parse_part",
    "part_names",
    "qn",
    "read_part",
    "repack",
    "retype_as_document",
    "retype_as_template",
    "save",
    "xpath",
]
