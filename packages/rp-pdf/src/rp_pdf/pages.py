"""Page specs for PDFs: the generic parser from ``rp-core``, plus page labels.

Generic 1-based range parsing ("3", "1-5", "1,3-5,9", "all") lives in
``rp_core.ranges`` and is shared by every package in the suite. What stays here
is the part only a PDF tool can have: resolving a spec against the document's
*page labels* — the "iv" / "FM2" / "1" strings a reader displays, which need not
be numbers and need not start at 1.

``rp-core`` deliberately has no concept of a page label, so this cannot move
there; ``parse_page_labels`` returns physical page numbers, which is the only
currency the core understands.
"""

from __future__ import annotations

from collections.abc import Sequence

from rp_core.ranges import RangeSpec, RangeSpecError, contiguous_runs, parse_range_spec

#: A page spec is an ordinary range spec; the names are kept because rp-pdf's
#: public API and CLI have always spelled it this way.
PageSpec = RangeSpec
PageSpecError = RangeSpecError

__all__ = [
    "PageSpec",
    "PageSpecError",
    "contiguous_runs",
    "parse_page_labels",
    "parse_pages",
]


def parse_pages(spec: PageSpec, page_count: int) -> list[int]:
    """Parse a page spec into sorted, de-duplicated 1-based physical page numbers."""
    return parse_range_spec(spec, page_count, noun="page")


def parse_page_labels(spec: PageSpec, labels: Sequence[str]) -> list[int]:
    """Parse a page spec against a PDF's page labels (one label per physical page).

    Items are labels ("iv", "FM2", "5") or label ranges ("i-xx", "1-30"); ranges
    cover the physical span between their endpoints. Returns sorted, de-duplicated
    1-based physical page numbers. An item that exactly matches a label wins over
    range interpretation, so labels containing hyphens stay addressable.
    """
    spec = spec.strip()
    if not spec:
        raise PageSpecError("Empty page spec; expected 'all', a page label, or a range like i-xx")
    if spec.lower() == "all":
        return list(range(1, len(labels) + 1))
    pages: set[int] = set()
    for item in spec.split(","):
        item = item.strip()
        if not item:
            raise PageSpecError(f"Empty item in page spec {spec!r}")
        start, end = _resolve_label_item(item, labels, spec)
        pages.update(range(start, end + 1))
    return sorted(pages)


def _resolve_label_item(item: str, labels: Sequence[str], spec: str) -> tuple[int, int]:
    single = _find_label(item, labels)
    if single is not None:
        return single, single
    reversed_range = None
    for pos in (i for i, ch in enumerate(item) if ch == "-"):
        start = _find_label(item[:pos], labels)
        end = _find_label(item[pos + 1 :], labels)
        if start is not None and end is not None:
            if start <= end:
                return start, end
            reversed_range = (start, end)
    if reversed_range is not None:
        raise PageSpecError(f"Reversed range {item!r} in page spec {spec!r}")
    raise PageSpecError(
        f"No page labeled {item!r} in this PDF (labels run from {labels[0]!r} to {labels[-1]!r})"
    )


def _find_label(label: str, labels: Sequence[str]) -> int | None:
    """1-based physical page for a label; exact match first, then unique
    case-insensitive match."""
    label = label.strip()
    if label in labels:
        return labels.index(label) + 1
    matches = [i for i, candidate in enumerate(labels) if candidate.lower() == label.lower()]
    if len(matches) == 1:
        return matches[0] + 1
    return None
