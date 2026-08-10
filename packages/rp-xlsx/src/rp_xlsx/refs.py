"""A1 notation and sheet selection — pure functions, no openpyxl, no I/O.

Two things spreadsheets need that no other leaf does, and both are worth
getting right before anything depends on them (spec section 12 step 4,
mirroring how `rp-pptx` built `runs.py` first):

**A1 notation stays in this leaf.** ``"A1"``, ``"A1:D20"``, ``"B:B"``,
``"3:3"`` are a spreadsheet concept, not a generic range spec, so they are
parsed here rather than by ``rp_core.ranges`` — exactly as PDF page *labels*
stay in ``rp_pdf.pages`` rather than in ``rp_core.ranges`` (parent spec
section 4.3).

**Sheet selection is two arguments, not one, and that is deliberate.**
``sheets`` is an ``rp_core.ranges`` spec over 1-based sheet *position*;
``names`` selects by sheet *name*. A single argument accepting both cannot be
disambiguated — ``"2024"`` is a perfectly ordinary sheet name and also a
position spec, and a workbook can contain a sheet literally named ``"2"``.
``--sheets 2`` and ``--sheet "2"`` must select different sheets on such a
workbook; that is the test this module exists to make pass (spec section 4,
section 11.2's ``house_like`` fixture).
"""

from __future__ import annotations

import re

from rp_core.errors import InputError
from rp_core.ranges import parse_range_spec
from rp_xlsx.errors import RefSpecError

_COLUMN_RE = re.compile(r"^[A-Za-z]{1,3}$")
_CELL_RE = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


def column_index(letters: str) -> int:
    """``"A"`` -> 1, ``"Z"`` -> 26, ``"AA"`` -> 27, ``"ZZ"`` -> 702; 1-based."""
    letters = letters.strip().upper()
    if not letters or not _COLUMN_RE.match(letters):
        raise RefSpecError(f"Invalid column letters {letters!r}")
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index


def column_letters(index: int) -> str:
    """Inverse of :func:`column_index`: 1 -> ``"A"``, 27 -> ``"AA"``."""
    if index < 1:
        raise RefSpecError(f"Column index must be >= 1, got {index}")
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


class CellPosition:
    """A 1-based (row, column) pair, and its A1 spelling."""

    __slots__ = ("row", "column")

    def __init__(self, row: int, column: int) -> None:
        self.row = row
        self.column = column

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CellPosition) and (self.row, self.column) == (
            other.row,
            other.column,
        )

    def __repr__(self) -> str:
        return f"CellPosition(row={self.row}, column={self.column})"

    @property
    def ref(self) -> str:
        return f"{column_letters(self.column)}{self.row}"


class A1Range:
    """A bounding box in A1 terms.

    ``None`` on a bound means "open" — ``"B:B"`` has no row bound and
    ``"3:3"`` has no column bound. Resolving an open bound against a sheet's
    actual extent is the caller's job, because this module has no I/O and
    does not know what any sheet contains.
    """

    __slots__ = ("min_row", "min_col", "max_row", "max_col")

    def __init__(
        self,
        min_row: int | None,
        min_col: int | None,
        max_row: int | None,
        max_col: int | None,
    ) -> None:
        self.min_row = min_row
        self.min_col = min_col
        self.max_row = max_row
        self.max_col = max_col

    def __eq__(self, other: object) -> bool:
        return isinstance(other, A1Range) and (
            self.min_row,
            self.min_col,
            self.max_row,
            self.max_col,
        ) == (other.min_row, other.min_col, other.max_row, other.max_col)

    def __repr__(self) -> str:
        return (
            f"A1Range(min_row={self.min_row}, min_col={self.min_col}, "
            f"max_row={self.max_row}, max_col={self.max_col})"
        )


def parse_cell_ref(ref: str) -> CellPosition:
    """``"B5"`` -> ``CellPosition(row=5, column=2)``."""
    text = ref.strip()
    match = _CELL_RE.match(text)
    if not match:
        raise RefSpecError(f"Invalid cell reference {ref!r}; expected A1 notation like 'B5'")
    letters, digits = match.groups()
    row = int(digits)
    if row < 1:
        raise RefSpecError(f"Invalid cell reference {ref!r}: row must be 1 or greater")
    return CellPosition(row=row, column=column_index(letters))


def parse_a1_range(spec: str) -> A1Range:
    """``"A1"``, ``"A1:D20"``, ``"B:B"``, ``"3:3"`` -> an :class:`A1Range`.

    Malformed input raises :class:`~rp_xlsx.errors.RefSpecError` naming the
    offending token.
    """
    text = spec.strip()
    if not text:
        raise RefSpecError("Empty cell range")

    start, sep, end = text.partition(":")
    if not sep:
        pos = parse_cell_ref(start)
        return A1Range(pos.row, pos.column, pos.row, pos.column)

    start, end = start.strip(), end.strip()
    if not start or not end:
        raise RefSpecError(f"Invalid cell range {spec!r}: missing an endpoint")

    if _COLUMN_RE.match(start) and _COLUMN_RE.match(end):
        # "B:B" or "B:D" -- whole columns, every row.
        left, right = column_index(start), column_index(end)
        return A1Range(None, min(left, right), None, max(left, right))
    if start.isdigit() and end.isdigit():
        # "3:3" or "3:7" -- whole rows, every column.
        top, bottom = int(start), int(end)
        if top < 1 or bottom < 1:
            raise RefSpecError(f"Invalid cell range {spec!r}: row must be 1 or greater")
        return A1Range(min(top, bottom), None, max(top, bottom), None)

    start_pos, end_pos = parse_cell_ref(start), parse_cell_ref(end)
    return A1Range(
        min(start_pos.row, end_pos.row),
        min(start_pos.column, end_pos.column),
        max(start_pos.row, end_pos.row),
        max(start_pos.column, end_pos.column),
    )


def resolve_sheet_selection(
    sheet_names: list[str],
    *,
    sheets: str = "all",
    names: list[str] | None = None,
) -> list[int]:
    """The ordered, 1-based sheet positions ``sheets``/``names`` select.

    ``sheets`` is an ``rp_core.ranges`` spec over 1-based position; ``names``
    selects by sheet name and may repeat. Supplying a non-default ``sheets``
    together with ``names`` is an :class:`~rp_core.errors.InputError`; an
    unknown name is too, and the message lists the workbook's actual sheet
    names so a caller can see what it should have asked for. Supplying
    neither (the defaults) selects every sheet, in order.
    """
    if names:
        if sheets != "all":
            raise InputError(
                "Supply either sheets (a position spec) or names (sheet names), not both."
            )
        positions: set[int] = set()
        for name in names:
            try:
                positions.add(sheet_names.index(name) + 1)
            except ValueError as exc:
                available = ", ".join(repr(n) for n in sheet_names)
                raise InputError(f"No sheet named {name!r}. Available sheets: {available}") from exc
        return sorted(positions)
    return parse_range_spec(sheets, len(sheet_names), noun="sheet")


#: Excel's own forbidden characters in a sheet title (verified: openpyxl
#: raises ``ValueError`` for these).
FORBIDDEN_SHEET_CHARS = frozenset(":\\/?*[]")

#: Excel's sheet-title length limit. openpyxl only *warns* past this
#: (verified) — a warning is invisible to an agent, so this package raises.
MAX_SHEET_NAME_LENGTH = 31


def validate_sheet_name(name: str, existing: list[str] = ()) -> None:
    """Raise :class:`~rp_core.errors.InputError` on a sheet name Excel would
    refuse, or openpyxl would only warn about (spec section 4).

    Checks forbidden characters, the 31-character limit, non-emptiness, and
    uniqueness against ``existing`` — none of which openpyxl itself raises
    reliably on the write side (section 9).

    **Uniqueness is checked case-insensitively** (verified against openpyxl
    3.1.5): Excel treats sheet names as case-insensitive, and
    ``wb.create_sheet("data")`` next to an existing ``"Data"`` does not raise
    — it silently renames the new sheet to ``"data1"``. A caller who asked
    for ``"data"`` and got a workbook containing ``"data1"`` with no error is
    exactly the silent-wrong-output failure this function exists to prevent,
    so the comparison is normalized with ``.casefold()`` rather than ``==``.
    """
    if not name:
        raise InputError("Sheet name must not be empty.")
    if len(name) > MAX_SHEET_NAME_LENGTH:
        raise InputError(
            f"Sheet name {name!r} is {len(name)} characters; Excel's limit is "
            f"{MAX_SHEET_NAME_LENGTH}."
        )
    found = FORBIDDEN_SHEET_CHARS & set(name)
    if found:
        offending = "".join(sorted(found))
        raise InputError(f"Sheet name {name!r} contains forbidden character(s): {offending}")
    folded = name.casefold()
    collision = next((other for other in existing if other.casefold() == folded), None)
    if collision is not None:
        raise InputError(
            f"A sheet named {collision!r} already exists; Excel treats sheet names as "
            f"case-insensitive, so {name!r} collides with it."
        )


def sheet_reference_pattern(name: str) -> re.Pattern[str]:
    """A compiled, case-insensitive pattern matching a sheet-qualified
    reference to ``name`` in formula text or a defined name's ``attr_text``.

    A formula can qualify a sheet reference two ways, and this matches
    both: quoted (``'Sheet Name'!A1``, with any internal ``'`` doubled per
    Excel's own escaping — verified against a real workbook) and bare
    (``Sheet1!A1``). Matching is case-insensitive because Excel resolves a
    sheet qualifier case-insensitively, same as sheet-name uniqueness
    itself (:func:`validate_sheet_name`).

    Deliberately over-inclusive: the bare form is reported even where Excel
    would technically require the quoted form (``name`` contains a space,
    say), and a match inside what happens to be a 3-D range
    (``Sheet1:Sheet3!A1``) is still caught since nothing excludes a
    preceding ``:``. A false positive here costs an explicit refusal to
    rename; a false negative would silently ship a workbook with a
    dangling reference — the whole reason this function exists.
    """
    quoted = "'" + name.replace("'", "''") + "'"
    return re.compile(
        r"(?:" + re.escape(quoted) + r"|(?<![A-Za-z0-9_.])" + re.escape(name) + r")!",
        re.IGNORECASE,
    )


__all__ = [
    "A1Range",
    "CellPosition",
    "FORBIDDEN_SHEET_CHARS",
    "MAX_SHEET_NAME_LENGTH",
    "column_index",
    "column_letters",
    "parse_a1_range",
    "parse_cell_ref",
    "resolve_sheet_selection",
    "sheet_reference_pattern",
    "validate_sheet_name",
]
