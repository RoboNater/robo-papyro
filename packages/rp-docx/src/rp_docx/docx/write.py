"""Creating and editing Word documents.

Everything here builds on two things: the resolved template's
:class:`~rp_docx.models.StyleMap` (spec section 5) and
:mod:`rp_docx.docx.runs` (spec section 6). Neither is optional — a document
built with the wrong styles looks right until review, and a replacement that
only checks one run at a time silently finds nothing.

**Markdown is parsed by hand rather than by a library, but no longer here.**
Spec section 9: the block grammar needed is small, and no markdown library on the
approved license list covers it, so a vetted dependency is the wrong trade for two
hundred lines of parsing. That parser now lives in :mod:`rp_core.markdown`, moved
there by rp-pptx-spec section 12 step 2 once a second leaf needed the same
grammar — it never contained an OOXML identifier, so nothing about it was
Word-specific. What stays here is the *renderer* over the shared AST, which is
the half that knows about styles and ``w:`` elements.

:func:`parse_markdown` and :func:`parse_inline` are re-exported so this module's
public surface is unchanged.

**No in-place mutation unless asked.** Every function takes an ``output``; when
it is ``None`` the change is written back to the source, and it is the CLI that
insists on ``-o`` or an explicit ``--in-place`` before that can happen.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal

from rp_core.markdown import Block, Span, parse_inline, parse_markdown
from rp_docx import ooxml, templates
from rp_docx.docx import runs as runs_module
from rp_docx.errors import RpDocxError
from rp_docx.models import CoreProperties, ReplaceResult, StyleMap

#: Page sizes ``create`` knows by name, in twips.
PAGE_SIZES: dict[str, tuple[int, int]] = {
    "letter": (12240, 15840),
    "a4": (11906, 16838),
}

#: Font applied to inline code spans. A *character style* would be the tidier
#: mechanism, but Word ships no built-in one and requiring the template to
#: define it would make ``**bold** and `code`` fail on Word's own defaults.
CODE_FONT = "Consolas"


# --- markdown, parsed --------------------------------------------------------


# --- markdown, rendered ------------------------------------------------------


def _add_spans(document: Any, paragraph: Any, spans: list[Span]) -> None:
    for span in spans:
        if span.href:
            _add_hyperlink(document, paragraph, span)
            continue
        run = paragraph.add_run(span.text)
        run.bold = span.bold or None
        run.italic = span.italic or None
        if span.code:
            run.font.name = CODE_FONT


def _add_hyperlink(document: Any, paragraph: Any, span: Span) -> None:
    """A real ``w:hyperlink`` with an external relationship.

    python-docx has no hyperlink API, so this builds the element. Written as
    markup rather than as blue underlined text, because a document whose links
    only *look* like links is exactly the kind of near-miss that survives review.
    """
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn as docx_qn

    rel_id = document.part.relate_to(span.href, RT.HYPERLINK, is_external=True)
    run = paragraph.add_run(span.text)
    run.font.underline = True
    try:
        run.style = document.styles["Hyperlink"]
    except KeyError:
        pass  # a template without the built-in Hyperlink style still gets a link
    link = paragraph._p.makeelement(docx_qn("w:hyperlink"), {})
    link.set(ooxml.qn("r:id"), rel_id)
    paragraph._p.replace(run._r, link)
    link.append(run._r)


def _add_rule(document: Any, style: str) -> None:
    """A horizontal rule, as a bottom border on an empty paragraph — which is
    what Word itself produces for one."""
    from lxml import etree

    paragraph = document.add_paragraph(style=style)
    properties = paragraph._p.get_or_add_pPr()
    borders = etree.SubElement(properties, ooxml.qn("w:pBdr"))
    bottom = etree.SubElement(borders, ooxml.qn("w:bottom"))
    for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "auto")):
        bottom.set(ooxml.qn(key), value)


def _add_table(document: Any, block: Block, style_name: str) -> None:
    """A GFM pipe table, with explicit widths in twips.

    Percentage widths render inconsistently outside Word, and an omitted or
    mis-specified shading pattern renders black in some viewers (spec section 9),
    so widths are absolute and no shading is applied at all.
    """
    from docx.shared import Twips

    columns = max(len(row) for row in block.rows)
    table = document.add_table(rows=len(block.rows), cols=columns)
    table.style = document.styles[style_name]
    usable = document.sections[0].page_width.twips - (
        document.sections[0].left_margin.twips + document.sections[0].right_margin.twips
    )
    width = Twips(max(1, usable // columns))
    table.autofit = False
    for row_index, row in enumerate(block.rows):
        for column_index in range(columns):
            cell = table.cell(row_index, column_index)
            cell.width = width
            value = row[column_index] if column_index < len(row) else ""
            cell.paragraphs[0].text = ""
            _add_spans(document, cell.paragraphs[0], parse_inline(value))
        if row_index == 0:
            for column_index in range(columns):
                for run in table.cell(0, column_index).paragraphs[0].runs:
                    run.bold = True


def render_markdown(document: Any, markdown: str, stylemap: StyleMap) -> None:
    """Append ``markdown`` to ``document`` using ``stylemap``'s style names.

    Every style is checked at the point it is first needed, and a missing one
    raises :class:`~rp_docx.errors.TemplateError` naming it (spec section 5.1).
    Checked lazily rather than up front because Word defines no code style at
    all, so an eager check would reject its own default template for a role most
    documents never use.
    """
    heading_roles = {1: "h1", 2: "h2", 3: "h3", 4: "h4"}
    for block in parse_markdown(markdown):
        if block.kind == "heading":
            role = heading_roles[block.level]
            style = templates.require_style(document, role, getattr(stylemap, role))
            paragraph = document.add_paragraph(style=style)
            _add_spans(document, paragraph, parse_inline(block.text))
        elif block.kind == "paragraph":
            style = templates.require_style(document, "body", stylemap.body)
            paragraph = document.add_paragraph(style=style)
            _add_spans(document, paragraph, parse_inline(block.text))
        elif block.kind in ("bullet", "numbered"):
            role = "bullet" if block.kind == "bullet" else "numbered"
            style = templates.require_style(document, role, getattr(stylemap, role))
            paragraph = document.add_paragraph(style=style)
            paragraph.paragraph_format.left_indent = _indent(block.level)
            _add_spans(document, paragraph, parse_inline(block.text))
        elif block.kind == "table":
            style = templates.require_style(document, "table", stylemap.table, style_type="table")
            _add_table(document, block, style)
        elif block.kind == "code":
            # The one role a stylemap may leave unset, because Word ships no
            # code style. Named but missing is still an error; unnamed means the
            # template has none, and body-plus-monospace is what it can express.
            style = (
                templates.require_style(document, "code", stylemap.code)
                if stylemap.code
                else templates.require_style(document, "body", stylemap.body)
            )
            for line in block.lines:
                paragraph = document.add_paragraph(style=style)
                paragraph.add_run(line).font.name = CODE_FONT
        elif block.kind == "rule":
            _add_rule(document, templates.require_style(document, "body", stylemap.body))


def _indent(level: int):
    from docx.shared import Inches

    return Inches(0.25 * max(0, level - 1))


# --- creating ----------------------------------------------------------------


def _apply_page_size(document: Any, page_size: str) -> None:
    from docx.shared import Twips

    try:
        width, height = PAGE_SIZES[page_size.lower()]
    except KeyError as exc:
        known = ", ".join(sorted(PAGE_SIZES))
        raise RpDocxError(f"Unknown page size {page_size!r}; choose from {known}.") from exc
    for section in document.sections:
        section.page_width, section.page_height = Twips(width), Twips(height)


def create(
    output: Path,
    *,
    markdown: str | None = None,
    template: str | Path | None = None,
    title: str | None = None,
    page_size: Literal["letter", "a4"] = "letter",
) -> Path:
    """Build a document from markdown, on a template.

    The template's body is kept, not cleared: a letterhead template's boilerplate
    is the reason it exists, and Word's own "new from template" behaves the same
    way. Markdown is appended after it.

    **A supplied template wins on page size** (spec section 9). ``page_size``
    only applies when no template was named, because a house template that is A4
    is A4 whatever the default says.
    """
    resolved = templates.resolve_template(template)
    stylemap = templates.load_stylemap(resolved)
    with ooxml.opened(resolved) as document:
        if template is None:
            _apply_page_size(document, page_size)
        if title is not None:
            document.core_properties.title = title
        if markdown:
            render_markdown(document, markdown, stylemap)
        return ooxml.save(document, Path(output))


def append_markdown(path: Path, markdown: str, *, output: Path | None = None) -> Path:
    """Append markdown to an existing document, using its own styles.

    The stylemap comes from the document being appended to, so text added to a
    house-styled document is house-styled too.
    """
    path = ooxml.check_readable(Path(path))
    stylemap = templates.load_stylemap(path)
    with ooxml.opened(path) as document:
        render_markdown(document, markdown, stylemap)
        return ooxml.save(document, Path(output) if output is not None else path)


def set_properties(path: Path, props: CoreProperties, *, output: Path | None = None) -> Path:
    """Set the core properties given, leaving unset ones alone.

    ``None`` means "do not touch", not "clear": clearing an author because the
    caller only wanted to change the title would be a surprise no CLI flag asked
    for.
    """
    path = ooxml.check_readable(Path(path))
    with ooxml.opened(path) as document:
        core = document.core_properties
        for field_name in (
            "title",
            "author",
            "last_modified_by",
            "created",
            "modified",
            "revision",
            "category",
            "keywords",
        ):
            value = getattr(props, field_name)
            if value is not None:
                setattr(core, field_name, value)
        return ooxml.save(document, Path(output) if output is not None else path)


# --- replacing ---------------------------------------------------------------


def revisable_parts(path: Path) -> list[tuple[str, str]]:
    """(part name, location label) for every part that can hold body text.

    Body-only replacement is the classic silent bug (spec section 6), so this is
    the list every text-editing operation walks: the document, each header and
    footer, and footnotes and endnotes when they exist.
    """
    parts: list[tuple[str, str]] = []
    for name in ooxml.part_names(path):
        if name == ooxml.DOCUMENT_PART:
            parts.append((name, "body"))
        elif name.startswith("word/header") and name.endswith(".xml"):
            parts.append((name, f"header:{_part_number(name)}"))
        elif name.startswith("word/footer") and name.endswith(".xml"):
            parts.append((name, f"footer:{_part_number(name)}"))
        elif name in ("word/footnotes.xml", "word/endnotes.xml"):
            parts.append((name, Path(name).stem))
    return parts


def _part_number(name: str) -> str:
    digits = "".join(ch for ch in Path(name).stem if ch.isdigit())
    return digits or "1"


def _write_parts(source: Path, output: Path | None, changed: dict[str, Any]) -> Path:
    """Serialize modified part roots back into the package."""
    from lxml import etree

    replacements = {
        name: etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        for name, root in changed.items()
    }
    target = Path(output) if output is not None else source
    if target == source:
        # Never rewrite the package in place while reading it: stage beside it
        # and move, so an interrupted write cannot leave a truncated document.
        staged = source.with_name(f".{source.name}.rp-docx-tmp")
        ooxml.repack(source, staged, replacements)
        shutil.move(str(staged), str(source))
        return source
    return ooxml.repack(source, target, replacements)


def replace_text(
    path: Path,
    replacements: dict[str, str],
    *,
    output: Path | None = None,
    match_case: bool = True,
    preserve_formatting: bool = True,
) -> ReplaceResult:
    """Replace text everywhere it appears, across run boundaries.

    Walks the body, table cells, text boxes, every header and footer, and
    footnotes and endnotes. The replacement inherits the formatting of the run
    holding the match's start; ``preserve_formatting=False`` strips that run's
    direct formatting instead.
    """
    path = ooxml.check_readable(Path(path))
    counts: dict[str, int] = {}
    locations: list[str] = []
    changed: dict[str, Any] = {}

    for name, location in revisable_parts(path):
        root = ooxml.parse_part(path, name)
        if root is None:
            continue
        part_counts, part_locations = runs_module.replace_in_part(
            root,
            replacements,
            location=location,
            ignore_case=not match_case,
            preserve_formatting=preserve_formatting,
        )
        if not part_counts:
            continue
        changed[name] = root
        for key, count in part_counts.items():
            counts[key] = counts.get(key, 0) + count
        for where in part_locations:
            if where not in locations:
                locations.append(where)

    written = _write_parts(path, output, changed) if changed else _copy_unchanged(path, output)
    # Keys that matched nothing still appear, with a count of zero: a caller
    # checking whether its replacement landed should not have to know whether a
    # missing key means "absent" or "not attempted".
    for key in replacements:
        counts.setdefault(key, 0)
    return ReplaceResult(output=written, replacements=counts, locations=locations)


def _copy_unchanged(path: Path, output: Path | None) -> Path:
    if output is None or Path(output) == path:
        return path
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return target


# --- tracked changes ---------------------------------------------------------


def _unwrap(node: Any) -> None:
    """Replace ``node`` with its children, in place, keeping document order.

    Revision wrappers hold only elements — never text of their own — so nothing
    is lost by promoting the children and dropping the wrapper.
    """
    parent = node.getparent()
    if parent is None:
        return
    position = list(parent).index(node)
    for offset, child in enumerate(list(node)):
        parent.insert(position + offset, child)
    parent.remove(node)


def _drop(node: Any) -> None:
    parent = node.getparent()
    if parent is not None:
        parent.remove(node)


def _deltext_to_text(node: Any) -> None:
    for child in node.iter(ooxml.qn("w:delText")):
        child.tag = ooxml.qn("w:t")


def _wanted(node: Any, authors: list[str] | None) -> bool:
    if authors is None:
        return True
    return (ooxml.attr(node, "w:author") or "") in authors


def _resolve_revisions(root: Any, *, accept: bool, authors: list[str] | None) -> int:
    """Apply or undo every revision in one part. Returns how many were handled.

    Order matters: revisions nest (a deletion inside an insertion), so the
    deepest are resolved first and a wrapper is never unwrapped out from under a
    node still waiting its turn.
    """
    handled = 0
    nodes = ooxml.xpath(root, ".//w:ins | .//w:del | .//w:rPrChange | .//w:pPrChange")
    for node in sorted(nodes, key=_depth, reverse=True):
        if not _wanted(node, authors):
            continue
        local = node.tag.rsplit("}", 1)[-1]
        if local.endswith("Change"):
            _resolve_property_change(node, accept=accept)
        elif local == "ins":
            # A w:ins inside run properties marks an inserted paragraph mark
            # rather than inserted text; it has no children to promote.
            if ooxml.xpath(node, "ancestor::w:rPr"):
                _drop(node)
            elif accept:
                _unwrap(node)
            else:
                _drop(node)
        elif accept:
            _drop(node)
        else:
            _deltext_to_text(node)
            _unwrap(node)
        handled += 1
    return handled


def _depth(node: Any) -> int:
    depth = 0
    parent = node.getparent()
    while parent is not None:
        depth += 1
        parent = parent.getparent()
    return depth


def _resolve_property_change(node: Any, *, accept: bool) -> None:
    """``w:rPrChange``/``w:pPrChange`` hold the properties as they were *before*
    the change, so rejecting one means restoring its contents over the current
    ones. Accepting means keeping what is there and discarding the record."""
    parent = node.getparent()
    if parent is None:
        return
    if accept:
        _drop(node)
        return
    for child in reversed(list(node)):
        if child.tag in (ooxml.qn("w:rPr"), ooxml.qn("w:pPr")):
            for existing in parent.findall(child.tag):
                parent.remove(existing)
            parent.insert(0, child)
    _drop(node)


def _apply_revisions(
    path: Path, output: Path | None, *, accept: bool, authors: list[str] | None
) -> Path:
    path = ooxml.check_readable(Path(path))
    changed: dict[str, Any] = {}
    for name, _ in revisable_parts(path):
        root = ooxml.parse_part(path, name)
        if root is None:
            continue
        if _resolve_revisions(root, accept=accept, authors=authors):
            changed[name] = root
    if not changed:
        return _copy_unchanged(path, output)
    return _write_parts(path, output, changed)


def accept_changes(
    path: Path, *, output: Path | None = None, authors: list[str] | None = None
) -> Path:
    """Accept tracked changes: promote insertions, discard deletions.

    ``authors`` narrows it to changes by the named authors, leaving everyone
    else's tracked.
    """
    return _apply_revisions(path, output, accept=True, authors=authors)


def reject_changes(
    path: Path, *, output: Path | None = None, authors: list[str] | None = None
) -> Path:
    """Reject tracked changes: discard insertions, restore deletions.

    Restoring a deletion means converting its ``w:delText`` back to ``w:t`` —
    text left as ``w:delText`` outside a ``w:del`` is invisible in Word, which
    looks exactly like the deletion having been accepted instead.
    """
    return _apply_revisions(path, output, accept=False, authors=authors)


__all__ = [
    "Block",
    "Span",
    "accept_changes",
    "append_markdown",
    "create",
    "parse_inline",
    "parse_markdown",
    "reject_changes",
    "render_markdown",
    "replace_text",
    "revisable_parts",
    "set_properties",
]
