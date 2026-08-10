"""Sheet structural operations: add, delete, rename, reorder.

Every function here calls section 6's guard first, exactly like
``xlsx/write.py``, and shares its rules: ``output`` is required (this
package never overwrites implicitly), and a workbook must end with at least
one visible sheet — stricter than openpyxl, which will happily write a
workbook Excel refuses to open.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rp_core.errors import InputError
from rp_xlsx import fidelity, ooxml, refs
from rp_xlsx.models import AtRiskPart, SheetOpResult


def _result(target: Path, wb: Any, dropped: list[AtRiskPart]) -> SheetOpResult:
    return SheetOpResult(
        output=target,
        sheet_count=len(wb.sheetnames),
        sheets=list(wb.sheetnames),
        recalculation_required=ooxml.has_any_formula(wb),
        dropped=dropped,
    )


def _require_a_visible_sheet_remains(wb: Any, doomed: set[str]) -> None:
    remaining_visible = [
        name for name in wb.sheetnames if name not in doomed and wb[name].sheet_state == "visible"
    ]
    if not remaining_visible:
        raise InputError(
            "A workbook must keep at least one visible sheet; Excel refuses to open one without it."
        )


def add_sheet(
    path: Path,
    name: str,
    *,
    index: int | None = None,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    report = fidelity.guard(path, allow_lossy=allow_lossy)
    target = ooxml.require_output(output)
    with ooxml.opened(path) as wb:
        refs.validate_sheet_name(name, wb.sheetnames)
        count = len(wb.sheetnames)
        if index is None:
            wb.create_sheet(name)
        else:
            if not 1 <= index <= count + 1:
                raise InputError(
                    f"Index {index} is out of range; a workbook with {count} sheets "
                    f"accepts 1..{count + 1}."
                )
            wb.create_sheet(name, index - 1)
        ooxml.save(wb, target)
        return _result(target, wb, report.at_risk)


def delete_sheets(
    path: Path,
    sheets: str = "",
    names: list[str] | None = None,
    *,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    if not sheets and not names:
        raise InputError("delete_sheets requires sheets (a position spec) or names.")
    report = fidelity.guard(path, allow_lossy=allow_lossy)
    target = ooxml.require_output(output)
    with ooxml.opened(path) as wb:
        sheet_names = wb.sheetnames
        positions = refs.resolve_sheet_selection(sheet_names, sheets=(sheets or "all"), names=names)
        doomed = {sheet_names[position - 1] for position in positions}
        _require_a_visible_sheet_remains(wb, doomed)
        for name in doomed:
            del wb[name]
        ooxml.save(wb, target)
        return _result(target, wb, report.at_risk)


def rename_sheet(
    path: Path,
    old: str,
    new: str,
    *,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    report = fidelity.guard(path, allow_lossy=allow_lossy)
    target = ooxml.require_output(output)
    with ooxml.opened(path) as wb:
        if old not in wb.sheetnames:
            available = ", ".join(repr(n) for n in wb.sheetnames)
            raise InputError(f"No sheet named {old!r}. Available sheets: {available}")
        others = [name for name in wb.sheetnames if name != old]
        refs.validate_sheet_name(new, others)
        wb[old].title = new
        ooxml.save(wb, target)
        return _result(target, wb, report.at_risk)


def reorder_sheets(
    path: Path,
    order: list[int],
    *,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    """Reorder sheets to ``order``, a complete permutation of ``1..sheet_count``.

    Anything else is an :class:`~rp_core.errors.InputError` naming the
    missing, duplicated, or out-of-range indices — ``rp-pptx`` section 4's
    rule for ``reorder_slides``, unchanged here.
    """
    report = fidelity.guard(path, allow_lossy=allow_lossy)
    target = ooxml.require_output(output)
    with ooxml.opened(path) as wb:
        _validate_permutation(order, len(wb.sheetnames))
        wb._sheets = [wb.worksheets[position - 1] for position in order]
        ooxml.save(wb, target)
        return _result(target, wb, report.at_risk)


def _validate_permutation(order: list[int], count: int) -> None:
    expected = set(range(1, count + 1))
    given = set(order)
    if len(order) == count and given == expected:
        return
    problems: list[str] = []
    missing = sorted(expected - given)
    if missing:
        problems.append(f"missing {missing}")
    duplicated = sorted({n for n in order if order.count(n) > 1})
    if duplicated:
        problems.append(f"duplicated {duplicated}")
    out_of_range = sorted(given - expected)
    if out_of_range:
        problems.append(f"out of range {out_of_range}")
    raise InputError(f"order must be a permutation of 1..{count}; " + "; ".join(problems))


__all__ = [
    "add_sheet",
    "delete_sheets",
    "rename_sheet",
    "reorder_sheets",
]
