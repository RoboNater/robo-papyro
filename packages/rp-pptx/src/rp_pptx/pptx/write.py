from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from rp_pptx import templates
from rp_pptx.models import CoreProperties, ReplaceResult
from rp_pptx.ooxml import copy_for_edit, opened, save
from rp_pptx.pptx.read import _walk_shapes
from rp_pptx.pptx.runs import replace_in_paragraph


def _blocks(markdown: str) -> list[tuple[str | None, list[str]]]:
    result, title, body = [], None, []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if title is not None or body:
                result.append((title, body))
            title, body = line.lstrip("#").strip(), []
        elif line.strip():
            body.append(line.strip().lstrip("-* "))
    if title is not None or body:
        result.append((title, body))
    return result


def _append(prs, markdown: str, layoutmap, *, append: bool = False) -> None:
    for index, (title, body) in enumerate(_blocks(markdown)):
        role = (
            "section"
            if append and index == 0 and title
            else "title"
            if index == 0 and title
            else "content"
        )
        layout = templates.require_layout(prs, getattr(layoutmap, role))
        slide = prs.slides.add_slide(layout)
        if slide.shapes.title is not None and title:
            slide.shapes.title.text = title
        placeholders = [
            p
            for p in slide.placeholders
            if getattr(p, "has_text_frame", False) and p != slide.shapes.title
        ]
        if placeholders and body:
            frame = placeholders[0].text_frame
            frame.clear()
            for i, text in enumerate(body):
                para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                para.text = text


def create(
    output: Path,
    *,
    markdown: str | None = None,
    template: str | Path | None = None,
    aspect: str = "16:9",
) -> Path:
    implicit = template is None
    template_path = templates.resolve_template(template)
    with opened(template_path) as source:
        from io import BytesIO

        stream = BytesIO()
        source.save(stream)
    stream.seek(0)
    prs = Presentation(stream)
    while prs.slides:
        slide_id = prs.slides._sldIdLst[0]
        prs.part.drop_rel(slide_id.rId)
        prs.slides._sldIdLst.remove(slide_id)
    if implicit:
        prs.slide_width = Inches(13.333 if aspect == "16:9" else 10)
        prs.slide_height = Inches(7.5)
    if markdown:
        _append(prs, markdown, templates.load_layoutmap(template_path))
    return save(prs, output)


def append_markdown(path: Path, markdown: str, *, output: Path | None = None) -> Path:
    prs, target = copy_for_edit(path, output)
    _append(prs, markdown, templates.load_layoutmap(Path(path)), append=True)
    return save(prs, target)


def replace_text(
    path: Path,
    replacements: dict[str, str],
    *,
    output: Path | None = None,
    match_case: bool = True,
    preserve_formatting: bool = True,
) -> ReplaceResult:
    prs, target = copy_for_edit(path, output)
    counts = {key: 0 for key in replacements}
    locations = []
    for slide_no, slide in enumerate(prs.slides, 1):
        changed = False
        shapes = list(_walk_shapes(slide.shapes))
        for shape in shapes:
            frames = []
            if getattr(shape, "has_text_frame", False):
                frames.append(shape.text_frame)
            if getattr(shape, "has_table", False):
                frames.extend(cell.text_frame for row in shape.table.rows for cell in row.cells)
            for frame in frames:
                for para in frame.paragraphs:
                    for old, new in replacements.items():
                        count = replace_in_paragraph(para, old, new, match_case=match_case)
                        counts[old] += count
                        changed |= bool(count)
        if changed:
            locations.append(f"slide:{slide_no}")
    save(prs, target)
    return ReplaceResult(output=target, replacements=counts, locations=locations)


def set_notes(path: Path, slide: int, text: str, *, output: Path | None = None) -> Path:
    prs, target = copy_for_edit(path, output)
    frame = prs.slides[slide - 1].notes_slide.notes_text_frame
    frame.text = text
    return save(prs, target)


def set_properties(path: Path, props: CoreProperties, *, output: Path | None = None) -> Path:
    prs, target = copy_for_edit(path, output)
    target_props = prs.core_properties
    for key, value in props.model_dump(exclude_none=True).items():
        setattr(target_props, key, value)
    return save(prs, target)
