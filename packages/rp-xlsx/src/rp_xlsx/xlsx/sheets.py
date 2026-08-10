"""Sheet structural operations: add, delete, rename, reorder.

Every function here calls section 6's guard first, exactly like
``xlsx/write.py``, and shares its rules: ``output`` is required (this
package never overwrites implicitly), and a workbook must end with at least
one visible sheet — stricter than openpyxl, which will happily write a
workbook Excel refuses to open.

**``rename_sheet`` is temporarily disabled** (see :data:`RENAME_DISABLED_MESSAGE`
and its docstring) — PR review kept finding another reference-bearing
structure (chart series, then hyperlinks, table formulas, ...) that
openpyxl leaves dangling after a rename and this package's scan did not
yet cover, so it is refused unconditionally rather than shipped with an
open-ended list of known gaps.
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


def _rename_via_a_temporary_title(ws: Any, wb: Any, new: str) -> None:
    """Set ``ws.title = new``, routed through a scratch title first.

    openpyxl's own title setter runs its *own* case-insensitive uniqueness
    check against every current sheet name — including the sheet's own prior
    title, which it does not exclude. On a case-only rename that means the
    sheet being renamed always collides with itself: ``ws.title = "data"``
    next to the sheet's own current title ``"Data"`` raises nothing and
    instead silently becomes ``"data1"`` (verified against openpyxl 3.1.5),
    even though :func:`~rp_xlsx.refs.validate_sheet_name` already confirmed
    ``new`` is not taken by any *other* sheet. Assigning a scratch title
    first removes the old title from the workbook before ``new`` is ever
    checked, so the second assignment has nothing of the sheet's own to
    collide with.
    """
    taken = {name.casefold() for name in wb.sheetnames}
    scratch = "~rename"
    suffix = 1
    while scratch.casefold() in taken:
        suffix += 1
        scratch = f"~rename{suffix}"
    ws.title = scratch
    ws.title = new


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


#: The same defensive-attribute-access exceptions ``xlsx/read.py``'s chart
#: reading guards against (spec section 9): one exotic chart's shape must not
#: sink a scan that exists purely to be conservative.
_CHART_REF_ERRORS = (AttributeError, TypeError, ValueError, IndexError)


def _chart_reference_texts(chart: Any) -> list[str]:
    """Every cell-reference string a chart's series point at — never a
    value, just the reference text a sheet rename could leave dangling.

    Mirrors ``xlsx/read.py``'s ``_ref_of`` (kept separate rather than
    imported, since that module's helpers are private to its own read
    path): a series' value/category source holds its reference under
    ``numRef.f`` or ``strRef.f`` depending on the data type.
    """
    texts: list[str] = []
    try:
        for series in getattr(chart, "series", []):
            for axis in ("val", "cat"):
                source = getattr(series, axis, None)
                if source is None:
                    continue
                for ref_attr in ("numRef", "strRef"):
                    sub = getattr(source, ref_attr, None)
                    formula = getattr(sub, "f", None) if sub is not None else None
                    if formula:
                        texts.append(formula)
    except _CHART_REF_ERRORS:
        pass
    return texts


def _references_to_old_sheet(wb: Any, old: str) -> list[str]:
    """Every formula, defined name, chart series, conditional-formatting
    rule, or data-validation rule that sheet-qualifies a reference to
    ``old``, each rendered as a short description for an error message.

    openpyxl does not rewrite any of these when a sheet's title changes
    (verified directly for each: a chart series ``val`` ref, a conditional
    formatting rule's formula, and a data validation's ``formula1`` were all
    still ``'Data'!...``/``Data!...`` after renaming ``Data`` and
    save/reload) — a rename that proceeded anyway would return success while
    leaving references pointed at a sheet that no longer exists. Every one
    of these is already plain reference/formula text once openpyxl has
    parsed the part (a series' ``numRef.f``, a rule's ``.formula`` entries, a
    validation's ``.formula1``/``.formula2``), so the same
    :func:`~rp_xlsx.refs.sheet_reference_matcher` that checks a cell formula
    checks these too — no separate parser needed.
    """
    matches = refs.sheet_reference_matcher(old)
    found: list[str] = []
    for ws in wb.worksheets:
        for cell in ooxml.populated_cells(ws):
            if cell.data_type == "f" and isinstance(cell.value, str) and matches(cell.value):
                found.append(f"formula {ws.title}!{cell.coordinate} = {cell.value}")
        for chart in getattr(ws, "_charts", []):
            for ref_text in _chart_reference_texts(chart):
                if matches(ref_text):
                    found.append(f"chart series on {ws.title!r} = {ref_text}")
        for cf_range in ws.conditional_formatting:
            for rule in cf_range.rules:
                for formula in getattr(rule, "formula", None) or ():
                    if isinstance(formula, str) and matches(formula):
                        found.append(
                            f"conditional formatting on {ws.title!r} {cf_range.sqref} = {formula}"
                        )
        for dv in ws.data_validations.dataValidation:
            for formula in (dv.formula1, dv.formula2):
                if formula and matches(formula):
                    found.append(f"data validation on {ws.title!r} = {formula}")
    for name, dn in wb.defined_names.items():
        if dn.attr_text and matches(dn.attr_text):
            found.append(f"defined name {name!r} = {dn.attr_text}")
    for ws in wb.worksheets:
        for name, dn in ws.defined_names.items():
            if dn.attr_text and matches(dn.attr_text):
                found.append(f"defined name {name!r} (scoped to {ws.title!r}) = {dn.attr_text}")
    return found


#: Message for :func:`rename_sheet`'s unconditional refusal (module level so
#: the CLI/MCP layers can reference the same text rather than re-explain it).
RENAME_DISABLED_MESSAGE = (
    "sheets rename is temporarily disabled. Renaming a sheet can leave formulas, "
    "defined names, chart series, conditional formatting, data validation, cell "
    "hyperlinks, or table calculated-column/totals-row formulas referring to the "
    "old sheet name -- openpyxl does not rewrite any of these on save. Each "
    "review pass on this feature's reference-detection scan found another "
    "reference-bearing structure it missed (chart series shapes beyond val/cat, "
    "then hyperlinks and table formulas), so rather than continue closing one "
    "structure at a time this operation is disabled until a structurally "
    "complete solution replaces the current per-structure scan. See "
    "docs/specs/rp-xlsx-spec.md's Sheets section for the tracked gap; "
    "_rename_sheet_impl below still has the detection logic this will build on."
)


def rename_sheet(
    path: Path,
    old: str,
    new: str,
    *,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    """Rename sheet ``old`` to ``new``.

    **Temporarily disabled** — see :data:`RENAME_DISABLED_MESSAGE`. The
    working implementation is retained as :func:`_rename_sheet_impl`, not
    deleted, so re-enabling this is a matter of wiring this name back to it
    once the remaining reference-bearing structures are covered.
    """
    raise InputError(RENAME_DISABLED_MESSAGE)


def _rename_sheet_impl(
    path: Path,
    old: str,
    new: str,
    *,
    output: Path | None = None,
    allow_lossy: bool = False,
) -> SheetOpResult:
    """The rename implementation :func:`rename_sheet` currently refuses to run.

    **Refuses rather than rename when anything sheet-qualifies a reference
    to ``old``.** openpyxl does not update these references when a sheet's
    title changes, so a rename that proceeded anyway would silently leave
    them pointed at a sheet name that no longer exists — indistinguishable
    from success until someone opens the file and finds ``#REF!``-shaped
    wrongness with no error anywhere. Detection (:func:`_references_to_old_sheet`)
    covers cell formulas, workbook- and sheet-scoped defined names, chart
    series, conditional-formatting rules, and data-validation rules, in
    both bare and quoted form and at either endpoint of a 3-D range —
    **known incomplete**: it does not yet cover scatter/bubble chart series
    (``xVal``/``yVal``/``bubbleSize``), series/axis titles (``tx.strRef``),
    cell hyperlinks, or table ``calculatedColumnFormula``/``totalsRowFormula``,
    each confirmed by direct reproduction to survive a rename unrewritten.
    This package has no reference-*rewriting* implementation — refusal was
    chosen deliberately over a rewrite that could still miss some
    reference-bearing structure and look done when it wasn't.
    """
    report = fidelity.guard(path, allow_lossy=allow_lossy)
    target = ooxml.require_output(output)
    with ooxml.opened(path) as wb:
        if old not in wb.sheetnames:
            available = ", ".join(repr(n) for n in wb.sheetnames)
            raise InputError(f"No sheet named {old!r}. Available sheets: {available}")
        others = [name for name in wb.sheetnames if name != old]
        refs.validate_sheet_name(new, others)
        references = _references_to_old_sheet(wb, old)
        if references:
            shown = "; ".join(references[:5])
            more = f" (and {len(references) - 5} more)" if len(references) > 5 else ""
            raise InputError(
                f"Refusing to rename sheet {old!r}: openpyxl does not update sheet-qualified "
                f"references when a sheet is renamed, and {len(references)} reference(s) "
                f"still refer to {old!r}: {shown}{more}. Update or remove those references "
                "first, then rename."
            )
        _rename_via_a_temporary_title(wb[old], wb, new)
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
