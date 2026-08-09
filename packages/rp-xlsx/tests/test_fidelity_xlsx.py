"""rp_xlsx.fidelity -- section 6's guard, tested from the observable (spec
section 11.3): a workbook with injected cached values loses them across an
edit and the result reports it; a workbook with an at-risk part raises
LossyEditError with exit code 3; --allow-lossy proceeds and lists the parts;
get_index-equivalent scanning still succeeds and reports at_risk.
"""

from __future__ import annotations

import pytest

from rp_xlsx import fidelity, ooxml
from rp_xlsx.errors import LossyEditError


class TestScan:
    def test_plain_workbook_is_safe(self, plain_workbook):
        report = fidelity.scan(plain_workbook)
        assert report.safe_to_edit is True
        assert report.at_risk == []
        assert report.macros_present is False

    def test_uncached_formula_workbook_has_no_cached_values(self, formula_workbook_path):
        report = fidelity.scan(formula_workbook_path)
        assert report.cached_values_present is False

    def test_injected_cached_value_is_detected(self, cached_value_workbook):
        report = fidelity.scan(cached_value_workbook)
        assert report.cached_values_present is True

    def test_at_risk_workbook_lists_every_category(self, at_risk_workbook):
        report = fidelity.scan(at_risk_workbook)
        assert report.safe_to_edit is False
        categories = {item.category for item in report.at_risk}
        assert categories == {
            "threaded_comments",
            "persons",
            "pivot_cache",
            "slicer",
            "form_control",
            "custom_xml",
        }

    def test_at_risk_report_names_the_parts(self, at_risk_workbook):
        report = fidelity.scan(at_risk_workbook)
        parts = {item.part for item in report.at_risk}
        assert "xl/threadedComments/threadedComment1.xml" in parts

    def test_macro_workbook_reports_macros_present(self, macro_workbook):
        report = fidelity.scan(macro_workbook)
        assert report.macros_present is True

    def test_macros_are_not_at_risk(self, macro_workbook):
        """Macros are handled via keep_vba, not flagged (spec section 6.2)."""
        report = fidelity.scan(macro_workbook)
        assert report.at_risk == []
        assert report.safe_to_edit is True

    def test_scan_never_opens_the_workbook_through_openpyxl(self, at_risk_workbook, monkeypatch):
        """The scan costs nothing on a workbook it is about to refuse editing
        on -- it must never call ooxml.opened()."""

        def _boom(*args, **kwargs):
            raise AssertionError("scan() must not open the workbook through openpyxl")

        monkeypatch.setattr(ooxml, "opened", _boom)
        report = fidelity.scan(at_risk_workbook)
        assert report.safe_to_edit is False


class TestGuard:
    def test_safe_workbook_proceeds(self, plain_workbook):
        report = fidelity.guard(plain_workbook)
        assert report.safe_to_edit is True

    def test_at_risk_workbook_raises_lossy_edit_error(self, at_risk_workbook):
        with pytest.raises(LossyEditError) as excinfo:
            fidelity.guard(at_risk_workbook)
        assert excinfo.value.exit_code == 3

    def test_error_names_the_categories(self, at_risk_workbook):
        with pytest.raises(LossyEditError, match="threaded_comments"):
            fidelity.guard(at_risk_workbook)

    def test_error_names_allow_lossy(self, at_risk_workbook):
        with pytest.raises(LossyEditError, match="allow-lossy"):
            fidelity.guard(at_risk_workbook)

    def test_allow_lossy_proceeds_and_returns_report(self, at_risk_workbook):
        report = fidelity.guard(at_risk_workbook, allow_lossy=True)
        assert report.at_risk  # still reported, not silenced
        assert report.safe_to_edit is False

    def test_refusal_costs_nothing_the_source_file_is_untouched(self, at_risk_workbook):
        original = at_risk_workbook.read_bytes()
        with pytest.raises(LossyEditError):
            fidelity.guard(at_risk_workbook)
        assert at_risk_workbook.read_bytes() == original


class TestSectionSixOneObservable:
    """The two mechanisms `WriteResult.recalculation_required` and
    `has_cached_values` depend on (full write-path coverage lands with
    xlsx/write.py in Phase 3 step 7)."""

    def test_edit_and_save_destroys_the_injected_cached_value(
        self, tmp_path, cached_value_workbook
    ):
        with ooxml.opened(cached_value_workbook) as wb:
            wb["Sheet"]["A1"] = 99
            output = ooxml.save(wb, tmp_path / "edited.xlsx")
        with ooxml.opened(output, data_only=True) as reopened:
            assert reopened["Sheet"]["A3"].value is None

    def test_edited_file_carries_full_calc_on_load(self, tmp_path, cached_value_workbook):
        with ooxml.opened(cached_value_workbook) as wb:
            wb["Sheet"]["A1"] = 99
            output = ooxml.save(wb, tmp_path / "edited.xlsx")
        with ooxml.opened(output) as reopened:
            assert reopened.calculation.fullCalcOnLoad is True
