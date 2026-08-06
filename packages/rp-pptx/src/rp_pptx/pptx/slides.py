"""Deleting and reordering slides — ``p:sldIdLst`` surgery (spec section 7).

python-pptx has no API for either. Deck order *is* the order of ``p:sldId``
elements in ``ppt/presentation.xml``, so reordering is moving those elements and
deleting is removing one plus the relationship it points at. Both go through the
element list directly.

**Known limit: media referenced only by a deleted slide stays in the package.**
Orphaned media is invisible bloat, not corruption, and garbage-collecting shared
media is easy to get subtly wrong — an image used by two slides must survive the
deletion of one. Section 7 accepts the bloat and asks for the limit to be noted,
which is what this paragraph is.

Nothing here prints, and nothing here imports typer.
"""

from __future__ import annotations

from pathlib import Path

from rp_core.errors import InputError
from rp_core.ranges import parse_range_spec
from rp_pptx.models import SlideOpResult
from rp_pptx.ooxml import copy_for_edit, save


def delete_slides(path: Path, slides: str, *, output: Path | None = None) -> SlideOpResult:
    """Delete the selected slides.

    Refuses to leave zero. An empty deck is a corner nothing downstream is
    tested against — PowerPoint, LibreOffice, and python-pptx each get to have
    an opinion — and "delete every slide" is far likelier a range-spec mistake
    than an intent (section 4).
    """
    presentation, target = copy_for_edit(path, output)
    count = len(presentation.slides)
    selected = parse_range_spec(slides, count, noun="slide")
    if len(selected) >= count:
        raise InputError(
            f"Refusing to delete every slide: {slides!r} selects all {count} of them. "
            "An empty deck is not something this package will produce."
        )
    # Back to front, so each index still refers to what it did when parsed.
    for number in sorted(selected, reverse=True):
        slide_id = presentation.slides._sldIdLst[number - 1]
        presentation.part.drop_rel(slide_id.rId)
        presentation.slides._sldIdLst.remove(slide_id)
    save(presentation, target)
    return SlideOpResult(output=target, slide_count=len(presentation.slides))


def reorder_slides(path: Path, order: list[int], *, output: Path | None = None) -> SlideOpResult:
    """Reorder to ``order``, which must be a complete permutation of 1..n.

    Anything else is an :class:`~rp_core.errors.InputError` naming exactly what
    is wrong with it. A partial spec, silently guessing where the unlisted
    slides go, is precisely the kind of surprise section 10 exists to prevent —
    and the guess would be invisible until someone opened the deck.
    """
    presentation, target = copy_for_edit(path, output)
    count = len(presentation.slides)
    expected = list(range(1, count + 1))
    if sorted(order) != expected:
        missing = sorted(set(expected) - set(order))
        duplicated = sorted({n for n in order if order.count(n) > 1})
        unknown = sorted({n for n in order if n not in expected})
        problems = []
        if missing:
            problems.append(f"missing {missing}")
        if duplicated:
            problems.append(f"duplicated {duplicated}")
        if unknown:
            problems.append(f"out of range {unknown}")
        raise InputError(
            f"--order must be a complete permutation of slides 1-{count}: "
            + ", ".join(problems or ["it is not one"])
        )

    id_list = presentation.slides._sldIdLst
    original = list(id_list)
    for element in original:
        id_list.remove(element)
    for number in order:
        id_list.append(original[number - 1])
    save(presentation, target)
    return SlideOpResult(output=target, slide_count=len(presentation.slides))
