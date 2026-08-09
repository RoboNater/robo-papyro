"""rp_xlsx.templates -- resolution (spec section 5.1).

inspect_template/build_manifest/synthesize land in Phase 3 step 8; this
covers resolve_template, needed by write.py's create() in step 7.
"""

from __future__ import annotations

import os

import pytest

from rp_xlsx.errors import TemplateError
from rp_xlsx.templates import resolve_template


class TestResolveTemplate:
    def test_none_returns_none(self, monkeypatch):
        monkeypatch.delenv("RP_XLSX_TEMPLATE", raising=False)
        assert resolve_template(None) is None

    def test_none_uses_configured_default_env_var(self, monkeypatch, plain_workbook):
        monkeypatch.setenv("RP_XLSX_TEMPLATE", str(plain_workbook))
        assert resolve_template(None) == plain_workbook

    def test_existing_path_is_used_as_given(self, plain_workbook):
        assert resolve_template(plain_workbook) == plain_workbook

    def test_existing_path_as_string(self, plain_workbook):
        assert resolve_template(str(plain_workbook)) == plain_workbook

    def test_wrong_path_names_the_path_not_a_template_name(self, tmp_path):
        missing = tmp_path / "nope" / "quarterly.xltx"
        with pytest.raises(TemplateError, match=str(missing)):
            resolve_template(missing)

    def test_bare_name_resolves_against_template_dir_env(self, monkeypatch, tmp_path):
        directory = tmp_path / "templates"
        directory.mkdir()
        (directory / "quarterly.xltx").write_bytes(b"fake")
        monkeypatch.setenv("RP_XLSX_TEMPLATE_DIR", str(directory))
        assert resolve_template("quarterly") == directory / "quarterly.xltx"

    def test_xltx_preferred_over_xlsx_when_both_exist(self, monkeypatch, tmp_path):
        directory = tmp_path / "templates"
        directory.mkdir()
        (directory / "house.xltx").write_bytes(b"fake-template")
        (directory / "house.xlsx").write_bytes(b"fake-workbook")
        monkeypatch.setenv("RP_XLSX_TEMPLATE_DIR", str(directory))
        assert resolve_template("house") == directory / "house.xltx"

    def test_unresolvable_name_lists_available_templates(self, monkeypatch, tmp_path):
        directory = tmp_path / "templates"
        directory.mkdir()
        (directory / "quarterly.xltx").write_bytes(b"fake")
        monkeypatch.setenv("RP_XLSX_TEMPLATE_DIR", str(directory))
        with pytest.raises(TemplateError, match="quarterly"):
            resolve_template("does-not-exist")

    def test_template_dir_env_splits_on_pathsep(self, monkeypatch, tmp_path):
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        (second / "quarterly.xltx").write_bytes(b"fake")
        monkeypatch.setenv("RP_XLSX_TEMPLATE_DIR", f"{first}{os.pathsep}{second}")
        assert resolve_template("quarterly") == second / "quarterly.xltx"
