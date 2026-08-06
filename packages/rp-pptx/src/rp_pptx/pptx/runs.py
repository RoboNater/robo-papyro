"""Run-spanning replacement for DrawingML paragraphs (spec section 6).

DrawingML splits a logical string across ``a:r`` runs as arbitrarily as
WordprocessingML splits ``w:r`` — formatting boundaries, language tagging,
editing history. A placeholder the user sees as ``{{ name }}`` may live in the
file as ``{{ na`` + ``me }}``, so a per-run replace finds nothing and reports
success. Every replacement in this package goes through here.

The algorithm is rp-docx section 6's, unchanged, because the problem is:

1. Per paragraph, build a concatenated string plus a run-offset map
2. Locate matches against the concatenated string
3. Write the replacement into the run containing the match start; blank the
   tails of the runs it spanned
4. Inherit formatting from the first spanned run
5. Overlapping candidates resolve to the longer

The code cannot be imported from ``rp_docx`` — leaves never import each other
(parent spec section 10) — and the element shapes differ (``a:r``/``a:t`` under
``a:p`` against ``w:r``/``w:t`` under ``w:p``), so this is its own implementation
of the shared algorithm rather than a wrapper around one.

**Only ``a:r`` runs are touched.** An ``a:fld`` also carries an ``a:t``, but its
text is generated — a slide number, a date — and rewriting it would either be
overwritten on next render or corrupt the field. Whatever is in a field is not
the user's text to replace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rp_pptx.ooxml import qn, xpath

#: Set on an ``a:t`` whose text has leading or trailing whitespace, for the same
#: reason Word needs it: without it the renderer is free to strip the space, and
#: a replacement ending in one silently runs into the next word.
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass(frozen=True)
class Match:
    key: str
    start: int
    end: int
    replacement: str


@dataclass
class TextSpan:
    """One ``a:t`` and where its text sits in the concatenated paragraph."""

    node: Any
    run: Any
    start: int
    end: int


def _element(paragraph: Any) -> Any:
    """The ``a:p`` element, whether given one or a python-pptx paragraph."""
    return getattr(paragraph, "_p", paragraph)


def text_spans(paragraph: Any) -> list[TextSpan]:
    """Every ``a:t`` under ``a:r`` in document order, with its offsets."""
    spans: list[TextSpan] = []
    cursor = 0
    for run in xpath(_element(paragraph), "./a:r"):
        for node in run.findall(qn("a:t")):
            text = node.text or ""
            spans.append(TextSpan(node=node, run=run, start=cursor, end=cursor + len(text)))
            cursor += len(text)
    return spans


def paragraph_text(paragraph: Any) -> str:
    """The concatenated run text a match is located against."""
    return "".join(span.node.text or "" for span in text_spans(paragraph))


def find_matches(
    text: str, replacements: dict[str, str], *, ignore_case: bool = False
) -> list[Match]:
    """Every non-overlapping occurrence of any key, left to right.

    Where two keys could match at the same place — ``{{ name }}`` and
    ``{{ name }} suffix``, or ``ab`` and ``abc`` — the **longer** wins, and the
    shorter is not then matched inside it. Picking arbitrarily would make the
    result depend on dict ordering, which is not something a caller can see or
    control, and which makes the same call produce different decks on different
    runs.
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
    node.text = text
    if text != text.strip():
        node.set(XML_SPACE, "preserve")
    elif node.get(XML_SPACE) == "preserve":
        del node.attrib[XML_SPACE]


def _strip_formatting(run: Any) -> None:
    """Drop a run's direct formatting, leaving the placeholder's own appearance."""
    if run is None:
        return
    for properties in run.findall(qn("a:rPr")):
        run.remove(properties)


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


def replace_in_paragraph(
    paragraph: Any,
    replacements: dict[str, str],
    *,
    ignore_case: bool = False,
    preserve_formatting: bool = True,
) -> dict[str, int]:
    """Replace every occurrence in one paragraph. Returns key → count.

    The replacement lands in the run holding the match's *start* and so takes
    that run's formatting; the rest of the match is blanked out of the runs it
    spanned. With ``preserve_formatting=False`` the receiving run's direct
    formatting is dropped instead.

    Matches are applied right to left so that offsets taken from the original
    text stay valid as earlier text changes length.
    """
    spans = text_spans(paragraph)
    if not spans:
        return {}
    text = "".join(span.node.text or "" for span in spans)
    matches = find_matches(text, replacements, ignore_case=ignore_case)

    for match in reversed(matches):
        _apply(spans, match, preserve_formatting=preserve_formatting)

    counts: dict[str, int] = {}
    for match in matches:
        counts[match.key] = counts.get(match.key, 0) + 1
    return counts
