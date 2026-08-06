"""Walking a slide's shapes, including the ones inside groups.

Small enough to feel like it belongs in ``read.py``, but ``write.py`` needs the
identical traversal and importing a private helper across modules is how the two
quietly drift apart. Spec section 6 makes the recursion load-bearing: a
replacement that misses grouped shapes is the pptx version of the body-only bug
section 6 warns about, and grouped shapes are exactly where a real deck hides its
callouts.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from rp_pptx.ooxml import qn

#: Classification is done on the element tag rather than ``shape.shape_type``.
#: python-pptx *raises* ``NotImplementedError`` for a shape it cannot classify,
#: and a deck only has to contain one — a SmartArt frame, an ink annotation, a
#: hand-authored shape — for a whole read to die on a shape nobody asked about.
#: The tag is unambiguous, cannot raise, and is what the classification is
#: derived from anyway.
_GROUP = qn("p:grpSp")
_PICTURE = qn("p:pic")


def is_group(shape: Any) -> bool:
    return shape._element.tag == _GROUP


def is_picture(shape: Any) -> bool:
    return shape._element.tag == _PICTURE


def walk(shapes: Any) -> Iterator[Any]:
    """Every shape in ``shapes``, descending into groups depth-first.

    Groups are yielded before their children so a caller can still see the
    grouping; callers that only want leaves filter them out.
    """
    for shape in shapes:
        yield shape
        if is_group(shape):
            yield from walk(shape.shapes)


def text_frames(shape: Any) -> Iterator[Any]:
    """Every text frame a shape offers — its own, and its table's cells.

    A group has no text frame of its own; its children are reached through
    :func:`walk`, so nothing is yielded for it here.
    """
    if getattr(shape, "has_text_frame", False):
        yield shape.text_frame
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                yield cell.text_frame
