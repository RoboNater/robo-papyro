"""Section 6 — the fidelity guard: what an openpyxl load->save would silently drop.

**Read this before writing any code that saves a workbook.** openpyxl does not
round-trip a workbook (``dev-notes/phase-3-openpyxl-probe.md``, verified).
Two losses, both silent: every formula's cached value, and any package part
openpyxl does not model (threaded comments, the persons part, pivot caches,
slicers, form controls, custom XML). This module answers "what would editing
this workbook cost?" without opening it through openpyxl at all — the scan
works directly on the zip via :mod:`rp_xlsx.ooxml`, so it costs nothing and
cannot half-write.

**The guard keys on part presence, not on a feature list.** Next year's
openpyxl models more, and the categories below are representative rather than
exhaustive (spec section 6.2). Presence is detectable with certainty;
placement is not — ``AGENTS.md``: *"Presence and placement are different
questions with different reliability"* — so this never tries to attribute a
part to a sheet, only to report that the part exists.
"""

from __future__ import annotations

from pathlib import Path

from rp_xlsx import ooxml
from rp_xlsx.errors import LossyEditError
from rp_xlsx.models import AtRiskPart, FidelityReport

#: Part-name prefix -> (category, detail). Order matters only in that a part
#: is classified under the first prefix it matches; the categories are
#: disjoint by construction (spec section 11.1's six representative parts).
_AT_RISK_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("xl/threadedComments/", "threaded_comments", "Threaded comments are deleted on save."),
    (
        "xl/persons/",
        "persons",
        "The persons part (threaded-comment author identities) is deleted on save.",
    ),
    ("xl/pivotCache/", "pivot_cache", "Pivot cache definitions are deleted on save."),
    ("xl/pivotTables/", "pivot_table", "Pivot tables are deleted on save."),
    ("xl/slicers/", "slicer", "Slicers are deleted on save."),
    ("xl/slicerCaches/", "slicer_cache", "Slicer caches are deleted on save."),
    ("xl/ctrlProps/", "form_control", "Form control properties are deleted on save."),
    ("customXml/", "custom_xml", "Custom XML parts are deleted on save."),
)


def classify_at_risk_parts(path: Path) -> list[AtRiskPart]:
    """Every part in ``path`` that a load->save would silently drop."""
    found: list[AtRiskPart] = []
    for part in ooxml.part_names(path):
        for prefix, category, detail in _AT_RISK_PREFIXES:
            if part.startswith(prefix):
                found.append(AtRiskPart(category=category, part=part, detail=detail))
                break
    return found


def has_cached_values(path: Path) -> bool:
    """Whether any formula in ``path`` carries a cached ``<v>`` (spec section 7).

    The observable is read directly off the sheet parts rather than by loading
    the workbook twice and comparing — cheaper, and this is what an index
    computes for every workbook it reports on. openpyxl itself writes an empty
    ``<v/>`` alongside ``<f>`` for a formula it has no cached value for
    (verified against 3.1.5), so presence of the element is not enough: only a
    ``<v>`` with actual text counts.
    """
    main_v = f"{{{ooxml.NS['main']}}}v"
    for part in ooxml.part_names(path):
        if not (part.startswith("xl/worksheets/") and part.endswith(".xml")):
            continue
        root = ooxml.parse_part(path, part)
        if root is None:
            continue
        for cell in ooxml.xpath(root, ".//main:c[main:f]"):
            value = cell.find(main_v)
            if value is not None and (value.text or "").strip():
                return True
    return False


def has_macros(path: Path) -> bool:
    """Whether ``path`` carries a VBA project part."""
    return ooxml.read_part(path, ooxml.VBA_PROJECT_PART) is not None


def scan(path: Path) -> FidelityReport:
    """What editing ``path`` with openpyxl would cost (spec section 6).

    Never refuses anything itself — reads are never blocked by the fidelity
    guard (section 6.2); only a subsequent write is, via :func:`guard`.
    ``get_index`` and ``rp-xlsx fidelity`` both call this directly and must
    stay total: an unreadable chart or a phantom dimension is not this
    function's problem, but a workbook this function cannot even open is
    :func:`~rp_xlsx.ooxml.check_readable`'s to explain, and it does.
    """
    path = ooxml.check_readable(path)
    at_risk = classify_at_risk_parts(path)
    return FidelityReport(
        path=path,
        safe_to_edit=not at_risk,
        at_risk=at_risk,
        cached_values_present=has_cached_values(path),
        macros_present=has_macros(path),
    )


def guard(path: Path, *, allow_lossy: bool = False) -> FidelityReport:
    """Call before opening any existing workbook for editing (spec section 6.2).

    Raises :class:`~rp_xlsx.errors.LossyEditError` (exit 3) when at-risk parts
    are present and ``allow_lossy`` is ``False``. Returns the
    :class:`~rp_xlsx.models.FidelityReport` either way, so a caller that passed
    ``allow_lossy=True`` can report exactly what was dropped in its own result
    (``WriteResult.dropped``) — the flag never makes the loss silent.

    Called **before** the workbook is opened for editing, so a refusal costs
    nothing and a write can never be left half-done.
    """
    report = scan(path)
    if report.at_risk and not allow_lossy:
        categories = sorted({item.category for item in report.at_risk})
        parts = ", ".join(item.part for item in report.at_risk)
        raise LossyEditError(
            f"Editing {Path(path).name} would silently drop: {', '.join(categories)} "
            f"({parts}). Pass --allow-lossy (allow_lossy=True) to proceed anyway; the "
            "result will report exactly what was dropped."
        )
    return report


__all__ = [
    "classify_at_risk_parts",
    "guard",
    "has_cached_values",
    "has_macros",
    "scan",
]
