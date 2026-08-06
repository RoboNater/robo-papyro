"""Creating and editing presentations.

Two things govern everything here: the resolved template's
:class:`~rp_pptx.models.LayoutMap` (spec section 5) and :mod:`rp_pptx.pptx.runs`
(section 6). Neither is optional — a deck built with the wrong layouts looks
right until someone opens it in PowerPoint, and a replacement that checks one run
at a time silently finds nothing.

**A document is a scroll; a deck is a sequence.** Section 9's segmentation rule
is what bridges them, and it has to be deterministic: the same markdown must
always produce the same slides. The rules, for :func:`create`:

- the first ``#`` opens the title slide, and a paragraph straight after it
  becomes the subtitle
- every later ``#`` opens a section-break slide
- every ``##`` opens a content slide
- ``---`` breaks the slide without changing role or giving it a title
- ``###`` and deeper are a **bold lead-in bullet**, not a slide — decks do not
  have sub-sub-sections, outlines do
- an HTML comment becomes that slide's speaker notes (the Marp convention)

:func:`append_markdown` uses the same rules with one substitution and two
guarantees: a leading ``#`` opens a *section* slide because the deck already has
its title, leading unheaded content opens a new untitled slide rather than being
merged into the existing last one, and no existing slide is touched at all.

**No reflow, no auto-splitting.** Slides do not scroll: content that outgrows its
placeholder overflows the slide edge silently. This module places what it is
given and does not second-guess quantity — deciding a section is "too long" is
editorial judgement, and out of scope.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pptx import Presentation
from pptx.util import Emu, Inches, Pt

from rp_core.errors import InputError
from rp_core.markdown import Block, parse_inline, parse_markdown
from rp_pptx import templates
from rp_pptx.models import CoreProperties, LayoutMap, ReplaceResult
from rp_pptx.ooxml import copy_for_edit, opened, save
from rp_pptx.pptx import shapes as shape_tools
from rp_pptx.pptx.runs import replace_in_paragraph

#: Font for fenced code. PowerPoint has no code style concept, so a monospace
#: text box is the whole of what "code block" can mean here (spec section 9).
CODE_FONT = "Consolas"

#: Slide geometries ``create`` knows by name, in EMU. Height is constant; the
#: aspect ratio is a width decision.
ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (Emu(int(Inches(13.333))), Emu(int(Inches(7.5)))),
    "4:3": (Emu(int(Inches(10))), Emu(int(Inches(7.5)))),
}

#: A paragraph that is nothing but a markdown image. Not a parser block kind on
#: purpose — see :mod:`rp_core.markdown` — so it is matched here instead.
_IMAGE_ONLY = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<href>[^)\s]+)\)$")


@dataclass
class SlidePlan:
    """One slide, decided before anything is built.

    Segmentation and rendering are separate passes so the layout each slide
    needs is known before a single shape exists — which is what lets layout
    checking stay lazy (section 5.1) and still be raised at the point of use.
    """

    role: str = "content"
    title: str | None = None
    subtitle: str | None = None
    body: list[Block] = field(default_factory=list)
    extras: list[Block] = field(default_factory=list)
    images: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.title or self.subtitle or self.body or self.extras or self.images)


def _image_in(block: Block) -> tuple[str, str] | None:
    if block.kind != "paragraph":
        return None
    found = _IMAGE_ONLY.match(block.text.strip())
    return (found.group("alt"), found.group("href")) if found else None


def segment(markdown: str, *, appending: bool) -> list[SlidePlan]:
    """Markdown blocks to a list of slides, per section 9.

    ``appending`` swaps one rule: a leading ``#`` opens a section slide rather
    than the deck's title slide, because the deck already has a title.
    """
    plans: list[SlidePlan] = []
    current = SlidePlan()
    seen_title = appending

    def flush() -> None:
        nonlocal current
        if not current.is_empty or current.notes:
            plans.append(current)
        current = SlidePlan()

    for block in parse_markdown(markdown):
        if block.kind == "heading" and block.level <= 2:
            top_level = block.level == 1
            if top_level and not seen_title:
                flush()
                current.role, current.title = "title", block.text
                seen_title = True
            else:
                flush()
                current.role = "section" if top_level else "content"
                current.title = block.text
            continue

        if block.kind == "rule":
            # An explicit break: same role, no title. Section 9 is specific that
            # the layout continues rather than resetting to content.
            role = current.role
            flush()
            current.role = role
            continue

        if block.kind == "comment":
            current.notes.append(block.text)
            continue

        if block.kind == "heading":
            # Level 3 and deeper: a bold lead-in bullet at the current level.
            current.body.append(Block(kind="bullet", text=f"**{block.text}**", level=1))
            continue

        image = _image_in(block)
        if image is not None:
            current.images.append(image)
            continue

        if block.kind in ("table", "code"):
            current.extras.append(block)
            continue

        if (
            block.kind == "paragraph"
            and current.role == "title"
            and current.subtitle is None
            and not current.body
        ):
            # The paragraph straight after the deck title is the subtitle.
            current.subtitle = block.text
            continue

        current.body.append(block)

    flush()

    for plan in plans:
        # A slide whose only content is an image gets the blank layout, so the
        # picture is not fighting an empty body placeholder for the space.
        if plan.images and not (plan.body or plan.extras or plan.title):
            plan.role = "blank"
    return plans


def _body_placeholder(slide: Any) -> Any | None:
    """The slide's body placeholder — the first text one that is not the title.

    Compared by element rather than by object: python-pptx builds a fresh proxy
    each time a placeholder is reached, so ``is`` between two of them is false
    even when they wrap the same shape.
    """
    title = slide.shapes.title
    title_element = title._element if title is not None else None
    for placeholder in slide.placeholders:
        if placeholder._element is title_element:
            continue
        if getattr(placeholder, "has_text_frame", False):
            return placeholder
    return None


def _write_spans(paragraph: Any, text: str) -> None:
    """Render inline markdown into one paragraph's runs."""
    for span in parse_inline(text):
        run = paragraph.add_run()
        run.text = span.text
        run.font.bold = span.bold or None
        run.font.italic = span.italic or None
        if span.code:
            run.font.name = CODE_FONT


def _fill_body(slide: Any, blocks: list[Block]) -> None:
    placeholder = _body_placeholder(slide)
    if placeholder is None or not blocks:
        return
    frame = placeholder.text_frame
    frame.clear()
    for offset, block in enumerate(blocks):
        paragraph = frame.paragraphs[0] if offset == 0 else frame.add_paragraph()
        # Bullet levels are 1-based in markdown nesting and 0-based as outline
        # levels; PowerPoint stops at 8.
        paragraph.level = min(max(block.level - 1, 0), 8) if block.level else 0
        _write_spans(paragraph, block.text)


def _add_table(slide: Any, block: Block, top: Emu, width: int) -> Emu:
    rows, columns = len(block.rows), max(len(row) for row in block.rows)
    height = Emu(int(Inches(0.4)) * rows)
    shape = slide.shapes.add_table(
        rows, columns, Inches(0.8), top, Emu(int(width) - int(Inches(1.6))), height
    )
    for row_index, row in enumerate(block.rows):
        for column_index in range(columns):
            value = row[column_index] if column_index < len(row) else ""
            shape.table.cell(row_index, column_index).text = value
    return Emu(int(top) + int(height) + int(Inches(0.2)))


def _add_code(slide: Any, block: Block, top: Emu, width: int) -> Emu:
    height = Inches(0.25) * max(len(block.lines), 1)
    box = slide.shapes.add_textbox(Inches(0.8), top, width - Inches(1.6), height)
    frame = box.text_frame
    frame.word_wrap = False
    for offset, line in enumerate(block.lines):
        paragraph = frame.paragraphs[0] if offset == 0 else frame.add_paragraph()
        run = paragraph.add_run()
        run.text = line
        run.font.name = CODE_FONT
        run.font.size = Pt(12)
    return Emu(int(top) + int(height) + int(Inches(0.2)))


def _add_image(slide: Any, alt: str, href: str, top: Emu) -> Emu:
    source = Path(href)
    if not source.is_file():
        raise InputError(
            f"Image not found: {href}. Paths in markdown resolve relative to the "
            "working directory, not to the markdown file."
        )
    picture = slide.shapes.add_picture(str(source), Inches(0.8), top, height=Inches(3))
    if alt:
        picture._element._nvXxPr.cNvPr.set("descr", alt)
    return Emu(int(top) + int(picture.height) + int(Inches(0.2)))


def _render(presentation: Presentation, plans: list[SlidePlan], layoutmap: LayoutMap) -> None:
    for plan in plans:
        # Lazy, per role, at the point of use (section 5.1): a deck with no
        # section breaks must not need a section layout to exist.
        layout = templates.require_layout(presentation, getattr(layoutmap, plan.role))
        slide = presentation.slides.add_slide(layout)

        if plan.title and slide.shapes.title is not None:
            slide.shapes.title.text = plan.title
        subtitle = [Block(kind="paragraph", text=plan.subtitle)] if plan.subtitle else []
        _fill_body(slide, subtitle + plan.body)

        top = Emu(int(Inches(2.2)) if (plan.title or plan.body) else int(Inches(0.8)))
        for block in plan.extras:
            if block.kind == "table":
                top = _add_table(slide, block, top, presentation.slide_width)
            else:
                top = _add_code(slide, block, top, presentation.slide_width)
        for alt, href in plan.images:
            top = _add_image(slide, alt, href, top)

        if plan.notes:
            slide.notes_slide.notes_text_frame.text = "\n\n".join(plan.notes)


def create(
    output: Path,
    *,
    markdown: str | None = None,
    template: str | Path | None = None,
    aspect: Literal["16:9", "4:3"] = "16:9",
) -> Path:
    """Build a deck, optionally from markdown.

    **The aspect decision is made on the ``template`` argument, not the resolved
    path** (spec section 4). ``resolve_template`` maps ``None`` onto a real
    ``Path``, so by the time resolution has happened an implicit default is
    indistinguishable from an explicitly requested one — and the two must differ:
    ``template=None`` forces ``aspect`` over whatever the fallback says, while any
    explicitly supplied template wins on geometry. So explicitness is recorded
    before resolving, and that is contract rather than implementation detail.
    """
    if aspect not in ASPECTS:
        raise InputError(f"Unknown aspect {aspect!r}; expected one of {', '.join(ASPECTS)}")
    implicit = template is None
    template_path = templates.resolve_template(template)

    with opened(template_path) as source:
        presentation = source
        while presentation.slides:
            slide_id = presentation.slides._sldIdLst[0]
            presentation.part.drop_rel(slide_id.rId)
            presentation.slides._sldIdLst.remove(slide_id)
        if implicit:
            presentation.slide_width, presentation.slide_height = ASPECTS[aspect]
        if markdown:
            _render(
                presentation,
                segment(markdown, appending=False),
                templates.load_layoutmap(template_path),
            )
        return save(presentation, output)


def append_markdown(path: Path, markdown: str, *, output: Path | None = None) -> Path:
    """Add slides to an existing deck. Never modifies one that is already there."""
    presentation, target = copy_for_edit(path, output)
    _render(presentation, segment(markdown, appending=True), templates.load_layoutmap(Path(path)))
    return save(presentation, target)


def replace_text(
    path: Path,
    replacements: dict[str, str],
    *,
    output: Path | None = None,
    match_case: bool = True,
    preserve_formatting: bool = True,
) -> ReplaceResult:
    """Replace throughout the deck: shapes, tables, groups, and notes.

    **Scope is section 6's.** Every shape with a text frame on every slide, table
    cells, shapes inside groups recursively, and notes slides. Layouts and
    masters are excluded — their text is design furniture, and editing it from a
    content operation is a surprise.

    A key that matched nothing is reported with a count of zero rather than
    omitted, so a caller can tell "replaced nothing" from "never asked".
    """
    presentation, target = copy_for_edit(path, output)
    counts = dict.fromkeys(replacements, 0)
    locations: list[str] = []
    table_index = 0

    def run(frame: Any, where: str) -> None:
        for paragraph in frame.paragraphs:
            found = replace_in_paragraph(
                paragraph,
                replacements,
                ignore_case=not match_case,
                preserve_formatting=preserve_formatting,
            )
            for key, count in found.items():
                counts[key] += count
            if found and where not in locations:
                locations.append(where)

    for number, slide in enumerate(presentation.slides, 1):
        for shape in shape_tools.walk(slide.shapes):
            if getattr(shape, "has_table", False):
                table_index += 1
                for row in shape.table.rows:
                    for cell in row.cells:
                        run(cell.text_frame, f"table:{table_index}")
            elif getattr(shape, "has_text_frame", False):
                run(shape.text_frame, f"slide:{number}")
        if slide.has_notes_slide:
            run(slide.notes_slide.notes_text_frame, f"notes:{number}")

    save(presentation, target)
    return ReplaceResult(output=target, replacements=counts, locations=locations)


def set_notes(path: Path, slide: int, text: str, *, output: Path | None = None) -> Path:
    """Replace one slide's speaker notes.

    ``slide`` is 1-based like every other index in the suite. Bounds are checked
    rather than left to Python: index 0 would quietly address the *last* slide,
    which is the kind of silent wrong-target edit that is worst to debug.
    """
    presentation, target = copy_for_edit(path, output)
    count = len(presentation.slides)
    if not 1 <= slide <= count:
        raise InputError(f"Slide {slide} is out of range; valid slides are 1-{count}")
    presentation.slides[slide - 1].notes_slide.notes_text_frame.text = text
    return save(presentation, target)


def set_properties(path: Path, props: CoreProperties, *, output: Path | None = None) -> Path:
    """Update core properties. ``None`` means leave alone, not clear."""
    presentation, target = copy_for_edit(path, output)
    for key, value in props.model_dump(exclude_none=True).items():
        setattr(presentation.core_properties, key, value)
    return save(presentation, target)
