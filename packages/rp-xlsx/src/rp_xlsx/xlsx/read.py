"""Reading workbooks: index, data, cells, formulas, tables, names, comments,
images, charts, properties, markdown.

Every function returns a pydantic model or a list of them, takes and returns
``pathlib.Path``, and never prints. Sheet indices are 1-based and counted
across the whole workbook, matching every other user-facing index in the
suite.

**``get_index`` must never refuse a readable file** (spec section 6.2, 12 step
6): at-risk parts, an unreadable chart, a phantom dimension — none of them may
make it fail. Section 9's footguns are handled here one by one: declared
dimensions lie (``used_range`` vs ``declared_range``), merged cells report
``None`` on every spanned cell, dates always come back as ``datetime``, and a
formula's value and its cached value come from two different loads.

**Two loads, not one.** openpyxl cannot report a formula's text and its cached
value from a single ``load_workbook`` call (verified,
``dev-notes/phase-3-openpyxl-probe.md``) — one load with ``data_only=False``,
one with ``data_only=True``. ``get_cells`` always does both, because
``Cell`` carries both fields; ``get_data`` only opens the second workbook when
``values="cached"``.
"""

from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from rp_core.progress import NULL, Progress
from rp_xlsx import fidelity, ooxml, refs
from rp_xlsx.models import (
    Cell,
    CellComment,
    CellValue,
    ChartRef,
    ChartSeries,
    CoreProperties,
    EmbeddedImage,
    ExcelTable,
    NamedRange,
    SheetData,
    SheetInfo,
    WorkbookIndex,
)

#: Content types for the image formats openpyxl/Excel actually embed. Falls
#: back to ``image/<format>`` for anything not listed, which is right for
#: every common raster format and merely imprecise for the rare ones.
_IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "emf": "image/x-emf",
    "wmf": "image/x-wmf",
}

_ChartAxisAttrError = (AttributeError, TypeError, ValueError, IndexError)


# --- shared cell/range helpers ------------------------------------------------


def _used_bounds(ws: Any) -> tuple[int, int, int, int] | None:
    """The bounding box of cells that actually hold a value or a formula —
    section 9's ``used_range``, never the declared, possibly-phantom one.

    Deliberately does not stop at the first populated cell it can see:
    ``ws.dimensions``/``max_row`` already do that cheaply and lie (a
    format-only cell at row 5000 makes them report row 5000), which is the
    exact failure this function exists to avoid. Scans
    ``ooxml.populated_cells`` rather than ``ws.iter_rows()`` for the same
    reason in the other direction: the declared rectangle is exactly what a
    phantom dimension inflates, so walking it here would trade a wrong
    answer for a slow one instead of fixing it.
    """
    min_row = min_col = max_row = max_col = None
    for cell in ooxml.populated_cells(ws):
        if cell.value is None:
            continue
        r, c = cell.row, cell.column
        min_row = r if min_row is None else min(min_row, r)
        max_row = r if max_row is None else max(max_row, r)
        min_col = c if min_col is None else min(min_col, c)
        max_col = c if max_col is None else max(max_col, c)
    return None if min_row is None else (min_row, min_col, max_row, max_col)


def _format_range(bounds: tuple[int, int, int, int]) -> str:
    min_row, min_col, max_row, max_col = bounds
    return f"{refs.column_letters(min_col)}{min_row}:{refs.column_letters(max_col)}{max_row}"


def _resolve_read_range(ws: Any, cells: str | None) -> tuple[int, int, int, int] | None:
    """The bounding box a read actually covers.

    An explicit ``cells`` bound is honoured exactly as given — a caller asking
    for ``A1:Z100`` gets that rectangle even where it runs past the data. Only
    an *open* bound (``"B:B"``, ``"3:3"``) falls back to the sheet's used
    range, because 1..1,048,576 is not a sensible answer to "every row of
    column B" on a sheet with twenty rows of data.
    """
    used = _used_bounds(ws)
    if cells is None:
        return used
    a1 = refs.parse_a1_range(cells)
    fallback_min_row, fallback_min_col, fallback_max_row, fallback_max_col = used or (1, 1, 1, 1)
    return (
        a1.min_row if a1.min_row is not None else fallback_min_row,
        a1.min_col if a1.min_col is not None else fallback_min_col,
        a1.max_row if a1.max_row is not None else fallback_max_row,
        a1.max_col if a1.max_col is not None else fallback_max_col,
    )


def _merged_origins(ws: Any) -> set[tuple[int, int]]:
    return {(rng.min_row, rng.min_col) for rng in ws.merged_cells.ranges}


def _row_value(f_cell: Any, ws_values: Any, row: int, col: int, values: str) -> CellValue:
    """A single cell's value for ``get_data``'s grid, honouring ``values``."""
    if f_cell.data_type != "f":
        return f_cell.value
    if values == "formulas":
        return f_cell.value  # the formula text itself
    if ws_values is None:
        return None
    return ws_values.cell(row=row, column=col).value


def _cell_model(sheet_name: str, f_cell: Any, v_cell: Any, merged_origins: set) -> Cell:
    is_formula = f_cell.data_type == "f"
    if is_formula:
        formula = f_cell.value
        cached = v_cell.value if v_cell is not None else None
        value = cached
        value_available = cached is not None
    else:
        formula = None
        value = f_cell.value
        value_available = True
    return Cell(
        sheet=sheet_name,
        ref=f"{refs.column_letters(f_cell.column)}{f_cell.row}",
        row=f_cell.row,
        column=f_cell.column,
        value=value,
        formula=formula,
        value_available=value_available,
        number_format=f_cell.number_format,
        is_date=bool(getattr(f_cell, "is_date", False)),
        is_merged_origin=(f_cell.row, f_cell.column) in merged_origins,
    )


def _coerce_revision(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _core_properties(wb: Any) -> CoreProperties:
    source = wb.properties
    return CoreProperties(
        title=source.title or None,
        author=source.creator or None,
        last_modified_by=source.lastModifiedBy or None,
        created=source.created,
        modified=source.modified,
        revision=_coerce_revision(source.revision),
        category=source.category or None,
        keywords=source.keywords or None,
    )


def _defined_names(wb: Any) -> list[NamedRange]:
    """Workbook-scoped and sheet-scoped defined names, in that order."""
    names = [
        NamedRange(name=name, scope=None, refers_to=dn.value)
        for name, dn in wb.defined_names.items()
    ]
    for ws in wb.worksheets:
        names.extend(
            NamedRange(name=name, scope=ws.title, refers_to=dn.value)
            for name, dn in ws.defined_names.items()
        )
    return names


def _anchor_ref(anchor: Any) -> str | None:
    """A drawing anchor's origin cell, or ``None`` when it is not a simple
    one-cell/two-cell anchor openpyxl models this way."""
    try:
        origin = anchor._from
        return f"{refs.column_letters(origin.col + 1)}{origin.row + 1}"
    except AttributeError:
        return None


def _sheet_info(ws: Any, index: int) -> SheetInfo:
    formula_count = 0
    comment_count = 0
    for cell in ooxml.populated_cells(ws):
        if cell.data_type == "f":
            formula_count += 1
        if cell.comment is not None:
            comment_count += 1
    bounds = _used_bounds(ws)
    used_range = None
    rows = columns = 0
    if bounds is not None:
        used_range = _format_range(bounds)
        rows = bounds[2] - bounds[0] + 1
        columns = bounds[3] - bounds[1] + 1
    return SheetInfo(
        index=index,
        name=ws.title,
        state=ws.sheet_state,
        used_range=used_range,
        declared_range=ws.dimensions,
        rows=rows,
        columns=columns,
        formula_count=formula_count,
        merged_count=len(ws.merged_cells.ranges),
        table_count=len(ws.tables),
        chart_count=len(ws._charts),
        image_count=len(ws._images),
        comment_count=comment_count,
        freeze_panes=ws.freeze_panes,
        autofilter=ws.auto_filter.ref,
    )


# --- public API ----------------------------------------------------------


def get_properties(path: Path) -> CoreProperties:
    with ooxml.opened(path) as wb:
        return _core_properties(wb)


def get_index(path: Path) -> WorkbookIndex:
    """The workbook's shape at a glance — the default ``rp-xlsx`` command.

    Never refuses a readable file: the fidelity scan (section 6) never opens
    the workbook through openpyxl at all, and every per-sheet reader here is
    defensive by construction (bounded loops over what openpyxl already
    parsed, no raw-XML reach that could raise on something exotic).
    """
    report = fidelity.scan(path)
    with ooxml.opened(path) as wb:
        sheets = [_sheet_info(ws, i) for i, ws in enumerate(wb.worksheets, start=1)]
        defined_name_count = len(_defined_names(wb))
        props = _core_properties(wb)
    return WorkbookIndex(
        path=Path(path),
        format=ooxml.format_of(Path(path)),
        sheet_count=len(sheets),
        sheets=sheets,
        defined_name_count=defined_name_count,
        has_macros=report.macros_present,
        has_cached_values=report.cached_values_present,
        at_risk=report.at_risk,
        core_properties=props,
    )


def get_data(
    path: Path,
    *,
    sheets: str = "all",
    names: list[str] | None = None,
    cells: str | None = None,
    header: bool = True,
    max_rows: int | None = None,
    values: Literal["cached", "formulas"] = "cached",
    progress: Progress | None = None,
) -> list[SheetData]:
    """Selected sheets' data as a grid of values — never display strings
    (section 9): a cell showing ``25.00%`` reports ``0.25``.

    ``values="cached"`` merges a formula's last-computed value in (a second
    load, ``data_only=True``); ``values="formulas"`` reports the formula text
    itself and needs only one load.
    """
    reporter = progress if progress is not None else NULL
    result: list[SheetData] = []
    need_cached = values == "cached"
    # Every context manager is constructed *inside* the with-statement, in
    # the order it is entered, so the progress step is live before anything
    # touches the file -- constructing (not entering) the second one earlier
    # would cost nothing here, but AGENTS.md's rule is to keep the ordering
    # honest rather than rely on it happening to be harmless.
    with (
        reporter.step("Reading sheet data") as step,
        ooxml.opened(path) as wb_f,
        ooxml.opened(path, data_only=True) if need_cached else nullcontext(None) as wb_v,
    ):
        sheet_names = wb_f.sheetnames
        positions = refs.resolve_sheet_selection(sheet_names, sheets=sheets, names=names)
        step.set_total(len(positions))
        for position in positions:
            ws_f = wb_f.worksheets[position - 1]
            ws_v = wb_v.worksheets[position - 1] if wb_v is not None else None
            result.append(_sheet_data(ws_f, ws_v, position, cells, header, max_rows, values))
            step.advance()
    return result


def _sheet_data(
    ws_f: Any,
    ws_v: Any,
    position: int,
    cells: str | None,
    header: bool,
    max_rows: int | None,
    values: str,
) -> SheetData:
    bounds = _resolve_read_range(ws_f, cells)
    if bounds is None:
        return SheetData(
            sheet=ws_f.title,
            index=position,
            range=ws_f.dimensions,
            header=None,
            rows=[],
            truncated=False,
        )
    min_row, min_col, max_row, max_col = bounds
    range_str = _format_range(bounds)

    header_row: list[str] | None = None
    start_row = min_row
    if header:
        header_row = [
            _header_cell(_row_value(ws_f.cell(row=min_row, column=c), ws_v, min_row, c, values))
            for c in range(min_col, max_col + 1)
        ]
        start_row = min_row + 1

    rows: list[list[CellValue]] = []
    truncated = False
    for offset, row in enumerate(range(start_row, max_row + 1)):
        if max_rows is not None and offset >= max_rows:
            truncated = True
            break
        rows.append(
            [
                _row_value(ws_f.cell(row=row, column=col), ws_v, row, col, values)
                for col in range(min_col, max_col + 1)
            ]
        )
    return SheetData(
        sheet=ws_f.title,
        index=position,
        range=range_str,
        header=header_row,
        rows=rows,
        truncated=truncated,
    )


def _header_cell(value: CellValue) -> str:
    return "" if value is None else str(value)


def get_cells(
    path: Path,
    *,
    sheets: str = "all",
    names: list[str] | None = None,
    cells: str | None = None,
    empty: bool = False,
) -> list[Cell]:
    """Every selected cell, with both its formula and its cached value.

    Always two loads (section 9) — a ``Cell`` carries both fields, so there is
    no cheaper mode here the way ``get_data``'s ``values="formulas"`` is one.
    ``empty=False`` skips cells with no value and no formula, so a sparse
    sheet does not serialize a million nulls.
    """
    result: list[Cell] = []
    with ooxml.opened(path) as wb_f, ooxml.opened(path, data_only=True) as wb_v:
        sheet_names = wb_f.sheetnames
        positions = refs.resolve_sheet_selection(sheet_names, sheets=sheets, names=names)
        for position in positions:
            ws_f = wb_f.worksheets[position - 1]
            ws_v = wb_v.worksheets[position - 1]
            bounds = _resolve_read_range(ws_f, cells)
            if bounds is None:
                continue
            merged_origins = _merged_origins(ws_f)
            min_row, min_col, max_row, max_col = bounds
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    f_cell = ws_f.cell(row=row, column=col)
                    if not empty and f_cell.value is None:
                        continue
                    v_cell = ws_v.cell(row=row, column=col)
                    result.append(_cell_model(ws_f.title, f_cell, v_cell, merged_origins))
    return result


def get_formulas(path: Path, *, sheets: str = "all") -> list[Cell]:
    """Only the formula cells, across the selected sheets."""
    return [cell for cell in get_cells(path, sheets=sheets, empty=True) if cell.formula is not None]


def get_tables(path: Path, *, sheets: str = "all") -> list[ExcelTable]:
    result: list[ExcelTable] = []
    with ooxml.opened(path) as wb:
        positions = refs.resolve_sheet_selection(wb.sheetnames, sheets=sheets)
        for position in positions:
            ws = wb.worksheets[position - 1]
            # `ws.tables.items()` yields (name, ref-string) pairs, not (name,
            # Table) -- the object itself only comes back through
            # `ws.tables[name]`. The kind of "first thing that looks right"
            # trap AGENTS.md warns about; verified against openpyxl 3.1.5.
            for name in ws.tables:
                table = ws.tables[name]
                columns = [column.name for column in (table.tableColumns or [])]
                result.append(
                    ExcelTable(
                        name=name,
                        sheet=ws.title,
                        ref=table.ref,
                        header_row=bool(table.headerRowCount),
                        totals_row=bool(table.totalsRowCount),
                        style=table.tableStyleInfo.name if table.tableStyleInfo else None,
                        columns=columns,
                    )
                )
    return result


def get_names(path: Path) -> list[NamedRange]:
    with ooxml.opened(path) as wb:
        return _defined_names(wb)


def get_comments(path: Path, *, sheets: str = "all") -> list[CellComment]:
    """Classic per-cell comments on the selected sheets.

    **Threaded comments are read nowhere** (spec section 7) — openpyxl reads
    only classic comments, and this package does not reach past it to read
    the threaded-comment parts directly. ``at_risk``/``fidelity.scan`` is what
    tells a caller a workbook carries them; this function simply does not
    claim to report on what it cannot see. A workbook mixing both still
    returns its classic comments rather than refusing the whole read — unlike
    ``rp-pptx``'s deck-wide raise, a workbook with threaded comments is still
    a workbook whose cells read correctly.
    """
    result: list[CellComment] = []
    with ooxml.opened(path) as wb:
        positions = refs.resolve_sheet_selection(wb.sheetnames, sheets=sheets)
        for position in positions:
            ws = wb.worksheets[position - 1]
            for cell in ooxml.populated_cells(ws):
                comment = cell.comment
                if comment is None:
                    continue
                result.append(
                    CellComment(
                        sheet=ws.title,
                        ref=f"{refs.column_letters(cell.column)}{cell.row}",
                        author=(comment.author or None),
                        text=comment.text or "",
                    )
                )
    return result


def get_images(
    path: Path, *, sheets: str = "all", output_dir: Path | None = None
) -> list[EmbeddedImage]:
    """Pictures on the selected sheets, numbered across the whole workbook.

    Legacy embeds openpyxl cannot classify report ``width_px``/``height_px``
    as ``None`` rather than raising (section 9's "read defensively" rule,
    same as ``rp-pptx``'s image handling).
    """
    result: list[EmbeddedImage] = []
    index = 0
    directory = Path(output_dir) if output_dir else None
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
    with ooxml.opened(path) as wb:
        wanted = set(refs.resolve_sheet_selection(wb.sheetnames, sheets=sheets))
        for position, ws in enumerate(wb.worksheets, start=1):
            for image in ws._images:
                index += 1
                if position not in wanted:
                    continue
                result.append(_embedded_image(image, ws.title, index, directory))
    return result


def _embedded_image(
    image: Any, sheet_name: str, index: int, directory: Path | None
) -> EmbeddedImage:
    fmt = (image.format or "").lower()
    filename = (
        Path(image.path).name if getattr(image, "path", None) else f"image-{index}.{fmt or 'bin'}"
    )
    content_type = _IMAGE_CONTENT_TYPES.get(
        fmt, f"image/{fmt}" if fmt else "application/octet-stream"
    )
    data = _image_bytes(image)
    width = height = None
    if data:
        try:
            with PILImage.open(BytesIO(data)) as pil:
                width, height = pil.size
        except (UnidentifiedImageError, OSError):
            width = height = None
    extracted = None
    if directory and data:
        extracted = directory / f"image-{index:03d}-{filename}"
        extracted.write_bytes(data)
    return EmbeddedImage(
        index=index,
        sheet=sheet_name,
        anchor=_anchor_ref(getattr(image, "anchor", None)),
        filename=filename,
        content_type=content_type,
        width_px=width,
        height_px=height,
        extracted_path=extracted,
    )


def _image_bytes(image: Any) -> bytes | None:
    try:
        ref = image.ref
        if hasattr(ref, "getvalue"):
            return ref.getvalue()
        if isinstance(ref, (bytes, bytearray)):
            return bytes(ref)
    except (AttributeError, OSError):
        pass
    return None


def _chart_title_text(chart: Any) -> str | None:
    try:
        title = chart.title
        if title is None or title.tx is None or title.tx.rich is None:
            return None
        parts = [run.t for paragraph in title.tx.rich.p for run in (paragraph.r or []) if run.t]
        text = "".join(parts).strip()
        return text or None
    except _ChartAxisAttrError:
        return None


def _series_name(series: Any) -> str | None:
    """A series' literal title text, when it has one.

    A series titled from a cell reference (``tx.strRef``) is left ``None`` —
    resolving it would mean evaluating a reference, which this package never
    does (section 4's rule for values/categories applies here too).
    """
    tx = getattr(series, "tx", None)
    return (tx.v or None) if tx is not None else None


def _ref_of(source: Any) -> str | None:
    """The cell reference a chart data source points at — never its values."""
    if source is None:
        return None
    for attr in ("numRef", "strRef"):
        sub = getattr(source, attr, None)
        formula = getattr(sub, "f", None) if sub is not None else None
        if formula:
            return formula
    return None


def get_charts(path: Path, *, sheets: str = "all") -> list[ChartRef]:
    """Charts on the selected sheets, numbered across the whole workbook.

    Read defensively (section 9): anything openpyxl cannot model reports its
    type with ``data_available: false`` rather than raising. One exotic chart
    must not sink the whole read.
    """
    result: list[ChartRef] = []
    index = 0
    with ooxml.opened(path) as wb:
        wanted = set(refs.resolve_sheet_selection(wb.sheetnames, sheets=sheets))
        for position, ws in enumerate(wb.worksheets, start=1):
            for chart in ws._charts:
                index += 1
                if position not in wanted:
                    continue
                result.append(_chart_ref(chart, ws.title, index))
    return result


def _chart_ref(chart: Any, sheet_name: str, index: int) -> ChartRef:
    chart_type = type(chart).__name__
    try:
        series = [
            ChartSeries(
                name=_series_name(s),
                values_ref=_ref_of(getattr(s, "val", None)),
                categories_ref=_ref_of(getattr(s, "cat", None)),
            )
            for s in getattr(chart, "series", [])
        ]
        return ChartRef(
            index=index,
            sheet=sheet_name,
            chart_type=chart_type,
            title=_chart_title_text(chart),
            anchor=_anchor_ref(getattr(chart, "anchor", None)),
            series=series,
            data_available=True,
        )
    except _ChartAxisAttrError:
        return ChartRef(
            index=index,
            sheet=sheet_name,
            chart_type=chart_type,
            title=None,
            anchor=None,
            series=[],
            data_available=False,
        )


def get_markdown(
    path: Path,
    *,
    sheets: str = "all",
    names: list[str] | None = None,
    cells: str | None = None,
    max_rows: int | None = 200,
) -> str:
    """Selected sheets rendered as GFM: a heading per sheet, then a pipe table."""
    data = get_data(path, sheets=sheets, names=names, cells=cells, header=True, max_rows=max_rows)
    chunks: list[str] = []
    for sheet in data:
        chunks.append(f"## {sheet.sheet}")
        chunks.append("")
        chunks.extend(_markdown_table(sheet))
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def _markdown_table(sheet: SheetData) -> list[str]:
    if not sheet.rows and not sheet.header:
        return ["*(no data)*"]
    width = len(sheet.header) if sheet.header else (len(sheet.rows[0]) if sheet.rows else 0)
    header = sheet.header or [refs.column_letters(i) for i in range(1, width + 1)]
    lines = ["| " + " | ".join(_md_cell(v) for v in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in sheet.rows:
        lines.append("| " + " | ".join(_md_cell(v) for v in row) + " |")
    return lines


def _md_cell(value: CellValue) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


__all__ = [
    "get_cells",
    "get_charts",
    "get_comments",
    "get_data",
    "get_formulas",
    "get_images",
    "get_index",
    "get_markdown",
    "get_names",
    "get_properties",
    "get_tables",
]
