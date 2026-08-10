"""Pydantic models for Word documents — docx-specific shapes only.

Owned by ``rp_core`` and never redefined here: ``Capability``, ``ErrorDetail``,
``ErrorEnvelope``, the exception hierarchy, range parsing, binary discovery, and
rasterization. If a model here starts looking format-agnostic, it belongs
upstream.

**Every user-facing index is 1-based** — paragraphs, tables, images, sections —
matching the rest of the suite. These models are the CLI's JSON payload as much
as they are the library's return type, so a field rename is a breaking change to
both.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from rp_core.models import CoreProperties  # noqa: F401 -- re-exported; see class docstring there

#: OOXML's own ``w:style/@w:type`` vocabulary. python-docx spells the last one
#: ``LIST``; the OOXML attribute value is ``numbering``, and that is what these
#: models report, because it is the name in the file rather than in one library.
StyleType = Literal["paragraph", "character", "table", "numbering"]


class Run(BaseModel):
    """One ``w:r`` — a stretch of text sharing formatting.

    Word splits a logical string across runs for reasons that have nothing to do
    with meaning (spellcheck state, revision ids), so run boundaries are an
    artifact of the editor, not of the document. See ``rp_docx.docx.runs``.
    """

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font: str | None = None
    size_pt: float | None = None
    color: str | None = None


class Heading(BaseModel):
    index: int
    level: int
    text: str
    style: str


class Paragraph(BaseModel):
    index: int
    text: str
    style: str
    list_level: int | None = None
    #: Populated only when the caller asks for runs; ``None`` means "not
    #: requested", which is different from "this paragraph has no runs".
    runs: list[Run] | None = None


class Table(BaseModel):
    index: int
    rows: int
    cols: int
    data: list[list[str]]
    style: str | None = None
    #: Text of the nearest preceding heading, so a table found by search can be
    #: placed in the document without re-reading it.
    section_context: str | None = None


class EmbeddedImage(BaseModel):
    index: int
    rel_id: str
    filename: str
    content_type: str
    width_px: int | None = None
    height_px: int | None = None
    alt_text: str | None = None
    #: Where the bytes were written, when an output directory was given.
    extracted_path: Path | None = None


class Comment(BaseModel):
    id: str
    author: str
    initials: str | None = None
    date: datetime | None = None
    text: str
    anchor_text: str | None = None
    para_id: str | None = None
    #: From ``word/commentsExtended.xml``, a part that may not exist; ``False``
    #: then, because an unrecorded comment is an open one.
    resolved: bool = False


class TrackedChange(BaseModel):
    id: str
    type: Literal["insertion", "deletion", "format"]
    author: str
    date: datetime | None = None
    text: str
    paragraph_index: int


class DocumentIndex(BaseModel):
    """A document's shape at a glance — the default `rp-docx` command."""

    path: Path
    paragraph_count: int
    word_count: int
    section_count: int
    table_count: int
    image_count: int
    comment_count: int
    tracked_change_count: int
    has_headers_footers: bool
    styles_used: list[str]
    headings: list[Heading]
    core_properties: CoreProperties


class StyleDef(BaseModel):
    name: str
    type: StyleType
    builtin: bool
    base_style: str | None = None


class StyleMap(BaseModel):
    """Logical role → the style name a particular template uses for it.

    House templates rarely use Word's built-in names, so Markdown conversion
    goes through this rather than hardcoding ``"Heading 1"``. Loaded from an
    optional ``<template>.stylemap.json`` beside the template; the defaults
    below are Word's built-ins, which is what a template built from python-docx's
    default already has.
    """

    h1: str = "Heading 1"
    h2: str = "Heading 2"
    h3: str = "Heading 3"
    h4: str = "Heading 4"
    body: str = "Normal"
    bullet: str = "List Bullet"
    numbered: str = "List Number"
    #: **Optional, and the only role that is.** Word ships no code style at all,
    #: so every other default here names a style that genuinely exists while a
    #: default for this one could only name a style that might not. ``None``
    #: means "this template has no code style", and code blocks are rendered in
    #: the body style with a monospace font — the most a template without one
    #: can express. Naming a style here makes it *required*, exactly like the
    #: others: a stylemap that names a missing style still fails loudly.
    #:
    #: Spec section 3 gives this as ``code: str = "Source Code"``, which is
    #: pandoc's name for the style it applies to code blocks — not a name Word
    #: defines. On Word's own defaults it makes every markdown document
    #: containing a code block fail. See the spec-corrections list in
    #: dev-notes/status-robo-papyro-phase-1.md.
    code: str | None = None
    table: str = "Table Grid"


class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["dotx", "docx"]
    styles: list[StyleDef]
    page_size: str
    has_letterhead: bool


class TemplateManifest(BaseModel):
    """Redacted-by-construction description of a template's shape.

    Carries structure only — style names, page geometry, presence flags. Never
    document text, never image bytes, never author names, never a path beyond
    the template's own basename. Safe to commit and to share outside the
    environment holding the original template.

    **Redaction is a correctness property, not a convention** (spec section
    5.2): ``tests/test_templates.py`` asserts that a manifest built from a
    template full of distinctive body text contains none of it. A field that
    would break that assertion does not belong in this model.
    """

    name: str
    format: Literal["dotx", "docx"]
    styles: list[StyleDef]
    page_size: str
    page_margins_twips: dict[str, int] | None = None
    default_paragraph_style: str | None = None
    has_letterhead: bool = False
    header_image_count: int = 0
    footer_present: bool = False
    section_count: int = 1
    stylemap: StyleMap | None = None


class ReplaceResult(BaseModel):
    output: Path
    #: placeholder → number of occurrences replaced.
    replacements: dict[str, int]
    #: Where they were: ``"body"``, ``"table:2"``, ``"header:1"``, ``"footer:1"``.
    #: Body-only replacement is the classic silent bug, so this reports the
    #: story parts as well and a caller can see when nothing outside the body
    #: was touched.
    locations: list[str]


class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]


class ConversionResult(BaseModel):
    """Where a `convert` wrote its output, and in what format."""

    source: Path
    output: Path
    format: str


class RenderResult(BaseModel):
    """One rendered page image. Physical page numbers only — a Word document
    has no page labels, and rp-core has no concept of one either."""

    page: int
    path: Path


class WriteResult(BaseModel):
    """A write command's outcome, for the commands whose only result is a file."""

    output: Path


__all__ = [
    "Comment",
    "ConversionResult",
    "CoreProperties",
    "DocumentIndex",
    "EmbeddedImage",
    "FillResult",
    "Heading",
    "Paragraph",
    "RenderResult",
    "ReplaceResult",
    "Run",
    "StyleDef",
    "StyleMap",
    "StyleType",
    "Table",
    "TemplateInfo",
    "TemplateManifest",
    "TrackedChange",
    "WriteResult",
]
