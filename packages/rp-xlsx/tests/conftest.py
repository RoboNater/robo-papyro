"""Fixtures generated at test time — no binary workbooks committed (spec
section 11.1). Grows through Phase 3; this step adds only what
``test_ooxml_xlsx.py`` and ``test_fidelity_xlsx.py`` need. The three named
synthetic templates (``minimal``/``house_like``/``hostile``, spec section
11.2) land in Phase 3 step 8.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
import pytest

WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
MACRO_WORKBOOK_CONTENT_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"


def _repack(
    source: Path,
    target: Path,
    *,
    extra: dict[str, bytes] | None = None,
    replace: dict[str, bytes] | None = None,
) -> Path:
    """Copy ``source``'s zip to ``target``, adding ``extra`` parts and
    substituting ``replace`` ones — the same primitive every injection
    fixture in this suite is built from (spec section 11.1)."""
    extra = extra or {}
    replace = replace or {}
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            data = replace.get(item.filename, zin.read(item.filename))
            zout.writestr(item, data)
        for name, data in extra.items():
            zout.writestr(name, data)
    return target


@pytest.fixture
def repack_zip():
    """The raw zip-injection helper, for tests that need a bespoke fixture."""
    return _repack


@pytest.fixture
def plain_workbook(tmp_path) -> Path:
    """A minimal workbook: no at-risk parts, no formulas, one text cell."""
    path = tmp_path / "plain.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "hello"
    wb.save(path)
    return path


@pytest.fixture
def template_workbook_path(tmp_path) -> Path:
    """A workbook saved as `.xltx` — openpyxl opens templates natively
    (spec section 5.3), so no injection is needed to produce one."""
    path = tmp_path / "template.xltx"
    wb = openpyxl.Workbook()
    wb.template = True
    ws = wb.active
    ws["A1"] = "title"
    wb.save(path)
    return path


@pytest.fixture
def formula_workbook_path(tmp_path) -> Path:
    """A workbook with a formula and no cached value — openpyxl's own
    default shape, and the baseline `cached_value_workbook` injects onto."""
    path = tmp_path / "formula.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["A2"], ws["A3"] = 1, 2, "=SUM(A1:A2)"
    wb.save(path)
    return path


@pytest.fixture
def cached_value_workbook(tmp_path, formula_workbook_path) -> Path:
    """The same workbook, with A3's formula carrying an injected cached
    `<v>` — the only way to test section 6.1 (spec section 11.1 item 1): an
    openpyxl-authored workbook has no cached values to lose otherwise.
    openpyxl writes an empty `<v></v>` alongside a value-less `<f>`
    (verified against 3.1.5), which is what gets replaced."""
    path = tmp_path / "cached.xlsx"
    with zipfile.ZipFile(formula_workbook_path) as zin:
        sheet = zin.read("xl/worksheets/sheet1.xml")
    injected = sheet.replace(b"<f>SUM(A1:A2)</f><v></v>", b"<f>SUM(A1:A2)</f><v>3</v>")
    assert injected != sheet, "openpyxl's empty <v/> placeholder was not found to replace"
    _repack(formula_workbook_path, path, replace={"xl/worksheets/sheet1.xml": injected})
    return path


@pytest.fixture
def at_risk_workbook(tmp_path, plain_workbook) -> Path:
    """The six representative at-risk parts from spec section 11.1 item 2 —
    presence fixtures only. They need no valid content: the guard keys on
    part names, not on anything inside them (the `modern_comments_deck`
    doctrine `AGENTS.md` and the spec both cite)."""
    path = tmp_path / "at_risk.xlsx"
    extra = {
        "customXml/item1.xml": b"<root/>",
        "xl/ctrlProps/ctrlProp1.xml": b"<formControlPr/>",
        "xl/persons/person.xml": b"<personList/>",
        "xl/pivotCache/pivotCacheDefinition1.xml": b"<pivotCacheDefinition/>",
        "xl/slicers/slicer1.xml": b"<slicer/>",
        "xl/threadedComments/threadedComment1.xml": b"<threadedComments/>",
    }
    _repack(plain_workbook, path, extra=extra)
    return path


@pytest.fixture
def macro_workbook(tmp_path, plain_workbook) -> Path:
    """A `.xlsm` carrying an injected `xl/vbaProject.bin` and the
    macro-enabled content type (spec section 11.1 item 3), to test that
    `keep_vba` preserves it across an edit."""
    path = tmp_path / "macro.xlsm"
    with zipfile.ZipFile(plain_workbook) as zin:
        content_types = zin.read("[Content_Types].xml").decode()
    content_types = content_types.replace(WORKBOOK_CONTENT_TYPE, MACRO_WORKBOOK_CONTENT_TYPE)
    if "vbaProject" not in content_types:
        content_types = content_types.replace(
            "</Types>",
            '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>',
        )
    _repack(
        plain_workbook,
        path,
        extra={"xl/vbaProject.bin": b"FAKE-VBA-BYTES"},
        replace={"[Content_Types].xml": content_types.encode()},
    )
    return path
