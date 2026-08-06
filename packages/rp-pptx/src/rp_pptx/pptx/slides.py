from pathlib import Path

from rp_core.errors import InputError
from rp_core.ranges import parse_range_spec
from rp_pptx.models import SlideOpResult
from rp_pptx.ooxml import copy_for_edit, save


def delete_slides(path: Path, slides: str, *, output: Path | None = None) -> SlideOpResult:
    prs, target = copy_for_edit(path, output)
    selected = parse_range_spec(slides, len(prs.slides), noun="slide")
    if len(selected) == len(prs.slides):
        raise InputError("Refusing to delete every slide")
    for number in reversed(selected):
        slide_id = prs.slides._sldIdLst[number - 1]
        prs.part.drop_rel(slide_id.rId)
        prs.slides._sldIdLst.remove(slide_id)
    save(prs, target)
    return SlideOpResult(output=target, slide_count=len(prs.slides))


def reorder_slides(path: Path, order: list[int], *, output: Path | None = None) -> SlideOpResult:
    prs, target = copy_for_edit(path, output)
    expected = list(range(1, len(prs.slides) + 1))
    if sorted(order) != expected:
        missing = sorted(set(expected) - set(order))
        duplicates = sorted({n for n in order if order.count(n) > 1})
        raise InputError(
            f"Order must be a complete permutation; missing={missing}, duplicated={duplicates}"
        )
    ids = list(prs.slides._sldIdLst)
    for item in ids:
        prs.slides._sldIdLst.remove(item)
    for number in order:
        prs.slides._sldIdLst.append(ids[number - 1])
    save(prs, target)
    return SlideOpResult(output=target, slide_count=len(prs.slides))
