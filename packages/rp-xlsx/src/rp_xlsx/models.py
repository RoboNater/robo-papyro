"""Pydantic models for spreadsheets — xlsx-specific shapes only.

Owned by ``rp_core`` and never redefined here: ``Capability``, ``ErrorDetail``,
``ErrorEnvelope``, ``CoreProperties``, the exception hierarchy, range parsing,
binary discovery, and rasterization. If a model here starts looking
format-agnostic, it belongs upstream.

**Every user-facing index is 1-based** — sheets, rows, columns, tables,
images — matching the rest of the suite. These models are the CLI's JSON
payload as much as they are the library's return type, so a field rename is a
breaking change to both.

**``CellValue``'s union order is load-bearing.** Pydantic's union coercion
will happily turn ``True`` into ``1`` in the wrong order — ``bool`` is
declared first below, and ``tests/test_models_xlsx.py`` asserts a boolean cell
round-trips as ``true``, not ``1``. This has bitten every codebase that has
ever serialized a spreadsheet (spec section 3).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from rp_core.models import CoreProperties  # noqa: F401 -- re-exported for callers

XlsxFormat = Literal["xlsx", "xlsm", "xltx", "xltm"]

#: A cell's value. ``bool`` must stay first: pydantic's left-to-right union
#: coercion otherwise turns ``True`` into ``1`` via the ``float``/``int`` arms.
CellValue = bool | str | float | int | datetime | None

SheetState = Literal["visible", "hidden", "veryHidden"]


class SheetInfo(BaseModel):
    index: int  # 1-based position in the workbook
    name: str
    state: SheetState
    used_range: str | None  # "A1:D20"; None for a genuinely empty sheet — §9
    declared_range: str  # what the file claims (ws.dimensions) — §9
    rows: int  # rows in used_range, not in declared_range
    columns: int
    formula_count: int
    merged_count: int
    table_count: int
    chart_count: int
    image_count: int
    comment_count: int
    freeze_panes: str | None
    autofilter: str | None


class AtRiskPart(BaseModel):
    category: str  # "threaded_comments", "pivot_cache", "slicer", ...
    part: str  # the part name in the package
    detail: str  # what a save would do to it


class WorkbookIndex(BaseModel):
    path: Path
    format: XlsxFormat
    sheet_count: int
    sheets: list[SheetInfo]
    defined_name_count: int
    has_macros: bool  # an xl/vbaProject.bin part is present
    has_cached_values: bool  # at least one formula carries a cached <v> — §6
    at_risk: list[AtRiskPart]  # part categories an edit would drop — §6
    core_properties: CoreProperties


class Cell(BaseModel):
    sheet: str
    ref: str  # "B5"
    row: int  # 1-based
    column: int  # 1-based
    value: CellValue
    formula: str | None  # "=SUM(B2:B4)"; None when the cell is not a formula
    value_available: bool  # False for a formula with no cached value — §6
    number_format: str  # "General", "0.00%", "yyyy-mm-dd"
    is_date: bool
    is_merged_origin: bool


class SheetData(BaseModel):
    sheet: str
    index: int
    range: str  # the range actually returned
    header: list[str] | None  # first row, when header=True
    rows: list[list[CellValue]]  # values only — see §9 on display strings
    truncated: bool  # max_rows cut the result short


class ExcelTable(BaseModel):
    """An Excel table object (ListObject) — not a Markdown or docx table."""

    name: str
    sheet: str
    ref: str
    header_row: bool
    totals_row: bool
    style: str | None
    columns: list[str]


class NamedRange(BaseModel):
    name: str
    scope: str | None  # sheet name for a sheet-scoped name; None if workbook-scoped
    refers_to: str


class CellComment(BaseModel):
    sheet: str
    ref: str
    author: str | None
    text: str


class EmbeddedImage(BaseModel):
    index: int
    sheet: str
    anchor: str | None  # "C3"; None when the anchor is not a simple cell anchor
    filename: str
    content_type: str
    width_px: int | None  # None for formats Pillow cannot read
    height_px: int | None
    extracted_path: Path | None


class ChartSeries(BaseModel):
    name: str | None
    values_ref: str | None  # the reference, not the values — we do not evaluate
    categories_ref: str | None


class ChartRef(BaseModel):
    index: int
    sheet: str
    chart_type: str
    title: str | None
    anchor: str | None
    series: list[ChartSeries]
    data_available: bool  # False when openpyxl cannot model this chart


class FidelityReport(BaseModel):
    """What editing this workbook with openpyxl would cost. — §6"""

    path: Path
    safe_to_edit: bool
    at_risk: list[AtRiskPart]
    cached_values_present: bool  # True means an edit discards them
    macros_present: bool


class WriteResult(BaseModel):
    output: Path
    cells_written: int
    recalculation_required: bool  # the source had formulas whose cached values are now gone
    dropped: list[AtRiskPart]  # non-empty only when allow_lossy let a write through


class ReplaceResult(BaseModel):
    output: Path
    replacements: dict[str, int]  # key -> count; unmatched keys report 0
    locations: list[str]  # "Sheet1!B4", "header:Sheet1"
    recalculation_required: bool


class SheetOpResult(BaseModel):
    output: Path
    sheet_count: int  # after the operation
    sheets: list[str]  # names, in order, after the operation


class FillResult(BaseModel):
    output: Path
    filled: dict[str, str]
    unresolved: list[str]


class SheetSpec(BaseModel):
    """One sheet's worth of rows, as ``create`` takes it regardless of source
    (CSV, JSON, or a Markdown table — spec section 9)."""

    name: str
    rows: list[list[CellValue]]
    header: list[str] | None = None
    column_widths: dict[str, float] | None = None
    freeze_header: bool = False


class TemplateInfo(BaseModel):
    name: str
    path: Path
    format: XlsxFormat
    sheets: list[SheetInfo]
    defined_names: list[NamedRange]
    placeholders: list[str]  # the {{ keys }} the template contains — §5.2


class SheetShape(BaseModel):
    index: int
    name: str
    state: SheetState
    used_range: str | None
    header: list[str] | None  # the header row, which is structure — §5.2 explains
    column_widths: dict[str, float]
    freeze_panes: str | None
    number_formats: dict[str, str]  # column letter -> format, where the column is uniform
    table_names: list[str]
    placeholder_cells: dict[str, str]  # "B2" -> "{{ client.name }}"


class TemplateManifest(BaseModel):
    """Redacted-by-construction description of a template's shape. — §5.2"""

    name: str
    format: XlsxFormat
    sheets: list[SheetShape]
    defined_names: list[NamedRange]
    placeholders: list[str]
    image_count: int  # logo presence, not logo bytes


__all__ = [
    "AtRiskPart",
    "Cell",
    "CellComment",
    "CellValue",
    "ChartRef",
    "ChartSeries",
    "CoreProperties",
    "EmbeddedImage",
    "ExcelTable",
    "FidelityReport",
    "FillResult",
    "NamedRange",
    "ReplaceResult",
    "SheetData",
    "SheetInfo",
    "SheetOpResult",
    "SheetShape",
    "SheetSpec",
    "SheetState",
    "TemplateInfo",
    "TemplateManifest",
    "WorkbookIndex",
    "WriteResult",
    "XlsxFormat",
]
