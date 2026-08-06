"""A small Markdown block/inline parser, shared by every leaf package.

Promoted out of ``rp_docx.docx.write`` by rp-pptx-spec section 12 step 2. Parsing
Markdown into a block/inline AST is format-agnostic in the same way zip handling
is — there is no OOXML identifier anywhere near it — so the parser lives here and
each leaf keeps only its own renderer over the shared AST.

The grammar is deliberately small: headings, paragraphs, bullet and numbered
lists, GFM pipe tables, fenced code, thematic breaks, HTML comments, and the
inline spans (bold, italic, code, links) that rp-docx-spec section 9 lists. It is
not a CommonMark implementation and does not try to be. Nesting of emphasis is
out of scope — that is where a hand-rolled parser starts guessing.

**Block kinds are contract.** Renderers dispatch on :attr:`Block.kind`, so adding
a kind is additive but renaming one breaks every leaf at once.

``comment`` is the one kind rp-docx never emitted, and the one addition
rp-pptx-spec section 12 step 2 asks for: section 9 there maps an HTML comment
block to a slide's speaker notes (the Marp convention), so the parser has to
surface comments as nodes rather than letting them fall through to a paragraph.
Renderers with no use for them ignore the kind, which is what rp-docx's does —
its block dispatch has no ``else``, so an unhandled kind renders as nothing.

Markdown images are deliberately *not* a block kind. rp-pptx-spec section 9 wants
a lone image on a slide, but promoting that here would change what rp-docx does
with an image line today (it renders the alt text and hyperlink through the
inline parser), and nothing in the spec asks for that. The pptx renderer matches
image-only paragraphs itself; if a second leaf ever needs the same thing, that is
the point to promote it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "Block",
    "BlockKind",
    "Span",
    "parse_inline",
    "parse_markdown",
    "split_row",
]

BlockKind = Literal[
    "heading",
    "paragraph",
    "bullet",
    "numbered",
    "table",
    "rule",
    "code",
    "comment",
]


@dataclass
class Block:
    """One markdown block, already classified."""

    kind: BlockKind
    text: str = ""
    level: int = 0
    rows: list[list[str]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_FENCE = re.compile(r"^\s*```")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
_COMMENT_OPEN = re.compile(r"^\s*<!--")
_COMMENT_CLOSE = re.compile(r"-->\s*$")

#: Inline spans, longest-delimiter first so ``**bold**`` is not read as two
#: italics. Link before emphasis so a link label can carry emphasis inside it.
_INLINE = re.compile(
    r"(?P<link>\[(?P<label>[^\]]*)\]\((?P<href>[^)\s]+)\))"
    r"|(?P<code>`[^`]+`)"
    r"|(?P<bold>\*\*[^*]+\*\*|__[^_]+__)"
    r"|(?P<italic>\*[^*]+\*|_[^_]+_)"
)


@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str | None = None


def parse_inline(text: str) -> list[Span]:
    """Split a line into formatted spans. Nested emphasis is not supported —
    the grammar stops at single spans, and nesting is where a hand-rolled parser
    starts guessing."""
    spans: list[Span] = []
    position = 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            spans.append(Span(text[position : match.start()]))
        if match.group("link"):
            spans.append(Span(match.group("label"), href=match.group("href")))
        elif match.group("code"):
            spans.append(Span(match.group("code")[1:-1], code=True))
        elif match.group("bold"):
            spans.append(Span(match.group("bold")[2:-2], bold=True))
        else:
            spans.append(Span(match.group("italic")[1:-1], italic=True))
        position = match.end()
    if position < len(text):
        spans.append(Span(text[position:]))
    return [span for span in spans if span.text] or ([Span(text)] if text else [])


def split_row(line: str) -> list[str]:
    """One pipe-table row, split into trimmed cells."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def parse_markdown(text: str) -> list[Block]:
    """Markdown to blocks. Everything the shared grammar covers, and no more."""
    blocks: list[Block] = []
    lines = text.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]

        if _FENCE.match(line):
            index += 1
            body: list[str] = []
            while index < len(lines) and not _FENCE.match(lines[index]):
                body.append(lines[index])
                index += 1
            blocks.append(Block(kind="code", lines=body))
            index += 1
            continue

        # HTML comments are surfaced, not skipped: rp-pptx maps them to speaker
        # notes. They may span lines, and an unterminated one runs to the end
        # rather than swallowing the parser.
        if _COMMENT_OPEN.match(line):
            body = []
            while index < len(lines):
                body.append(lines[index])
                closed = bool(_COMMENT_CLOSE.search(lines[index]))
                index += 1
                if closed:
                    break
            joined = "\n".join(body).strip()
            inner = joined.removeprefix("<!--").removesuffix("-->").strip()
            blocks.append(Block(kind="comment", text=inner, lines=body))
            continue

        if not line.strip():
            index += 1
            continue

        if _RULE.match(line):
            blocks.append(Block(kind="rule"))
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            blocks.append(
                Block(
                    kind="heading",
                    # Capped at 4 deliberately: rp-docx maps levels onto h1-h4
                    # style roles and has nothing to say about deeper ones, and
                    # rp-pptx treats level 3 and deeper alike (a bold lead-in
                    # bullet, not a slide). Raising the cap breaks the former.
                    level=min(len(heading.group(1)), 4),
                    text=heading.group(2).strip(),
                )
            )
            index += 1
            continue

        # A pipe table is a header row followed by a divider; without the
        # divider it is a paragraph that happens to contain pipes.
        if "|" in line and index + 1 < len(lines) and _TABLE_DIVIDER.match(lines[index + 1]):
            rows = [split_row(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(split_row(lines[index]))
                index += 1
            blocks.append(Block(kind="table", rows=rows))
            continue

        bullet = _BULLET.match(line)
        if bullet:
            blocks.append(
                Block(
                    kind="bullet",
                    level=len(bullet.group(1)) // 2 + 1,
                    text=bullet.group(2).strip(),
                )
            )
            index += 1
            continue

        numbered = _NUMBERED.match(line)
        if numbered:
            blocks.append(
                Block(
                    kind="numbered",
                    level=len(numbered.group(1)) // 2 + 1,
                    text=numbered.group(2).strip(),
                )
            )
            index += 1
            continue

        # A paragraph runs to the next blank line; markdown's soft wrapping
        # means a wrapped sentence is one paragraph, not several.
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not _is_block_start(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(Block(kind="paragraph", text=" ".join(paragraph)))
    return blocks


def _is_block_start(line: str) -> bool:
    return bool(
        _HEADING.match(line)
        or _BULLET.match(line)
        or _NUMBERED.match(line)
        or _RULE.match(line)
        or _FENCE.match(line)
        or _COMMENT_OPEN.match(line)
    )
