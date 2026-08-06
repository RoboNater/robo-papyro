from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from PIL import Image
from pptx.enum.shapes import MSO_SHAPE_TYPE

from rp_core.ranges import parse_range_spec
from rp_pptx.models import (
    ChartRef,
    ChartSeries,
    CoreProperties,
    EmbeddedImage,
    Paragraph,
    PresentationIndex,
    Run,
    SlideText,
    SlideTitle,
    SpeakerNotes,
    Table,
)
from rp_pptx.ooxml import opened


def _indices(spec: str, count: int) -> list[int]:
    return parse_range_spec(spec, count, noun="slide")


def _ratio(width: int, height: int) -> str:
    value = width / height
    if abs(value - 16 / 9) < 0.02:
        return "16:9"
    if abs(value - 4 / 3) < 0.02:
        return "4:3"
    f = Fraction(width, height).limit_denominator(100)
    return f"{f.numerator}:{f.denominator}"


def _title(slide) -> str | None:
    return slide.shapes.title.text.strip() if slide.shapes.title is not None else None


def get_properties(path: Path) -> CoreProperties:
    with opened(path) as prs:
        p = prs.core_properties
        return CoreProperties(
            title=p.title,
            author=p.author,
            last_modified_by=p.last_modified_by,
            created=p.created,
            modified=p.modified,
            revision=p.revision,
            category=p.category,
            keywords=p.keywords,
        )


def get_text(path: Path, *, slides: str = "all", runs: bool = False) -> list[SlideText]:
    result = []
    with opened(path) as prs:
        for number in _indices(slides, len(prs.slides)):
            slide = prs.slides[number - 1]
            paragraphs = []
            for shape in _walk_shapes(slide.shapes):
                if not getattr(shape, "has_text_frame", False):
                    continue
                for para in shape.text_frame.paragraphs:
                    run_models = None
                    if runs:
                        run_models = [
                            Run(
                                text=r.text,
                                bold=bool(r.font.bold),
                                italic=bool(r.font.italic),
                                underline=bool(r.font.underline),
                                font=r.font.name,
                                size_pt=r.font.size.pt if r.font.size else None,
                                color=_color(r.font.color),
                            )
                            for r in para.runs
                        ]
                    paragraphs.append(Paragraph(text=para.text, level=para.level, runs=run_models))
            result.append(
                SlideText(
                    index=number,
                    layout=slide.slide_layout.name,
                    title=_title(slide),
                    paragraphs=paragraphs,
                )
            )
    return result


def _color(color) -> str | None:
    try:
        return str(color.rgb) if color.rgb else None
    except AttributeError:
        return None


def _walk_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk_shapes(shape.shapes)


def get_tables(path: Path, *, slides: str = "all", table_index: int | None = None) -> list[Table]:
    result, index = [], 0
    with opened(path) as prs:
        wanted = set(_indices(slides, len(prs.slides)))
        for slide_no, slide in enumerate(prs.slides, 1):
            for shape in _walk_shapes(slide.shapes):
                if not getattr(shape, "has_table", False):
                    continue
                index += 1
                if slide_no not in wanted or (table_index and index != table_index):
                    continue
                table = shape.table
                result.append(
                    Table(
                        index=index,
                        slide_index=slide_no,
                        rows=len(table.rows),
                        cols=len(table.columns),
                        data=[[cell.text for cell in row.cells] for row in table.rows],
                    )
                )
    return result


def get_images(
    path: Path, *, slides: str = "all", output_dir: Path | None = None
) -> list[EmbeddedImage]:
    result, index = [], 0
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    with opened(path) as prs:
        for slide_no in _indices(slides, len(prs.slides)):
            for shape in _walk_shapes(prs.slides[slide_no - 1].shapes):
                if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                    continue
                index += 1
                image = shape.image
                extracted = None
                if output_dir:
                    extracted = Path(output_dir) / f"image-{index}.{image.ext}"
                    extracted.write_bytes(image.blob)
                width = height = None
                try:
                    from io import BytesIO

                    with Image.open(BytesIO(image.blob)) as im:
                        width, height = im.size
                except OSError:
                    pass
                result.append(
                    EmbeddedImage(
                        index=index,
                        slide_index=slide_no,
                        rel_id=shape._pic.blipFill.blip.embed,
                        filename=image.filename,
                        content_type=image.content_type,
                        width_px=width,
                        height_px=height,
                        alt_text=shape.name or None,
                        extracted_path=extracted,
                    )
                )
    return result


def get_notes(path: Path, *, slides: str = "all") -> list[SpeakerNotes]:
    result = []
    with opened(path) as prs:
        for number in _indices(slides, len(prs.slides)):
            text = prs.slides[number - 1].notes_slide.notes_text_frame.text.strip()
            if text:
                result.append(SpeakerNotes(slide_index=number, text=text))
    return result


def get_charts(path: Path, *, slides: str = "all") -> list[ChartRef]:
    result, index = [], 0
    with opened(path) as prs:
        for slide_no in _indices(slides, len(prs.slides)):
            for shape in prs.slides[slide_no - 1].shapes:
                if not getattr(shape, "has_chart", False):
                    continue
                index += 1
                chart = shape.chart
                try:
                    series = [
                        ChartSeries(
                            name=str(s.name) if s.name else None,
                            values=[float(v) if v is not None else None for v in s.values],
                        )
                        for s in chart.series
                    ]
                    categories = [str(c.label) for c in chart.plots[0].categories]
                except (AttributeError, TypeError, ValueError):
                    series, categories = [], []
                result.append(
                    ChartRef(
                        index=index,
                        slide_index=slide_no,
                        chart_type=str(chart.chart_type),
                        categories=categories,
                        series=series,
                        data_available=bool(series),
                    )
                )
    return result


def get_comments(path: Path, *, slides: str = "all") -> list:
    # python-pptx has no comments API. Classic and modern OOXML parsing is deferred.
    return []


def get_markdown(
    path: Path, *, slides: str = "all", notes: bool = True, images_dir: Path | None = None
) -> str:
    note_map = {n.slide_index: n.text for n in get_notes(path, slides=slides)} if notes else {}
    chunks = []
    for slide in get_text(path, slides=slides):
        lines = [f"## {slide.title}"] if slide.title else [f"<!-- slide {slide.index} -->"]
        for para in slide.paragraphs:
            if para.text and para.text != slide.title:
                lines.append(("  " * para.level + "- " if para.level else "") + para.text)
        if slide.index in note_map:
            lines.extend(["", f"> Notes: {note_map[slide.index]}"])
        chunks.append("\n".join(lines))
    if images_dir:
        get_images(path, slides=slides, output_dir=images_dir)
    return "\n\n---\n\n".join(chunks)


def get_index(path: Path) -> PresentationIndex:
    with opened(path) as prs:
        titles = [
            SlideTitle(index=i, layout=s.slide_layout.name, title=_title(s))
            for i, s in enumerate(prs.slides, 1)
        ]
        notes_count = sum(bool(s.notes_slide.notes_text_frame.text.strip()) for s in prs.slides)
        table_count = sum(
            getattr(sh, "has_table", False) for s in prs.slides for sh in _walk_shapes(s.shapes)
        )
        chart_count = sum(getattr(sh, "has_chart", False) for s in prs.slides for sh in s.shapes)
        image_count = sum(
            sh.shape_type == MSO_SHAPE_TYPE.PICTURE
            for s in prs.slides
            for sh in _walk_shapes(s.shapes)
        )
        return PresentationIndex(
            path=Path(path),
            slide_count=len(prs.slides),
            slide_width_emu=prs.slide_width,
            slide_height_emu=prs.slide_height,
            aspect_ratio=_ratio(prs.slide_width, prs.slide_height),
            master_count=len(prs.slide_masters),
            layout_names=[
                layout.name for master in prs.slide_masters for layout in master.slide_layouts
            ],
            image_count=image_count,
            table_count=table_count,
            chart_count=chart_count,
            notes_count=notes_count,
            comment_count=0,
            titles=titles,
            core_properties=get_properties(path),
        )
