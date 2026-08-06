from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Run(BaseModel):
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font: str | None = None
    size_pt: float | None = None
    color: str | None = None


class Paragraph(BaseModel):
    text: str
    level: int = 0
    runs: list[Run] | None = None


class SlideTitle(BaseModel):
    index: int
    layout: str
    title: str | None = None


class SlideText(SlideTitle):
    paragraphs: list[Paragraph]


class MergeSpan(BaseModel):
    row: int
    col: int
    row_span: int
    col_span: int


class Table(BaseModel):
    index: int
    slide_index: int
    rows: int
    cols: int
    data: list[list[str]]
    merges: list[MergeSpan] = []


class EmbeddedImage(BaseModel):
    index: int
    slide_index: int
    rel_id: str
    filename: str
    content_type: str
    width_px: int | None = None
    height_px: int | None = None
    alt_text: str | None = None
    extracted_path: Path | None = None


class SpeakerNotes(BaseModel):
    slide_index: int
    text: str


class Comment(BaseModel):
    id: str
    author: str
    initials: str | None = None
    date: datetime | None = None
    text: str
    slide_index: int
    parent_id: str | None = None


class ChartSeries(BaseModel):
    name: str | None = None
    values: list[float | None]


class ChartRef(BaseModel):
    index: int
    slide_index: int
    chart_type: str
    title: str | None = None
    categories: list[str] = []
    series: list[ChartSeries] = []
    data_available: bool = True


class CoreProperties(BaseModel):
    title: str | None = None
    author: str | None = None
    last_modified_by: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    revision: int | None = None
    category: str | None = None
    keywords: str | None = None


class PresentationIndex(BaseModel):
    path: Path
    slide_count: int
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str
    master_count: int
    layout_names: list[str]
    image_count: int
    table_count: int
    chart_count: int
    notes_count: int
    comment_count: int | None
    titles: list[SlideTitle]
    core_properties: CoreProperties


class PlaceholderDef(BaseModel):
    idx: int
    type: str
    name: str


class LayoutDef(BaseModel):
    name: str
    index: int
    placeholders: list[PlaceholderDef]


class LayoutMap(BaseModel):
    title: str = "Title Slide"
    section: str = "Section Header"
    content: str = "Title and Content"
    blank: str = "Blank"


class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: Literal["potx", "pptx"]
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str
    master_count: int
    layouts: list[LayoutDef]


class TemplateManifest(BaseModel):
    name: str
    format: Literal["potx", "pptx"]
    slide_width_emu: int
    slide_height_emu: int
    aspect_ratio: str
    master_count: int
    layouts: list[LayoutDef]
    master_image_count: int = 0
    notes_master_present: bool = False
    layoutmap: LayoutMap | None = None


class ReplaceResult(BaseModel):
    output: Path
    replacements: dict[str, int]
    locations: list[str]


class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]


class SlideOpResult(BaseModel):
    output: Path
    slide_count: int


class WriteResult(BaseModel):
    """A write command's outcome, for commands whose only result is a file."""

    output: Path


class ConversionResult(BaseModel):
    """Where a ``convert`` wrote its output, and in what format."""

    source: Path
    output: Path
    format: str


class RenderResult(BaseModel):
    """One rendered slide image. A slide is a page, so these are page numbers."""

    page: int
    path: Path
