"""Tabular interchange: CSV/TSV and JSON both directions, Markdown tables in
(spec section 4). Everything here produces or consumes ``SheetSpec`` — the
one input shape ``create`` takes regardless of whether the rows came from
CSV, JSON, or a Markdown table.

**Delimiter is explicit or inferred from the file extension, never sniffed
from content.** ``csv.Sniffer`` is wrong often enough on real exports that
the failure mode — one column containing everything — is a recognisable bug
report, and a silent misparse is exactly what parent spec section 10 exists
to avoid.

**CSV has no type system, so this package does not pretend it does.** A
field is a number only when it parses cleanly as one with no leading zero
(``"007"`` stays text — the classic zip-code/ID footgun) or as a float;
everything else, including anything that looks like a boolean or a date,
stays a plain string. Guessing a type from formatting is exactly the kind
of silent misinterpretation parent spec section 10 warns about, and half of
Excel's own CSV-import complaints are this exact class of bug.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from rp_core.errors import InputError
from rp_core.markdown import parse_markdown
from rp_xlsx.models import CellValue, SheetSpec
from rp_xlsx.xlsx.read import get_data

#: A number with no leading zero (other than a bare "0") — "007" must stay
#: text (the classic zip-code/ID footgun), but float() itself does not
#: enforce that, so the shape is checked before int()/float() ever run.
_NUMBER_RE = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?$")


def _read_text_source(source: Path | str) -> str:
    """A path to a file, or the content itself.

    Matches the CLI convention (parent spec section 10): ``--map``,
    ``--rows``, and ``--context`` all accept either a path to a JSON file or
    the JSON itself, and ``from_json``/``from_markdown`` take the same
    ``Path | str`` shape so the library layer agrees with the CLI.
    """
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    candidate = Path(source)
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return source


def _csv_cell(value: CellValue) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _coerce_csv_value(text: str) -> CellValue:
    """A CSV field's value: an int or float when it parses cleanly and
    unambiguously as one, otherwise the text itself. Never a bool, never a
    date — CSV has no marker for either, and reporting one would be a guess.
    """
    if text == "":
        return None
    if not _NUMBER_RE.match(text):
        return text
    if "." in text or "e" in text or "E" in text:
        return float(text)
    return int(text)


def to_csv(
    path: Path,
    output_dir: Path,
    *,
    sheets: str = "all",
    names: list[str] | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> list[Path]:
    """One CSV (or TSV) file per selected sheet, named after the sheet.

    Sheet names are safe filenames by construction: Excel forbids
    ``: \\ / ? * [ ]`` in a sheet title (section 4's ``validate_sheet_name``
    enforces the same rule on the write side), so nothing read back from a
    real workbook needs sanitizing here.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = ".tsv" if delimiter == "\t" else ".csv"
    written: list[Path] = []
    for sheet in get_data(path, sheets=sheets, names=names, header=True):
        target = output_dir / f"{sheet.sheet}{extension}"
        with target.open("w", newline="", encoding=encoding) as handle:
            writer = csv.writer(handle, delimiter=delimiter)
            if sheet.header:
                writer.writerow(sheet.header)
            for row in sheet.rows:
                writer.writerow([_csv_cell(value) for value in row])
        written.append(target)
    return written


def from_csv(
    sources: list[Path],
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    header: bool = True,
) -> list[SheetSpec]:
    """One ``SheetSpec`` per source file, named after the file's stem.

    ``delimiter=None`` infers from the extension (``.tsv`` -> tab, else
    comma) — never sniffed from content (module docstring).
    """
    specs: list[SheetSpec] = []
    for raw_source in sources:
        source = Path(raw_source)
        sep = (
            delimiter
            if delimiter is not None
            else ("\t" if source.suffix.lower() == ".tsv" else ",")
        )
        with source.open("r", newline="", encoding=encoding) as handle:
            rows = list(csv.reader(handle, delimiter=sep))
        header_row: list[str] | None = None
        if header and rows:
            header_row, rows = rows[0], rows[1:]
        specs.append(
            SheetSpec(
                name=source.stem,
                header=header_row,
                rows=[[_coerce_csv_value(cell) for cell in row] for row in rows],
            )
        )
    return specs


def from_json(source: Path | str) -> list[SheetSpec]:
    """A JSON array of ``SheetSpec``-shaped objects, from a file or a literal
    string (spec section 10's "path or the JSON itself" convention)."""
    text = _read_text_source(source)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise InputError("from_json expects a JSON array of sheet objects.")
    try:
        return [SheetSpec.model_validate(item) for item in data]
    except ValidationError as exc:
        raise InputError(f"Invalid sheet object in JSON: {exc}") from exc


def from_markdown(source: Path | str) -> list[SheetSpec]:
    """Every GFM pipe table in ``source``, one ``SheetSpec`` each, named
    after the nearest preceding heading (falling back to ``"SheetN"`` when
    there is none).

    Consumes :func:`rp_core.markdown.parse_markdown`'s AST — the shared
    block parser, not a bespoke one — and takes its ``"table"`` blocks,
    whose first row is already the header (the parser drops the divider
    row). This is the one place this package touches Markdown on the write
    side; there is no "Markdown document -> workbook" mapping, because a
    workbook is not a document.
    """
    text = _read_text_source(source)
    blocks = parse_markdown(text)
    specs: list[SheetSpec] = []
    heading: str | None = None
    table_count = 0
    for block in blocks:
        if block.kind == "heading":
            heading = block.text
            continue
        if block.kind != "table" or not block.rows:
            continue
        table_count += 1
        header_row, *data_rows = block.rows
        specs.append(
            SheetSpec(
                name=heading or f"Sheet{table_count}",
                header=header_row,
                rows=[[_coerce_csv_value(cell) for cell in row] for row in data_rows],
            )
        )
    return specs


__all__ = ["from_csv", "from_json", "from_markdown", "to_csv"]
