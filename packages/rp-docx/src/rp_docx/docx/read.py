"""Reading Word documents: structure, text, tables, images, comments, changes.

Pure extraction. Nothing here prints, nothing imports typer, and every function
returns a pydantic model or a list of them — the CLI does all formatting.

Two things python-docx cannot do at all, so they go through
:mod:`rp_docx.ooxml` instead (spec section 7):

* **Comments** live in ``word/comments.xml``, anchored in the document by
  ``w:commentRangeStart``/``End``, with their resolved state in a separate
  ``word/commentsExtended.xml`` that may not exist.
* **Tracked changes** are ``w:ins`` and ``w:del`` wrappers. A deletion holds its
  text in ``w:delText``, *not* ``w:t`` — a reader that looks only for ``w:t``
  reports every deletion as empty and looks like it works.

All user-facing indices are 1-based.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from rp_docx import ooxml
from rp_docx.docx import runs
from rp_docx.errors import InvalidDocxError
from rp_docx.models import (
    Comment,
    CoreProperties,
    DocumentIndex,
    EmbeddedImage,
    Heading,
    Paragraph,
    Run,
    Table,
    TrackedChange,
)

#: Word's own heading style names, so a document using them reports a level even
#: when its outline level is not set explicitly.
_HEADING_PREFIX = "Heading "

_CHANGE_TYPES = {"ins": "insertion", "del": "deletion"}


# --- properties ------------------------------------------------------------


def get_properties(path: Path) -> CoreProperties:
    """The document's core properties (``docProps/core.xml``)."""
    with ooxml.opened(path) as document:
        props = document.core_properties
        return CoreProperties(
            title=props.title or None,
            author=props.author or None,
            last_modified_by=props.last_modified_by or None,
            created=props.created,
            modified=props.modified,
            revision=props.revision or None,
            category=props.category or None,
            keywords=props.keywords or None,
        )


# --- text ------------------------------------------------------------------


def _heading_level(style_name: str, paragraph: Any) -> int | None:
    """The heading level of a paragraph, or ``None`` if it is not a heading.

    Style name first, then ``w:outlineLvl``, so a house template's renamed
    heading style is still recognized as a heading — which is the whole point of
    the outline level being in the file.
    """
    if style_name.startswith(_HEADING_PREFIX):
        tail = style_name[len(_HEADING_PREFIX) :].strip()
        if tail.isdigit() and 1 <= int(tail) <= 9:
            return int(tail)
    levels = ooxml.xpath(paragraph._p, "./w:pPr/w:outlineLvl")
    if levels:
        value = ooxml.attr(levels[0], "w:val")
        if value is not None and value.isdigit() and 0 <= int(value) <= 8:
            return int(value) + 1  # w:outlineLvl is 0-based; our indices are not
    return None


def _list_level(paragraph: Any) -> int | None:
    """1-based list nesting depth, or ``None`` when the paragraph is not a list item.

    Numbering can be attached to the paragraph *or* inherited from its style,
    and python-docx's own ``add_paragraph(style="List Bullet")`` produces the
    second kind — so reading only the paragraph's own ``w:numPr`` reports every
    style-driven list as not a list at all. OOXML's ``w:ilvl`` is 0-based; every
    index this suite reports is not.
    """
    numbering = ooxml.xpath(paragraph._p, "./w:pPr/w:numPr")
    if not numbering:
        style = paragraph.style
        if style is None:
            return None
        numbering = ooxml.xpath(style.element, "./w:pPr/w:numPr")
        if not numbering:
            return None
    levels = ooxml.xpath(numbering[0], "./w:ilvl")
    if not levels:
        return 1
    value = ooxml.attr(levels[0], "w:val")
    return int(value) + 1 if value is not None and value.lstrip("-").isdigit() else 1


def _style_name(paragraph: Any) -> str:
    style = paragraph.style
    return style.name if style is not None and style.name else "Normal"


def _run_model(run: Any) -> Run:
    font = run.font
    color = None
    if font.color is not None and font.color.rgb is not None:
        color = str(font.color.rgb)
    return Run(
        text=run.text,
        bold=bool(run.bold),
        italic=bool(run.italic),
        underline=bool(run.underline),
        font=font.name,
        size_pt=font.size.pt if font.size is not None else None,
        color=color,
    )


def get_text(
    path: Path, *, style_filter: str | None = None, runs_wanted: bool = False
) -> list[Paragraph]:
    """Body paragraphs, 1-based, optionally filtered by style name.

    ``runs_wanted`` populates each paragraph's runs with their formatting. The
    index is the paragraph's position in the document, so filtering by style
    does not renumber what is left — a filtered result still says where each
    paragraph is.
    """
    with ooxml.opened(path) as document:
        result: list[Paragraph] = []
        for index, paragraph in enumerate(document.paragraphs, start=1):
            style = _style_name(paragraph)
            if style_filter is not None and style != style_filter:
                continue
            result.append(
                Paragraph(
                    index=index,
                    text=paragraph.text,
                    style=style,
                    list_level=_list_level(paragraph),
                    runs=[_run_model(run) for run in paragraph.runs] if runs_wanted else None,
                )
            )
        return result


def get_markdown(path: Path, *, embed_images: bool = False) -> str:
    """The document as Markdown, via mammoth.

    ``embed_images`` inlines images as data URIs; without it they are dropped,
    because a Markdown file referencing images that were never written is worse
    than one with none.
    """
    import tempfile

    import mammoth

    path = ooxml.check_readable(Path(path))
    convert_image = None if embed_images else mammoth.images.img_element(lambda _: {})

    with tempfile.TemporaryDirectory(prefix="rp-docx-md-") as tmp:
        # mammoth reads the package itself and, like python-docx, does not
        # expect the template content type.
        source = (
            ooxml.retype_as_document(path, Path(tmp) / f"{path.stem}.docx")
            if ooxml.is_template(path)
            else path
        )
        with open(source, "rb") as handle:
            try:
                result = mammoth.convert_to_markdown(handle, convert_image=convert_image)
            except Exception as exc:  # mammoth raises bare exceptions on bad packages
                raise InvalidDocxError(f"{path.name} could not be converted: {exc}") from exc
    return result.value


# --- tables ----------------------------------------------------------------


def _cell_text(cell: Any) -> str:
    return "\n".join(paragraph.text for paragraph in cell.paragraphs).strip()


def _iter_tables(container: Any) -> Iterator[Any]:
    """Every table, nested ones included, in document order.

    python-docx's ``document.tables`` is top level only, so a table inside a
    cell is invisible to it — and a nested table is exactly where a caller
    looking for one tends to find nothing.
    """
    for table in container.tables:
        yield table
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_tables(cell)


def _section_context(document: Any, table: Any) -> str | None:
    """Text of the nearest heading before this table, so a table found on its
    own can still be placed in the document."""
    heading: str | None = None
    for element in document.element.body.iter():
        if element.tag == ooxml.qn("w:p"):
            style = ooxml.xpath(element, "./w:pPr/w:pStyle")
            name = ooxml.attr(style[0], "w:val") if style else None
            if name and name.lower().startswith("heading"):
                heading = runs.paragraph_text(element)
        elif element is table._tbl:
            return heading
    return heading


def get_tables(path: Path, *, table_index: int | None = None) -> list[Table]:
    """Tables as row-major string data. ``table_index`` is 1-based."""
    with ooxml.opened(path) as document:
        result: list[Table] = []
        for index, table in enumerate(_iter_tables(document), start=1):
            if table_index is not None and index != table_index:
                continue
            data = [[_cell_text(cell) for cell in row.cells] for row in table.rows]
            result.append(
                Table(
                    index=index,
                    rows=len(data),
                    cols=max((len(row) for row in data), default=0),
                    data=data,
                    style=table.style.name if table.style is not None else None,
                    section_context=_section_context(document, table),
                )
            )
        return result


# --- images ----------------------------------------------------------------


def _alt_text(document: Any, rel_id: str) -> str | None:
    """Alt text for the image behind ``rel_id``.

    Word writes it to ``wp:docPr`` and Office variants also carry a
    ``pic:cNvPr``; either can exist without a description, so every candidate is
    consulted rather than the first one found being taken as the answer.
    """
    for blip in ooxml.xpath(document.element.body, ".//a:blip"):
        if ooxml.attr(blip, "r:embed") != rel_id:
            continue
        for expression in ("ancestor::w:drawing//wp:docPr", "ancestor::pic:pic//pic:cNvPr"):
            for prop in ooxml.xpath(blip, expression):
                described = prop.get("descr") or prop.get("title")
                if described and described.strip():
                    return described
    return None


def get_images(path: Path, *, output_dir: Path | None = None) -> list[EmbeddedImage]:
    """Embedded images, written to ``output_dir`` when one is given.

    Reported whether or not they are written: a caller asking what a document
    contains should not have to extract it to find out.
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    with ooxml.opened(path) as document:
        result: list[EmbeddedImage] = []
        related = document.part.rels
        for rel_id in sorted(related):
            rel = related[rel_id]
            if rel.reltype != RT.IMAGE or rel.is_external:
                continue
            image = rel.target_part
            index = len(result) + 1
            filename = Path(str(image.partname)).name
            extracted: Path | None = None
            if output_dir is not None:
                extracted = output_dir / f"image_{index:03d}_{filename}"
                extracted.write_bytes(image.blob)
            width, height = _image_size(image)
            result.append(
                EmbeddedImage(
                    index=index,
                    rel_id=rel_id,
                    filename=filename,
                    content_type=image.content_type,
                    width_px=width,
                    height_px=height,
                    alt_text=_alt_text(document, rel_id),
                    extracted_path=extracted,
                )
            )
        return result


def _image_size(image: Any) -> tuple[int | None, int | None]:
    """Pixel dimensions, or ``(None, None)`` for a format Pillow cannot read.

    An unreadable image is metadata we do not have, not a corrupt document: a
    document holding an EMF drawing is perfectly valid and its other images must
    still be reported.
    """
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image.blob)) as opened:
            return opened.width, opened.height
    except (UnidentifiedImageError, OSError, ValueError):
        return None, None


# --- comments --------------------------------------------------------------


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolved_ids(path: Path) -> set[str]:
    """``w15:paraId`` values marked done in ``commentsExtended.xml``.

    The part is optional — it only appears once someone has resolved a comment —
    so its absence means "nothing resolved", not "cannot tell".
    """
    root = ooxml.parse_part(path, ooxml.COMMENTS_EXTENDED_PART)
    if root is None:
        return set()
    done = set()
    for node in ooxml.xpath(root, ".//w15:commentEx"):
        if ooxml.attr(node, "w15:done") in ("1", "true", "on"):
            para_id = ooxml.attr(node, "w15:paraId")
            if para_id:
                done.add(para_id)
    return done


def _anchor_texts(path: Path) -> dict[str, str]:
    """Comment id → the text its range covers in the document body."""
    root = ooxml.parse_part(path, ooxml.DOCUMENT_PART)
    if root is None:
        return {}
    anchors: dict[str, str] = {}
    open_ranges: dict[str, list[str]] = {}
    for node in root.iter():
        tag = node.tag
        if tag == ooxml.qn("w:commentRangeStart"):
            identifier = ooxml.attr(node, "w:id")
            if identifier is not None:
                open_ranges[identifier] = []
        elif tag == ooxml.qn("w:commentRangeEnd"):
            identifier = ooxml.attr(node, "w:id")
            if identifier is not None and identifier in open_ranges:
                anchors[identifier] = "".join(open_ranges.pop(identifier)).strip() or None
        elif tag == ooxml.qn("w:t") and open_ranges:
            for pieces in open_ranges.values():
                pieces.append(node.text or "")
    return {key: value for key, value in anchors.items() if value}


def get_comments(path: Path) -> list[Comment]:
    """Comments with their authors, anchors, and resolved state."""
    ooxml.check_readable(Path(path))
    root = ooxml.parse_part(path, ooxml.COMMENTS_PART)
    if root is None:
        return []
    resolved = _resolved_ids(path)
    anchors = _anchor_texts(path)
    result: list[Comment] = []
    for node in ooxml.xpath(root, ".//w:comment"):
        identifier = ooxml.attr(node, "w:id") or ""
        paragraphs = ooxml.xpath(node, "./w:p")
        para_id = ooxml.attr(paragraphs[0], "w14:paraId") if paragraphs else None
        result.append(
            Comment(
                id=identifier,
                author=ooxml.attr(node, "w:author") or "",
                initials=ooxml.attr(node, "w:initials"),
                date=_parse_date(ooxml.attr(node, "w:date")),
                text="\n".join(runs.paragraph_text(p) for p in paragraphs).strip(),
                anchor_text=anchors.get(identifier),
                para_id=para_id,
                resolved=para_id in resolved if para_id else False,
            )
        )
    return result


# --- tracked changes -------------------------------------------------------


def _revision_text(node: Any) -> str:
    """The text a revision carries.

    ``w:delText`` for deletions, ``w:t`` for insertions. Reading only ``w:t``
    reports every deletion as empty — and looks like it works.
    """
    pieces = []
    for child in node.iter():
        if child.tag in (ooxml.qn("w:t"), ooxml.qn("w:delText")):
            pieces.append(child.text or "")
    return "".join(pieces)


def get_tracked_changes(path: Path) -> list[TrackedChange]:
    """Insertions, deletions, and paragraph-mark format changes, in document order."""
    ooxml.check_readable(Path(path))
    root = ooxml.parse_part(path, ooxml.DOCUMENT_PART)
    if root is None:
        return []

    paragraph_of: dict[Any, int] = {}
    for index, paragraph in enumerate(ooxml.xpath(root, ".//w:p"), start=1):
        paragraph_of[paragraph] = index

    result: list[TrackedChange] = []
    for node in ooxml.xpath(root, ".//w:ins | .//w:del | .//w:rPrChange | .//w:pPrChange"):
        local = node.tag.rsplit("}", 1)[-1]
        # A w:ins inside a paragraph-mark's run properties is not an inserted
        # run: it records that the paragraph mark itself was inserted, which
        # Word shows as a formatting change rather than as new text.
        in_mark_properties = bool(ooxml.xpath(node, "ancestor::w:rPr"))
        change_type = (
            "format" if local.endswith("Change") or in_mark_properties else _CHANGE_TYPES[local]
        )
        result.append(
            TrackedChange(
                id=ooxml.attr(node, "w:id") or "",
                type=change_type,
                author=ooxml.attr(node, "w:author") or "",
                date=_parse_date(ooxml.attr(node, "w:date")),
                text=_revision_text(node),
                paragraph_index=_paragraph_index(node, paragraph_of),
            )
        )
    return result


def _paragraph_index(node: Any, paragraph_of: dict[Any, int]) -> int:
    ancestor = node.getparent()
    while ancestor is not None:
        if ancestor.tag == ooxml.qn("w:p") and ancestor in paragraph_of:
            return paragraph_of[ancestor]
        ancestor = ancestor.getparent()
    return 0


# --- index -----------------------------------------------------------------


def get_index(path: Path) -> DocumentIndex:
    """Everything a caller needs to decide what to read next.

    The default command, and the one an agent runs first — so it counts
    everything cheaply rather than making eight calls necessary to find out
    whether a document has comments.
    """
    path = ooxml.check_readable(Path(path))
    parts = ooxml.part_names(path)
    has_headers_footers = any(
        name.startswith(("word/header", "word/footer")) and name.endswith(".xml") for name in parts
    )

    with ooxml.opened(path) as document:
        paragraphs = document.paragraphs
        headings: list[Heading] = []
        styles_used: list[str] = []
        words = 0
        for index, paragraph in enumerate(paragraphs, start=1):
            style = _style_name(paragraph)
            if style not in styles_used:
                styles_used.append(style)
            words += len(paragraph.text.split())
            level = _heading_level(style, paragraph)
            if level is not None and paragraph.text.strip():
                headings.append(
                    Heading(index=index, level=level, text=paragraph.text.strip(), style=style)
                )
        table_count = sum(1 for _ in _iter_tables(document))
        section_count = len(document.sections)
        properties = CoreProperties(
            title=document.core_properties.title or None,
            author=document.core_properties.author or None,
            last_modified_by=document.core_properties.last_modified_by or None,
            created=document.core_properties.created,
            modified=document.core_properties.modified,
            revision=document.core_properties.revision or None,
            category=document.core_properties.category or None,
            keywords=document.core_properties.keywords or None,
        )

    return DocumentIndex(
        path=path,
        paragraph_count=len(paragraphs),
        word_count=words,
        section_count=section_count,
        table_count=table_count,
        image_count=len(get_images(path)),
        comment_count=len(get_comments(path)),
        tracked_change_count=len(get_tracked_changes(path)),
        has_headers_footers=has_headers_footers,
        styles_used=sorted(styles_used),
        headings=headings,
        core_properties=properties,
    )


__all__ = [
    "get_comments",
    "get_images",
    "get_index",
    "get_markdown",
    "get_properties",
    "get_tables",
    "get_text",
    "get_tracked_changes",
]
