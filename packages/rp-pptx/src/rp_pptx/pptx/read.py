"""Reading presentations: index, text, tables, images, notes, comments, charts.

Every function returns a pydantic model or a list of them, takes and returns
``pathlib.Path``, and never prints. Indices the user sees are 1-based
throughout — slides, tables, images, charts — and **counted across the deck**,
not across the selection, so ``--slides 3`` reports the same image number that a
whole-deck read does. An index that renumbers when you filter is not an index.

``slides`` accepts the ``rp_core.ranges`` spec on every read that returns
per-slide content (spec section 4): asking "what tables are on slide 12" should
not mean fetching all ninety slides' worth and filtering afterwards. Only
:func:`get_index` and :func:`get_properties` are whole-deck by nature.

**Placeholder prompt text is not content** (section 9). An empty placeholder
shows "Click to add title", but that string lives in the layout, not the slide;
python-pptx returns ``""`` for the slide-side frame, which is what these reads
go through, so it never leaks into output.
"""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from rp_core.ranges import parse_range_spec
from rp_pptx import ooxml
from rp_pptx.errors import UnsupportedFeatureError
from rp_pptx.models import (
    ChartRef,
    ChartSeries,
    Comment,
    CoreProperties,
    EmbeddedImage,
    MergeSpan,
    Paragraph,
    PresentationIndex,
    Run,
    SlideText,
    SlideTitle,
    SpeakerNotes,
    Table,
)
from rp_pptx.ooxml import opened
from rp_pptx.pptx import shapes as shape_tools


def _selected(spec: str, count: int) -> list[int]:
    return parse_range_spec(spec, count, noun="slide")


def _ratio(width: int, height: int) -> str:
    """``"16:9"``, ``"4:3"``, or the reduced ratio for anything else."""
    if not height:
        return "0:0"
    value = width / height
    if abs(value - 16 / 9) < 0.02:
        return "16:9"
    if abs(value - 4 / 3) < 0.02:
        return "4:3"
    reduced = Fraction(width, height).limit_denominator(100)
    return f"{reduced.numerator}:{reduced.denominator}"


def _title_of(slide: Any) -> str | None:
    """The slide's title, or ``None`` when it has no title placeholder."""
    title = slide.shapes.title
    if title is None:
        return None
    text = title.text_frame.text.strip()
    return text or None


def _colour(font: Any) -> str | None:
    try:
        return str(font.color.rgb) if font.color and font.color.rgb else None
    except (AttributeError, TypeError, ValueError):
        # A theme colour has no .rgb, and asking raises rather than returning
        # None. Reporting nothing is better than reporting a wrong hex.
        return None


def _alt_text(shape: Any) -> str | None:
    """A shape's alt text — the ``descr`` attribute, not its name.

    A shape always has a name ("Picture 7"), so returning that would make the
    field never null and never useful; ``descr`` is what a screen reader reads
    and what a user actually typed.
    """
    try:
        value = shape._element._nvXxPr.cNvPr.get("descr")
    except AttributeError:
        return None
    return value or None


def get_properties(path: Path) -> CoreProperties:
    with opened(path) as presentation:
        source = presentation.core_properties
        return CoreProperties(
            title=source.title or None,
            author=source.author or None,
            last_modified_by=source.last_modified_by or None,
            created=source.created,
            modified=source.modified,
            revision=source.revision,
            category=source.category or None,
            keywords=source.keywords or None,
        )


def get_text(path: Path, *, slides: str = "all", runs: bool = False) -> list[SlideText]:
    """Every paragraph on the selected slides, optionally down to runs."""
    result: list[SlideText] = []
    with opened(path) as presentation:
        for number in _selected(slides, len(presentation.slides)):
            slide = presentation.slides[number - 1]
            paragraphs: list[Paragraph] = []
            for shape in shape_tools.walk(slide.shapes):
                # Shape text only. Table cells are text too, but they belong to
                # get_tables, where the reader also learns the shape of the grid;
                # reporting them here as well would double every cell in
                # get_markdown and in any word count built on this.
                if getattr(shape, "has_text_frame", False):
                    for paragraph in shape.text_frame.paragraphs:
                        paragraphs.append(
                            Paragraph(
                                text=paragraph.text,
                                level=paragraph.level,
                                runs=[
                                    Run(
                                        text=run.text,
                                        bold=bool(run.font.bold),
                                        italic=bool(run.font.italic),
                                        underline=bool(run.font.underline),
                                        font=run.font.name,
                                        # The nominal size, which is what the file
                                        # says. A normAutofit fontScale changes what
                                        # PowerPoint draws, and guessing at the
                                        # effective size would be a different number
                                        # from any the document contains (section 9).
                                        size_pt=run.font.size.pt if run.font.size else None,
                                        color=_colour(run.font),
                                    )
                                    for run in paragraph.runs
                                ]
                                if runs
                                else None,
                            )
                        )
            result.append(
                SlideText(
                    index=number,
                    layout=slide.slide_layout.name,
                    title=_title_of(slide),
                    paragraphs=paragraphs,
                )
            )
    return result


def _merges(table: Any) -> list[MergeSpan]:
    spans: list[MergeSpan] = []
    for row_index, row in enumerate(table.rows, start=1):
        for column_index, cell in enumerate(row.cells, start=1):
            if cell.is_merge_origin:
                spans.append(
                    MergeSpan(
                        row=row_index,
                        col=column_index,
                        row_span=cell.span_height,
                        col_span=cell.span_width,
                    )
                )
    return spans


def get_tables(path: Path, *, slides: str = "all", table_index: int | None = None) -> list[Table]:
    """Tables on the selected slides, numbered across the whole deck.

    A merged region reports its value once, on the origin cell; the cells it
    swallowed read as empty. python-pptx concatenates the merged cells' text
    onto the origin, so the origin is read from its own first cell rather than
    from the merged view.
    """
    result: list[Table] = []
    index = 0
    with opened(path) as presentation:
        wanted = set(_selected(slides, len(presentation.slides)))
        for slide_number, slide in enumerate(presentation.slides, start=1):
            for shape in shape_tools.walk(slide.shapes):
                if not getattr(shape, "has_table", False):
                    continue
                index += 1
                if slide_number not in wanted:
                    continue
                if table_index is not None and index != table_index:
                    continue
                table = shape.table
                data = [
                    ["" if cell.is_spanned else cell.text for cell in row.cells]
                    for row in table.rows
                ]
                result.append(
                    Table(
                        index=index,
                        slide_index=slide_number,
                        rows=len(table.rows),
                        cols=len(table.columns),
                        data=data,
                        merges=_merges(table),
                    )
                )
    return result


def get_images(
    path: Path, *, slides: str = "all", output_dir: Path | None = None
) -> list[EmbeddedImage]:
    """Pictures on the selected slides, numbered across the whole deck.

    Legacy decks embed WMF/EMF metafiles Pillow cannot parse. Those report
    ``width_px``/``height_px`` as ``None``; extraction still writes the bytes,
    and nothing raises (section 9).
    """
    result: list[EmbeddedImage] = []
    index = 0
    directory = Path(output_dir) if output_dir else None
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
    with opened(path) as presentation:
        wanted = set(_selected(slides, len(presentation.slides)))
        for slide_number, slide in enumerate(presentation.slides, start=1):
            for shape in shape_tools.walk(slide.shapes):
                if not shape_tools.is_picture(shape):
                    continue
                index += 1
                if slide_number not in wanted:
                    continue
                image = shape.image
                extracted = None
                if directory:
                    extracted = directory / f"image-{index}.{image.ext}"
                    extracted.write_bytes(image.blob)
                width = height = None
                try:
                    with Image.open(BytesIO(image.blob)) as opened_image:
                        width, height = opened_image.size
                except (UnidentifiedImageError, OSError, ValueError):
                    pass
                result.append(
                    EmbeddedImage(
                        index=index,
                        slide_index=slide_number,
                        rel_id=shape._element.blipFill.blip.rEmbed,
                        filename=image.filename or f"image-{index}.{image.ext}",
                        content_type=image.content_type,
                        width_px=width,
                        height_px=height,
                        alt_text=_alt_text(shape),
                        extracted_path=extracted,
                    )
                )
    return result


def get_notes(path: Path, *, slides: str = "all") -> list[SpeakerNotes]:
    """Speaker notes for the selected slides, skipping slides that have none.

    ``has_notes_slide`` is checked first because reading ``notes_slide``
    directly *creates* the notes part on any slide lacking one — harmless for a
    read that is never saved, wasteful on a ninety-slide deck, and a trap for
    anything that later saves the same object.
    """
    result: list[SpeakerNotes] = []
    with opened(path) as presentation:
        for number in _selected(slides, len(presentation.slides)):
            slide = presentation.slides[number - 1]
            if not slide.has_notes_slide:
                continue
            text = slide.notes_slide.notes_text_frame.text.strip()
            if text:
                result.append(SpeakerNotes(slide_index=number, text=text))
    return result


def get_charts(path: Path, *, slides: str = "all") -> list[ChartRef]:
    """Charts on the selected slides, numbered across the whole deck.

    Read defensively (section 9): anything python-pptx cannot model reports its
    type and title with ``data_available: false`` rather than raising. One
    exotic chart must not sink the whole read.
    """
    result: list[ChartRef] = []
    index = 0
    with opened(path) as presentation:
        wanted = set(_selected(slides, len(presentation.slides)))
        for slide_number, slide in enumerate(presentation.slides, start=1):
            for shape in shape_tools.walk(slide.shapes):
                if not getattr(shape, "has_chart", False):
                    continue
                index += 1
                if slide_number not in wanted:
                    continue
                chart = shape.chart
                title = None
                try:
                    if chart.has_title:
                        title = chart.chart_title.text_frame.text or None
                except (AttributeError, TypeError, ValueError):
                    title = None
                try:
                    series = [
                        ChartSeries(
                            name=str(item.name) if item.name else None,
                            values=[
                                float(value) if value is not None else None for value in item.values
                            ],
                        )
                        for item in chart.series
                    ]
                    categories = [str(category) for category in chart.plots[0].categories]
                    available = True
                except (AttributeError, TypeError, ValueError, IndexError):
                    series, categories, available = [], [], False
                result.append(
                    ChartRef(
                        index=index,
                        slide_index=slide_number,
                        chart_type=str(chart.chart_type),
                        title=title,
                        categories=categories,
                        series=series,
                        data_available=available,
                    )
                )
    return result


# --- comments (spec section 7) ------------------------------------------------


def _classic_authors(path: Path) -> dict[str, tuple[str, str | None]]:
    """``authorId`` → (name, initials) from ``ppt/commentAuthors.xml``."""
    root = ooxml.parse_part(path, ooxml.CLASSIC_AUTHORS_PART)
    if root is None:
        return {}
    authors = {}
    for author in ooxml.xpath(root, "./p:cmAuthor"):
        authors[author.get("id")] = (author.get("name") or "", author.get("initials") or None)
    return authors


def _classic_comment_parts(path: Path) -> dict[int, list[str]]:
    """1-based presentation slide number → its classic comment parts."""
    return {
        number: [
            part
            for part, content_type in attached
            if content_type == ooxml.CLASSIC_COMMENT_CONTENT_TYPE
        ]
        for number, attached in ooxml.comment_parts_by_slide(path).items()
    }


def _modern_comment_slides(path: Path) -> list[int]:
    """Slides carrying a modern threaded-comment part, in presentation order.

    May be empty on a deck that *does* carry modern parts — a part orphaned from
    its slide, or one attached through a relationship type this package has
    never seen a real example of, is still unreadable. So callers must treat
    :func:`~rp_pptx.ooxml.has_modern_comments` as the authority on presence and
    this only as the authority on *where*.
    """
    return sorted(
        number
        for number, attached in ooxml.comment_parts_by_slide(path).items()
        if any(content_type == ooxml.MODERN_COMMENT_CONTENT_TYPE for _, content_type in attached)
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def get_comments(path: Path, *, slides: str = "all") -> list[Comment]:
    """Classic comments on the selected slides.

    **Modern threaded comments are deferred** (section 7), and the deferral is an
    error rather than a silence: a deck carrying modern comment parts raises
    :class:`~rp_pptx.errors.UnsupportedFeatureError` naming the slides that carry
    them. That applies to mixed classic/modern decks too — partial results are
    sacrificed for an error that cannot be mistaken for a complete read. Returning
    ``[]`` would be indistinguishable from "this deck has no comments", which is
    the one outcome section 7 forbids.
    """
    # Presence is decided package-wide, placement only afterwards. A modern part
    # this reader cannot attribute to a slide is still a modern part it cannot
    # read, and falling through to a classic-only result would be the silent
    # partial answer section 7 forbids — so the check is on presence, and the
    # slide list only sharpens the message.
    if ooxml.has_modern_comments(path):
        located = _modern_comment_slides(path)
        where = (
            f"on slide(s) {', '.join(str(number) for number in located)}"
            if located
            else "somewhere in the package (they could not be attributed to a slide)"
        )
        error = UnsupportedFeatureError(
            f"{Path(path).name} carries modern threaded comments {where}, "
            "which this version cannot read."
        )
        error.hint = (
            "Modern-comment support is deferred until a PowerPoint-authored reference "
            "deck can be inspected (rp-pptx-spec section 7); see "
            "dev-notes/status-robo-papyro-phase-2.5.md. Classic comments are read normally."
        )
        raise error

    authors = _classic_authors(path)
    parts = _classic_comment_parts(path)
    result: list[Comment] = []
    with opened(path) as presentation:
        wanted = set(_selected(slides, len(presentation.slides)))
    for slide_number in sorted(parts):
        if slide_number not in wanted:
            continue
        for part in parts[slide_number]:
            root = ooxml.parse_part(path, part)
            if root is None:
                continue
            for comment in ooxml.xpath(root, "./p:cm"):
                author_id = comment.get("authorId")
                name, initials = authors.get(author_id, ("", None))
                text_nodes = ooxml.xpath(comment, "./p:text")
                result.append(
                    Comment(
                        id=comment.get("idx") or "",
                        author=name,
                        initials=initials,
                        date=_parse_date(comment.get("dt")),
                        text=text_nodes[0].text or "" if text_nodes else "",
                        slide_index=slide_number,
                        # Classic comments do not thread; section 7 normalizes both
                        # generations onto one model, so this is None throughout.
                        parent_id=None,
                    )
                )
    return result


def _comment_count(path: Path) -> int | None:
    """Classic comments in the deck, or ``None`` when that would be a lie.

    Section 7: an index must never refuse a readable deck, so this stays total —
    but a confidently wrong classic-only count over a deck that also has modern
    comments is worse than admitting ignorance. ``None`` is the suite's
    established null-means-unknown shape (rp-pdf's ``has_text: bool | None``).
    """
    if ooxml.has_modern_comments(path):
        return None
    total = 0
    for parts in _classic_comment_parts(path).values():
        for name in parts:
            root = ooxml.parse_part(path, name)
            if root is not None:
                total += len(ooxml.xpath(root, "./p:cm"))
    return total


def get_index(path: Path) -> PresentationIndex:
    """A whole-deck overview. Total by contract — it never refuses a readable deck."""
    with opened(path) as presentation:
        titles = [
            SlideTitle(index=number, layout=slide.slide_layout.name, title=_title_of(slide))
            for number, slide in enumerate(presentation.slides, start=1)
        ]
        notes_count = 0
        table_count = image_count = chart_count = 0
        for slide in presentation.slides:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                notes_count += 1
            for shape in shape_tools.walk(slide.shapes):
                table_count += bool(getattr(shape, "has_table", False))
                chart_count += bool(getattr(shape, "has_chart", False))
                image_count += shape_tools.is_picture(shape)

        return PresentationIndex(
            path=Path(path),
            slide_count=len(presentation.slides),
            slide_width_emu=presentation.slide_width,
            slide_height_emu=presentation.slide_height,
            aspect_ratio=_ratio(presentation.slide_width, presentation.slide_height),
            master_count=len(presentation.slide_masters),
            layout_names=[
                layout.name
                for master in presentation.slide_masters
                for layout in master.slide_layouts
            ],
            image_count=image_count,
            table_count=table_count,
            chart_count=chart_count,
            notes_count=notes_count,
            comment_count=_comment_count(path),
            titles=titles,
            core_properties=get_properties(path),
        )


# --- markdown ----------------------------------------------------------------


def _cell(value: str) -> str:
    """One table cell, safe to put between pipes.

    A pipe would end the cell early and a newline would end the row, so both are
    escaped rather than emitted — a GFM table has no way to express either.
    """
    return value.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\v", " ")


def _as_markdown_rows(table: Table) -> list[str]:
    if not table.data:
        return []
    header, *body = table.data
    lines = [
        "| " + " | ".join(_cell(value) for value in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in body)
    return lines


def get_markdown(
    path: Path, *, slides: str = "all", notes: bool = True, images_dir: Path | None = None
) -> str:
    """The deck as markdown, in the dialect :func:`~rp_pptx.pptx.write.create` reads.

    That symmetry is the point: speaker notes come out as HTML comments because
    that is the form ``create`` turns back into notes (section 9), and slides are
    separated by ``---`` because that is an explicit slide break. Round-tripping
    a deck through markdown should produce the same deck, not merely a readable
    document.
    """
    texts = get_text(path, slides=slides)
    note_map = (
        {note.slide_index: note.text for note in get_notes(path, slides=slides)} if notes else {}
    )
    tables: dict[int, list[Table]] = {}
    for table in get_tables(path, slides=slides):
        tables.setdefault(table.slide_index, []).append(table)
    images: dict[int, list[EmbeddedImage]] = {}
    for image in get_images(path, slides=slides, output_dir=images_dir):
        images.setdefault(image.slide_index, []).append(image)

    chunks: list[str] = []
    for slide in texts:
        lines: list[str] = []
        if slide.title:
            lines.append(f"## {slide.title}")
            lines.append("")
        for paragraph in slide.paragraphs:
            if not paragraph.text or paragraph.text == slide.title:
                continue
            lines.append("  " * paragraph.level + f"- {paragraph.text}")
        for table in tables.get(slide.index, []):
            lines.extend(["", *_as_markdown_rows(table)])
        for image in images.get(slide.index, []):
            target = image.extracted_path or Path(image.filename)
            lines.extend(["", f"![{image.alt_text or ''}]({target.as_posix()})"])
        if slide.index in note_map:
            lines.extend(["", f"<!-- {note_map[slide.index]} -->"])
        chunks.append("\n".join(lines).strip())
    return "\n\n---\n\n".join(chunks)
