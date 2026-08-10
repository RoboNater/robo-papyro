"""Typer CLI wrapping rp_xlsx. Parses args, calls the library, serializes output.

Conventions, all inherited from ``rp_core.clikit`` rather than restated here:

* **JSON to stdout by default**; ``--plain`` is the human opt-out. There is no
  ``--json`` flag anywhere in the suite (parent spec section 4.6).
* Errors are an ``ErrorEnvelope`` on **stderr**, with the exit code carried by
  the error class: 1 for input errors, 2 for a missing external binary, 3 for an
  unreadable or unsupported file — including ``LossyEditError`` (spec section 6).
* **Never overwrite an input file** without ``--in-place``. Every editing command
  insists on ``-o`` or ``--in-place`` and says so rather than guessing.
* ``--allow-lossy`` appears on every command that writes to an existing
  workbook, and nowhere else — never on ``create`` or ``template``, which
  never open one.

Options are options and arguments are arguments: a typer parameter without a
default silently becomes a positional argument instead, so each one is
spelled out with ``typer.Option`` rather than left to inference.

Rendering and conversion are thin re-exports of ``rp_core`` — no rendering
implementation lives in this package (spec section 4).
"""

from __future__ import annotations

import enum
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from rp_core import binaries, clikit
from rp_core import render as core_render
from rp_xlsx import fidelity as fidelity_module
from rp_xlsx import templates as templates_module
from rp_xlsx.errors import RpXlsxError
from rp_xlsx.models import (
    ConversionResult,
    FileWritten,
    RenderResult,
    SheetSpec,
    TemplateManifest,
)
from rp_xlsx.xlsx import read, write
from rp_xlsx.xlsx import sheets as sheets_module
from rp_xlsx.xlsx import tabular as tabular_module
from rp_xlsx.xlsx import template as template_module

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rp-xlsx — spreadsheet toolkit (JSON-first library and CLI).",
)
sheets_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Add, delete, rename, and reorder sheets."
)
templates_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Inspect and build house templates."
)
app.add_typer(sheets_app, name="sheets")
app.add_typer(templates_app, name="templates")

# On Windows, redirected output defaults to the legacy code page, which cannot
# encode arbitrary sheet text. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


#: Canonical subcommand names, held to spec section 10 by
#: tests/test_invariants_xlsx.py in both directions: a command in the code but
#: not here is an untested addition, and one here but not in the code is a
#: documented command that does not exist.
COMMAND_NAMES = frozenset(
    {
        "append",
        "cells",
        "charts",
        "comments",
        "convert",
        "create",
        "data",
        "doctor",
        "fidelity",
        "formulas",
        "images",
        "index",
        "markdown",
        "names",
        "props",
        "render",
        "replace",
        "set",
        "sheets",
        "tables",
        "template",
        "templates",
    }
)
SHEETS_COMMAND_NAMES = frozenset({"add", "delete", "list", "rename", "reorder"})
TEMPLATES_COMMAND_NAMES = frozenset({"inspect", "list", "manifest", "synthesize"})


FileArg = Annotated[Path, typer.Argument(help="The .xlsx, .xlsm, .xltx, or .xltm file")]
OutFileOpt = Annotated[Path | None, typer.Option("--out", "-o", help="Write here")]
InPlaceOpt = Annotated[bool, typer.Option("--in-place", help="Overwrite the input file")]
AllowLossyOpt = Annotated[
    bool,
    typer.Option(
        "--allow-lossy",
        help="Proceed even if this edit would drop parts openpyxl cannot model",
    ),
]
SheetsOpt = Annotated[
    str, typer.Option("--sheets", help="Sheet position spec: 'all', '2', '1-3', '2,4'")
]
SheetOpt = Annotated[
    list[str] | None, typer.Option("--sheet", help="Sheet name (not position); repeatable")
]
CellsOpt = Annotated[str | None, typer.Option("--cells", help="A1 range: 'A1:D20', 'B:B', '3:3'")]


def _errors():
    return clikit.error_handler()


def _job(title: str, entries: clikit.JobEntries, describe: bool | None, progress: bool | None):
    """Describe and report on a job, on stderr, when a human is watching.

    Only ``convert`` and ``render`` take these options: they are the two
    commands that shell out to LibreOffice and poppler, where a run takes
    long enough for silence to be ambiguous. Everything else here is
    in-process and finishes before a progress line would repaint once.
    """
    return clikit.job(
        title,
        entries,
        describe=clikit.display_enabled(describe),
        progress=clikit.display_enabled(progress),
    )


def _destination(file: Path, out: Path | None, in_place: bool) -> Path:
    """Where an editing command writes, or a refusal to guess (spec section 10)."""
    if out is not None and in_place:
        raise RpXlsxError("Pass either --out or --in-place, not both.")
    if in_place:
        return file
    if out is None:
        raise RpXlsxError(
            "Refusing to guess an output path: pass --out to write a copy, "
            "or --in-place to overwrite the input."
        )
    return out


def _json_value(value: str, *, what: str) -> Any:
    """A JSON value given either as a path or inline (spec section 10)."""
    candidate = Path(value)
    try:
        text = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    except OSError as exc:
        raise RpXlsxError(f"Cannot read {what} from {value}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RpXlsxError(f"{what} is not valid JSON: {exc}") from exc


def _json_object(value: str, *, what: str) -> dict:
    parsed = _json_value(value, what=what)
    if not isinstance(parsed, dict):
        raise RpXlsxError(f"{what} must be a JSON object, not {type(parsed).__name__}.")
    return parsed


def _json_array(value: str, *, what: str) -> list:
    parsed = _json_value(value, what=what)
    if not isinstance(parsed, list):
        raise RpXlsxError(f"{what} must be a JSON array, not {type(parsed).__name__}.")
    return parsed


def _sheet_data_csv(sheet: Any) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if sheet.header:
        writer.writerow(sheet.header)
    for row in sheet.rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def _sheet_data_md(sheet: Any) -> str:
    width = len(sheet.header) if sheet.header else (len(sheet.rows[0]) if sheet.rows else 0)
    header = sheet.header or [f"col{i}" for i in range(1, width + 1)]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in sheet.rows:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


# --- reads ---------------------------------------------------------------


@app.command()
def index(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Overview of a workbook: sheets, formulas, defined names, at-risk parts."""
    with _errors():
        clikit.emit(read.get_index(file), plain)


class DataFormat(str, enum.Enum):
    json = "json"
    csv = "csv"
    md = "md"


@app.command()
def data(
    file: FileArg,
    sheets_spec: SheetsOpt = "all",
    sheet: SheetOpt = None,
    cells: CellsOpt = None,
    no_header: Annotated[
        bool, typer.Option("--no-header", help="Treat the first row as data, not a header")
    ] = False,
    max_rows: Annotated[int | None, typer.Option("--max-rows", help="Cap rows returned")] = None,
    formulas_only: Annotated[
        bool,
        typer.Option("--formulas-only", help="Report formula text instead of cached values"),
    ] = False,
    fmt: Annotated[DataFormat, typer.Option("--format", help="Output format")] = DataFormat.json,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory for csv/md files")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Sheet data as a grid of values — not display strings (spec section 9)."""
    with _errors():
        result = read.get_data(
            file,
            sheets=sheets_spec,
            names=sheet,
            cells=cells,
            header=not no_header,
            max_rows=max_rows,
            values="formulas" if formulas_only else "cached",
        )
        if fmt is DataFormat.json:
            clikit.emit(result, plain)
            return
        rendered = {
            sheet_data.sheet: (
                _sheet_data_csv(sheet_data) if fmt is DataFormat.csv else _sheet_data_md(sheet_data)
            )
            for sheet_data in result
        }
        if out is None:
            typer.echo("\n\n".join(rendered.values()))
            return
        out.mkdir(parents=True, exist_ok=True)
        extension = "csv" if fmt is DataFormat.csv else "md"
        written = []
        for sheet_name, body in rendered.items():
            destination = out / f"{sheet_name}.{extension}"
            destination.write_text(body, encoding="utf-8")
            written.append(FileWritten(output=destination))
        clikit.emit(written, plain)


@app.command()
def cells(
    file: FileArg,
    sheets_spec: SheetsOpt = "all",
    sheet: SheetOpt = None,
    cells_range: CellsOpt = None,
    empty: Annotated[
        bool, typer.Option("--empty", help="Include cells with no value and no formula")
    ] = False,
    plain: clikit.plain_option = False,
) -> None:
    """Every selected cell, with both its formula and its cached value."""
    with _errors():
        clikit.emit(
            read.get_cells(file, sheets=sheets_spec, names=sheet, cells=cells_range, empty=empty),
            plain,
        )


@app.command()
def formulas(
    file: FileArg, sheets_spec: SheetsOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Only the formula cells, across the selected sheets."""
    with _errors():
        clikit.emit(read.get_formulas(file, sheets=sheets_spec), plain)


@app.command()
def tables(
    file: FileArg, sheets_spec: SheetsOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Excel table objects (ListObjects) — not Markdown or docx tables."""
    with _errors():
        clikit.emit(read.get_tables(file, sheets=sheets_spec), plain)


@app.command()
def names(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Defined names, workbook- and sheet-scoped."""
    with _errors():
        clikit.emit(read.get_names(file), plain)


@app.command()
def comments(
    file: FileArg, sheets_spec: SheetsOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Classic per-cell comments. Threaded comments are read nowhere (section 7)."""
    with _errors():
        clikit.emit(read.get_comments(file, sheets=sheets_spec), plain)


@app.command()
def images(
    file: FileArg,
    sheets_spec: SheetsOpt = "all",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Extract the image bytes here")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Embedded pictures, optionally extracted."""
    with _errors():
        clikit.emit(read.get_images(file, sheets=sheets_spec, output_dir=out), plain)


@app.command()
def charts(
    file: FileArg, sheets_spec: SheetsOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Charts, with series references — values are never evaluated."""
    with _errors():
        clikit.emit(read.get_charts(file, sheets=sheets_spec), plain)


@app.command()
def props(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Core document properties."""
    with _errors():
        clikit.emit(read.get_properties(file), plain)


@app.command()
def markdown(
    file: FileArg,
    out: OutFileOpt = None,
    sheets_spec: SheetsOpt = "all",
    cells: CellsOpt = None,
    max_rows: Annotated[int | None, typer.Option("--max-rows", help="Cap rows per sheet")] = 200,
) -> None:
    """The workbook as Markdown: a heading and a pipe table per sheet."""
    with _errors():
        value = read.get_markdown(file, sheets=sheets_spec, cells=cells, max_rows=max_rows)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(value, encoding="utf-8")
            clikit.emit(FileWritten(output=out))
        else:
            typer.echo(value)


@app.command()
def fidelity(file: FileArg, plain: clikit.plain_option = False) -> None:
    """What editing this workbook would cost (spec section 6) — without editing it."""
    with _errors():
        clikit.emit(fidelity_module.scan(file), plain)


# --- writes ----------------------------------------------------------------


@app.command()
def create(
    out: Annotated[Path, typer.Option("--out", "-o", help="The workbook to write")],
    from_csv: Annotated[
        list[Path] | None,
        typer.Option("--from-csv", help="Build a sheet from this CSV; repeatable"),
    ] = None,
    from_json: Annotated[
        Path | None, typer.Option("--from-json", help="Build sheets from this JSON file")
    ] = None,
    from_markdown: Annotated[
        Path | None,
        typer.Option("--from-markdown", help="Build sheets from this markdown's tables"),
    ] = None,
    template: Annotated[
        str | None, typer.Option("--template", help="House template name or path")
    ] = None,
    no_header_style: Annotated[
        bool, typer.Option("--no-header-style", help="Skip the bold header row and freeze")
    ] = False,
    plain: clikit.plain_option = False,
) -> None:
    """Create a workbook, from CSV/JSON/markdown sources and/or a template."""
    with _errors():
        sheets: list[SheetSpec] = []
        if from_csv:
            sheets.extend(tabular_module.from_csv(list(from_csv)))
        if from_json:
            sheets.extend(tabular_module.from_json(from_json))
        if from_markdown:
            sheets.extend(tabular_module.from_markdown(from_markdown))
        written = write.create(
            out, sheets=sheets or None, template=template, header_style=not no_header_style
        )
        clikit.emit(FileWritten(output=written), plain)


@app.command(name="set")
def set_cells_command(
    file: FileArg,
    mapping: Annotated[
        str, typer.Option("--map", help='JSON: {"Sheet1": {"B2": 5}}, or a path to one')
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Set specific cells. A value beginning with "=" is always a formula."""
    with _errors():
        updates = _json_object(mapping, what="--map")
        clikit.emit(
            write.set_cells(
                file, updates, output=_destination(file, out, in_place), allow_lossy=allow_lossy
            ),
            plain,
        )


@app.command()
def append(
    file: FileArg,
    sheet: Annotated[str, typer.Option("--sheet", help="Sheet to append to")],
    rows: Annotated[
        str | None, typer.Option("--rows", help="JSON array of arrays, or a path to one")
    ] = None,
    from_csv: Annotated[
        Path | None, typer.Option("--from-csv", help="Append this CSV's rows")
    ] = None,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Append rows after a sheet's last used row (never after a phantom dimension)."""
    with _errors():
        if (rows is None) == (from_csv is None):
            raise RpXlsxError("Pass exactly one of --rows or --from-csv.")
        if rows is not None:
            row_values = _json_array(rows, what="--rows")
        else:
            row_values = tabular_module.from_csv([from_csv], header=False)[0].rows
        clikit.emit(
            write.append_rows(
                file,
                sheet,
                row_values,
                output=_destination(file, out, in_place),
                allow_lossy=allow_lossy,
            ),
            plain,
        )


@app.command()
def replace(
    file: FileArg,
    mapping: Annotated[str, typer.Option("--map", help='JSON: {"old": "new"}, or a path to one')],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    sheets_spec: SheetsOpt = "all",
    ignore_case: Annotated[
        bool, typer.Option("--ignore-case", help="Match case-insensitively")
    ] = False,
    include_formulas: Annotated[
        bool, typer.Option("--include-formulas", help="Also rewrite text inside formulas")
    ] = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Replace text in cell values and header/footer text. Skips formulas by default."""
    with _errors():
        clikit.emit(
            write.replace_text(
                file,
                _json_object(mapping, what="--map"),
                output=_destination(file, out, in_place),
                sheets=sheets_spec,
                match_case=not ignore_case,
                include_formulas=include_formulas,
                allow_lossy=allow_lossy,
            ),
            plain,
        )


@app.command()
def template(
    template_name: Annotated[str, typer.Argument(help="Template name or path")],
    context: Annotated[str, typer.Option("--context", help="JSON object, or a path to one")],
    out: Annotated[Path, typer.Option("--out", "-o", help="The workbook to write")],
    strict: Annotated[
        bool,
        typer.Option("--strict/--no-strict", help="Fail when a placeholder is unresolved"),
    ] = True,
    plain: clikit.plain_option = False,
) -> None:
    """Fill a template's {{ placeholders }} from a JSON context."""
    with _errors():
        clikit.emit(
            template_module.fill_template(
                template_name, _json_object(context, what="--context"), out, strict=strict
            ),
            plain,
        )


# --- sheet operations --------------------------------------------------------


@sheets_app.command("list")
def sheets_list(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Sheet names, in order — cheaper than parsing the whole index."""
    with _errors():
        clikit.emit([sheet.name for sheet in read.get_index(file).sheets], plain)


@sheets_app.command("add")
def sheets_add(
    file: FileArg,
    name: Annotated[str, typer.Option("--name", help="New sheet name")],
    index_opt: Annotated[
        int | None, typer.Option("--index", help="1-based insert position; default appends")
    ] = None,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Add a sheet."""
    with _errors():
        clikit.emit(
            sheets_module.add_sheet(
                file,
                name,
                index=index_opt,
                output=_destination(file, out, in_place),
                allow_lossy=allow_lossy,
            ),
            plain,
        )


@sheets_app.command("delete")
def sheets_delete(
    file: FileArg,
    sheets_spec: Annotated[
        str, typer.Option("--sheets", help="Sheets to delete, by position")
    ] = "",
    sheet: Annotated[
        list[str] | None, typer.Option("--sheet", help="Sheet name to delete; repeatable")
    ] = None,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Delete sheets. Refuses to leave the workbook with no visible sheet."""
    with _errors():
        clikit.emit(
            sheets_module.delete_sheets(
                file,
                sheets_spec,
                sheet,
                output=_destination(file, out, in_place),
                allow_lossy=allow_lossy,
            ),
            plain,
        )


@sheets_app.command("rename")
def sheets_rename(
    file: FileArg,
    old: Annotated[str, typer.Option("--from", help="Current sheet name")],
    new: Annotated[str, typer.Option("--to", help="New sheet name")],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Rename a sheet."""
    with _errors():
        clikit.emit(
            sheets_module.rename_sheet(
                file, old, new, output=_destination(file, out, in_place), allow_lossy=allow_lossy
            ),
            plain,
        )


@sheets_app.command("reorder")
def sheets_reorder(
    file: FileArg,
    order: Annotated[
        str, typer.Option("--order", help="A complete permutation, comma separated: 3,1,2")
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    allow_lossy: AllowLossyOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Reorder sheets. The order must be a complete permutation."""
    with _errors():
        try:
            wanted = [int(part) for part in order.split(",") if part.strip()]
        except ValueError as exc:
            raise RpXlsxError(f"--order must be comma-separated integers, got {order!r}") from exc
        clikit.emit(
            sheets_module.reorder_sheets(
                file, wanted, output=_destination(file, out, in_place), allow_lossy=allow_lossy
            ),
            plain,
        )


# --- templates ---------------------------------------------------------------


@templates_app.command("list")
def templates_list(plain: clikit.plain_option = False) -> None:
    """Every template resolution can find."""
    with _errors():
        clikit.emit(templates_module.list_templates(), plain)


@templates_app.command("inspect")
def templates_inspect(
    name: Annotated[str, typer.Argument(help="Template name or path")],
    plain: clikit.plain_option = False,
) -> None:
    """A template's sheets, defined names, and placeholders."""
    with _errors():
        resolved = templates_module.resolve_template(name)
        if resolved is None:
            raise RpXlsxError(f"No template resolved for {name!r}.")
        clikit.emit(templates_module.inspect_template(resolved), plain)


@templates_app.command("manifest")
def templates_manifest(
    file: FileArg,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the manifest JSON here")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """A redacted description of a template's shape, safe to commit."""
    with _errors():
        manifest = templates_module.build_manifest(file)
        if out is None:
            clikit.emit(manifest, plain)
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        clikit.emit(FileWritten(output=out), plain)


@templates_app.command("synthesize")
def templates_synthesize(
    manifest_file: Annotated[Path, typer.Argument(help="A .manifest.json")],
    out: Annotated[Path, typer.Option("--out", "-o", help="The .xltx to write")],
    plain: clikit.plain_option = False,
) -> None:
    """Rebuild a structurally equivalent template from a manifest."""
    with _errors():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RpXlsxError(f"Cannot read manifest {manifest_file}: {exc}") from exc
        manifest = TemplateManifest.model_validate(data)
        clikit.emit(FileWritten(output=templates_module.synthesize(manifest, out)), plain)


# --- convert and render -------------------------------------------------------


class ConvertTarget(str, enum.Enum):
    pdf = "pdf"
    csv = "csv"
    ods = "ods"
    html = "html"


@app.command()
def convert(
    file: FileArg,
    to: Annotated[ConvertTarget, typer.Option("--to", help="Target format")],
    out: OutFileOpt = None,
    plain: clikit.plain_option = False,
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
) -> None:
    """Convert a workbook with LibreOffice. Needs soffice on PATH."""
    with _errors():
        destination = Path(out) if out is not None else file.with_suffix(f".{to.value}")
        if destination.resolve() == file.resolve():
            raise RpXlsxError(f"Refusing to overwrite {file.name}: pass --out.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        entries = [("to", f"{to.value}, via LibreOffice"), ("output", str(destination))]
        with _job(f"rp-xlsx convert — {file}", entries, show_description, show_progress):
            produced = binaries.soffice_convert(file, to.value, destination.parent)
            if produced != destination:
                produced.replace(destination)
        clikit.emit(ConversionResult(source=file, output=destination, format=to.value), plain)


@app.command()
def render(
    file: FileArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory for the page images")],
    dpi: Annotated[int, typer.Option("--dpi", help="Render resolution")] = 150,
    pages: Annotated[str | None, typer.Option("--pages", help="Pages: 'all', '5', '1-5'")] = None,
    fmt: Annotated[str, typer.Option("--format", help="Image format: png or jpeg")] = "png",
    plain: clikit.plain_option = False,
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
) -> None:
    """Rasterize a workbook to page images via LibreOffice and poppler.

    Page count is a property of the file's print settings, not of its data —
    LibreOffice paginates a sheet according to its print area and page setup.
    """
    with _errors():
        entries = [
            ("pages", pages or "all"),
            ("format", f"{fmt} at {dpi} dpi"),
            ("output", str(out)),
            ("via", "LibreOffice to PDF, then poppler to images"),
        ]
        with _job(f"rp-xlsx render — {file}", entries, show_description, show_progress) as reporter:
            written = core_render.render_pages(
                file, out, dpi=dpi, pages=pages, fmt=fmt, progress=reporter
            )
        clikit.emit(
            [RenderResult(page=number, path=path) for number, path in enumerate(written, start=1)],
            plain,
        )


# Capability report. rp-xlsx needs LibreOffice to convert or render, and
# poppler to turn the converted PDF into images.
app.command("doctor")(clikit.doctor_command("soffice", "pdftoppm", "pdfinfo"))


def _registered(target: typer.Typer) -> set[str]:
    """Command names registered on ``target`` — used by the invariant test."""
    import typer.main

    names_found: set[str] = set()
    for command in target.registered_commands:
        names_found.add(command.name or typer.main.get_command_name(command.callback.__name__))
    for group in target.registered_groups:
        if group.name:
            names_found.add(group.name)
    return names_found


def main() -> None:
    """Console-script entry point."""
    app()


__all__ = [
    "COMMAND_NAMES",
    "SHEETS_COMMAND_NAMES",
    "TEMPLATES_COMMAND_NAMES",
    "app",
    "main",
]
