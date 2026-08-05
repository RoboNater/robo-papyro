"""Text replacement that survives Word's arbitrary run splitting.

**Read this before touching anything that replaces text.** Word splits a single
logical string across several ``w:r`` runs for reasons that have nothing to do
with meaning — spellcheck state, revision ids, a formatting change three
characters in. A paragraph that reads ``Dear {{ client.name }},`` can be stored
as ``Dear {{ ``, ``clie``, ``nt.na``, ``me }},``. A naive ``run.text.replace()``
finds nothing at all, and reports success. This is why ``docxtpl`` exists, and
reimplementing it is the main engineering work in this package (spec section 6).

The approach, per spec section 6:

1. Concatenate a paragraph's text nodes, keeping an offset map back to each
2. Locate matches against the concatenated string
3. Write the replacement into the node containing the match *start*; blank what
   the match covered in every node it spans
4. The replacement therefore inherits the first spanned run's formatting —
   documented behavior, not an accident
5. Walk table cells, headers, footers, footnotes, endnotes, **and text boxes**;
   body-only replacement is the classic silent bug

This module works on ``lxml`` elements rather than python-docx objects, because
half the places text hides — footnotes, text boxes — have no python-docx
representation at all. Everything it needs is a ``w:p`` element.

Two details that are easy to get wrong and expensive to debug:

* **Deleted text is skipped.** Tracked deletions hold their text in
  ``w:delText``, not ``w:t``, so collecting ``w:t`` nodes excludes them by
  construction. Replacing inside a deletion would resurrect text the author
  removed.
* **Nested paragraphs are not this paragraph.** A text box's content is a
  ``w:p`` inside a run of the outer paragraph. Its text belongs to it, and it is
  visited separately.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from rp_docx.ooxml import NS, qn, xpath

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass(frozen=True)
class TextSpan:
    """One ``w:t`` node's position in its paragraph's concatenated text."""

    node: Any
    run: Any
    start: int
    end: int


@dataclass(frozen=True)
class Match:
    """One located occurrence: where it is, and what replaces it."""

    key: str
    start: int
    end: int
    replacement: str


def text_spans(paragraph: Any) -> list[TextSpan]:
    """The paragraph's own ``w:t`` nodes with their offsets, in document order.

    "Its own" excludes the content of any paragraph nested inside it — a text
    box is a paragraph living in a run, and its text is visited when that
    paragraph is.
    """
    spans: list[TextSpan] = []
    offset = 0
    for node in paragraph.iter(qn("w:t")):
        if _owning_paragraph(node) is not paragraph:
            continue
        text = node.text or ""
        spans.append(
            TextSpan(node=node, run=_owning_run(node), start=offset, end=offset + len(text))
        )
        offset += len(text)
    return spans


def paragraph_text(paragraph: Any) -> str:
    """The paragraph's visible text, as the replacement machinery sees it."""
    return "".join(span.node.text or "" for span in text_spans(paragraph))


def _owning_paragraph(node: Any) -> Any:
    parent = node.getparent()
    while parent is not None and parent.tag != qn("w:p"):
        parent = parent.getparent()
    return parent


def _owning_run(node: Any) -> Any:
    parent = node.getparent()
    while parent is not None and parent.tag != qn("w:r"):
        parent = parent.getparent()
    return parent


def find_matches(
    text: str, replacements: dict[str, str], *, ignore_case: bool = False
) -> list[Match]:
    """Every non-overlapping occurrence of any key, left to right.

    Where two keys could match at the same place — ``{{ name }}`` and
    ``{{ name }} suffix``, or ``ab`` and ``abc`` — the **longer** one wins, and
    the shorter is not then matched inside it. Picking arbitrarily would make
    the result depend on dict ordering, which is not something a caller can see
    or control.
    """
    if not text or not replacements:
        return []
    flags = re.IGNORECASE if ignore_case else 0
    candidates: list[Match] = []
    for key, value in replacements.items():
        if not key:
            continue
        for found in re.finditer(re.escape(key), text, flags):
            candidates.append(
                Match(key=key, start=found.start(), end=found.end(), replacement=value)
            )

    # Longest first at any given start, then left to right, then greedily
    # non-overlapping — the same result whatever order the keys arrived in.
    candidates.sort(key=lambda m: (m.start, -(m.end - m.start)))
    chosen: list[Match] = []
    consumed = -1
    for candidate in candidates:
        if candidate.start >= consumed:
            chosen.append(candidate)
            consumed = candidate.end
    return chosen


def _set_text(node: Any, text: str) -> None:
    """Write a text node, keeping whitespace Word would otherwise discard.

    Without ``xml:space="preserve"`` Word strips leading and trailing spaces,
    so a replacement ending in a space silently loses it and words run together
    in the rendered document.
    """
    node.text = text
    if text != text.strip():
        node.set(XML_SPACE, "preserve")
    elif node.get(XML_SPACE) == "preserve":
        del node.attrib[XML_SPACE]


def _strip_formatting(run: Any) -> None:
    if run is None:
        return
    for properties in run.findall(qn("w:rPr")):
        run.remove(properties)


def replace_in_paragraph(
    paragraph: Any,
    replacements: dict[str, str],
    *,
    ignore_case: bool = False,
    preserve_formatting: bool = True,
) -> dict[str, int]:
    """Replace every occurrence in one paragraph. Returns key → count.

    The replacement text lands in the run holding the match's *start* and so
    takes that run's formatting; the rest of the match is blanked out of the
    runs it spanned. With ``preserve_formatting=False`` the receiving run's
    direct formatting is dropped instead, leaving the replacement in the
    paragraph style's own appearance.
    """
    spans = text_spans(paragraph)
    if not spans:
        return {}
    text = "".join(span.node.text or "" for span in spans)
    matches = find_matches(text, replacements, ignore_case=ignore_case)
    if not matches:
        return {}

    # Right to left: rewriting a node changes lengths only at and after the
    # match, and every remaining match ends before it, so the offsets computed
    # from the original text stay valid.
    for match in reversed(matches):
        _apply(spans, match, preserve_formatting=preserve_formatting)

    counts: dict[str, int] = {}
    for match in matches:
        counts[match.key] = counts.get(match.key, 0) + 1
    return counts


def _apply(spans: list[TextSpan], match: Match, *, preserve_formatting: bool) -> None:
    written = False
    for span in spans:
        if span.end <= match.start or span.start >= match.end:
            continue
        current = span.node.text or ""
        local_start = max(0, match.start - span.start)
        local_end = min(len(current), match.end - span.start)
        head, tail = current[:local_start], current[local_end:]
        if not written:
            _set_text(span.node, head + match.replacement + tail)
            if not preserve_formatting:
                _strip_formatting(span.run)
            written = True
        else:
            _set_text(span.node, head + tail)


# --- walking every place text hides ---------------------------------------


def iter_paragraphs(root: Any, *, location: str = "body") -> Iterator[tuple[str, Any]]:
    """Every paragraph in an XML part, with a label saying where it is.

    Labels are ``"body"``, ``"table:N"`` for the Nth table in the part (nested
    tables count, in document order), and whatever ``location`` names for a
    header, footer, footnote, or endnote part. Text-box paragraphs are reached
    because they are ordinary ``w:p`` elements living inside a run.
    """
    # Keyed by the element itself, not by id(): lxml creates its Python proxies
    # on demand and discards them once unreferenced, so an id() recorded now can
    # belong to an unrelated proxy by the time the ancestor walk looks it up.
    # Holding the elements in the dict keeps the proxies alive and identity
    # stable for as long as the walk needs it.
    tables = {table: index for index, table in enumerate(xpath(root, ".//w:tbl"), start=1)}
    for paragraph in xpath(root, ".//w:p"):
        yield _locate(paragraph, tables, location), paragraph


def _locate(paragraph: Any, tables: dict[Any, int], default: str) -> str:
    ancestor = paragraph.getparent()
    while ancestor is not None:
        if ancestor.tag == qn("w:tbl") and ancestor in tables:
            return f"table:{tables[ancestor]}"
        ancestor = ancestor.getparent()
    return default


def replace_in_part(
    root: Any,
    replacements: dict[str, str],
    *,
    location: str = "body",
    ignore_case: bool = False,
    preserve_formatting: bool = True,
) -> tuple[dict[str, int], list[str]]:
    """Replace throughout one XML part. Returns (counts, locations touched)."""
    counts: dict[str, int] = {}
    touched: list[str] = []
    for where, paragraph in iter_paragraphs(root, location=location):
        found = replace_in_paragraph(
            paragraph,
            replacements,
            ignore_case=ignore_case,
            preserve_formatting=preserve_formatting,
        )
        if not found:
            continue
        if where not in touched:
            touched.append(where)
        for key, count in found.items():
            counts[key] = counts.get(key, 0) + count
    return counts, touched


def collect_text(root: Any) -> list[str]:
    """Every paragraph's text in a part — the read-side use of the same walk."""
    return [paragraph_text(paragraph) for _, paragraph in iter_paragraphs(root)]


__all__ = [
    "NS",
    "Match",
    "TextSpan",
    "collect_text",
    "find_matches",
    "iter_paragraphs",
    "paragraph_text",
    "replace_in_paragraph",
    "replace_in_part",
    "text_spans",
]
