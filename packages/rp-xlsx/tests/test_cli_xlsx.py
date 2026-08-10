"""The CLI surface: JSON by default, ``--plain`` for humans, envelopes on
stderr, exit codes matching parent spec section 4.1's taxonomy.

Invoked through ``typer.CliRunner`` rather than a subprocess so failures show
a traceback, with one subprocess test to prove the console script and the
umbrella resolve to the same code path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rp_xlsx.cli import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, [str(a) for a in args])


def payload(result):
    return json.loads(result.stdout)


READ_COMMANDS = [
    "index",
    "data",
    "cells",
    "formulas",
    "tables",
    "names",
    "comments",
    "images",
    "charts",
    "props",
    "fidelity",
]


class TestJsonByDefault:
    def test_reads_emit_json_with_no_flag(self, plain_workbook):
        result = run("index", plain_workbook)
        assert result.exit_code == 0
        assert payload(result)["format"] == "xlsx"

    def test_plain_is_not_json(self, plain_workbook):
        result = run("index", plain_workbook, "--plain")
        assert result.exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)

    @pytest.mark.parametrize("command", READ_COMMANDS)
    def test_every_read_command_takes_plain(self, plain_workbook, command):
        assert run(command, plain_workbook, "--plain").exit_code == 0

    @pytest.mark.parametrize("command", READ_COMMANDS)
    def test_every_read_command_emits_json_by_default(self, plain_workbook, command):
        result = run(command, plain_workbook)
        assert result.exit_code == 0
        json.loads(result.stdout)  # must not raise


class TestOptionsAreOptions:
    """A typer parameter with no default silently becomes a positional
    argument instead, so each flag gets an explicit assertion."""

    def test_sheets_is_a_flag(self, rich_workbook_path):
        assert run("data", rich_workbook_path, "--sheets", "1").exit_code == 0

    def test_map_is_a_flag(self, plain_workbook, tmp_path):
        result = run(
            "set", plain_workbook, "--map", '{"Sheet1": {"A2": 1}}', "-o", tmp_path / "o.xlsx"
        )
        assert result.exit_code == 0

    def test_order_is_a_flag(self, tmp_path):
        source = tmp_path / "src.xlsx"
        spec_file = tmp_path / "sheets.json"
        spec_file.write_text('[{"name": "A", "rows": [["x"]]}]', encoding="utf-8")
        created = run("create", "-o", source, "--from-json", spec_file)
        assert created.exit_code == 0
        result = run(
            "sheets",
            "reorder",
            source,
            "--order",
            "1",
            "-o",
            tmp_path / "o.xlsx",
        )
        assert result.exit_code == 0

    def test_a_map_may_be_a_file(self, plain_workbook, tmp_path):
        mapping = tmp_path / "map.json"
        mapping.write_text('{"Sheet1": {"A2": 5}}', encoding="utf-8")
        result = run("set", plain_workbook, "--map", mapping, "-o", tmp_path / "o.xlsx")
        assert result.exit_code == 0

    def test_malformed_json_is_an_input_error(self, plain_workbook, tmp_path):
        result = run("set", plain_workbook, "--map", "{not json", "-o", tmp_path / "o.xlsx")
        assert result.exit_code == 1

    def test_a_json_array_is_rejected_for_map(self, plain_workbook, tmp_path):
        result = run("set", plain_workbook, "--map", "[]", "-o", tmp_path / "o.xlsx")
        assert result.exit_code == 1


class TestOutputRules:
    def test_neither_out_nor_in_place_is_refused(self, plain_workbook):
        result = run("set", plain_workbook, "--map", '{"Sheet1": {"A2": 1}}')
        assert result.exit_code == 1

    def test_both_together_are_refused(self, plain_workbook, tmp_path):
        result = run(
            "set",
            plain_workbook,
            "--map",
            '{"Sheet1": {"A2": 1}}',
            "-o",
            tmp_path / "o.xlsx",
            "--in-place",
        )
        assert result.exit_code == 1

    def test_in_place_writes_to_the_input(self, plain_workbook):
        before = plain_workbook.read_bytes()
        result = run("set", plain_workbook, "--map", '{"Sheet1": {"A2": 1}}', "--in-place")
        assert result.exit_code == 0
        assert plain_workbook.read_bytes() != before


class TestExitCodes:
    """Parent spec section 4.1's taxonomy, at the boundary that reports it."""

    def test_success_is_zero(self, plain_workbook):
        assert run("index", plain_workbook).exit_code == 0

    def test_a_missing_file_is_one(self, tmp_path):
        assert run("index", tmp_path / "nope.xlsx").exit_code == 1

    def test_a_non_package_is_three(self, tmp_path):
        broken = tmp_path / "fake.xlsx"
        broken.write_text("not a zip", encoding="utf-8")
        assert run("index", broken).exit_code == 3

    def test_a_bad_sheets_spec_is_one_not_three(self, plain_workbook):
        """A typo in --sheets must not be reported as a corrupt file."""
        assert run("data", plain_workbook, "--sheets", "99").exit_code == 1

    def test_an_unknown_template_is_one(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RP_XLSX_TEMPLATE_DIR", raising=False)
        result = run("create", "-o", tmp_path / "x.xlsx", "--template", "nonexistent")
        assert result.exit_code == 1

    def test_lossy_edit_exits_three(self, at_risk_workbook, tmp_path):
        result = run(
            "set", at_risk_workbook, "--map", '{"Sheet1": {"A2": 1}}', "-o", tmp_path / "o.xlsx"
        )
        assert result.exit_code == 3

    def test_the_error_envelope_is_on_stderr_with_the_exit_code(self, tmp_path):
        broken = tmp_path / "fake.xlsx"
        broken.write_text("not a zip", encoding="utf-8")
        isolated = CliRunner()
        result = isolated.invoke(app, ["index", str(broken)])
        assert result.exit_code == 3
        envelope = json.loads(result.stderr.strip().splitlines()[-1])
        assert envelope["error"]["type"] == "InvalidXlsxError"
        assert envelope["error"]["exit_code"] == 3


class TestCommands:
    def test_create_from_json(self, tmp_path):
        source = tmp_path / "sheets.json"
        source.write_text('[{"name": "A", "header": ["H"], "rows": [["x"]]}]', encoding="utf-8")
        result = run("create", "-o", tmp_path / "d.xlsx", "--from-json", source)
        assert result.exit_code == 0
        assert (tmp_path / "d.xlsx").is_file()

    def test_create_from_csv(self, tmp_path):
        source = tmp_path / "in.csv"
        source.write_text("A,B\n1,2\n", encoding="utf-8")
        result = run("create", "-o", tmp_path / "d.xlsx", "--from-csv", source)
        assert result.exit_code == 0

    def test_create_from_markdown(self, tmp_path):
        source = tmp_path / "in.md"
        source.write_text("# Sheet\n\n| A |\n| --- |\n| x |\n", encoding="utf-8")
        result = run("create", "-o", tmp_path / "d.xlsx", "--from-markdown", source)
        assert result.exit_code == 0

    def test_markdown_to_stdout_and_to_a_file(self, rich_workbook_path, tmp_path):
        stdout_result = run("markdown", rich_workbook_path, "--sheets", "1")
        assert stdout_result.exit_code == 0
        assert "## Data" in stdout_result.stdout

        out_file = tmp_path / "out.md"
        file_result = run("markdown", rich_workbook_path, "--sheets", "1", "-o", out_file)
        assert file_result.exit_code == 0
        assert out_file.is_file()
        payload(file_result)  # JSON, not the markdown itself, when -o is given

    def test_data_csv_and_md_formats(self, rich_workbook_path, tmp_path):
        csv_result = run("data", rich_workbook_path, "--sheets", "1", "--format", "csv")
        assert csv_result.exit_code == 0
        md_result = run("data", rich_workbook_path, "--sheets", "1", "--format", "md")
        assert md_result.exit_code == 0

    def test_data_written_to_a_directory(self, rich_workbook_path, tmp_path):
        out = tmp_path / "csvs"
        result = run("data", rich_workbook_path, "--sheets", "1", "--format", "csv", "-o", out)
        assert result.exit_code == 0
        assert any(out.iterdir())

    def test_data_csv_reports_the_source_sheet_per_file(self, tmp_path):
        """A sanitized/deduplicated filename can diverge from the sheet's
        literal name, so the JSON result must say which sheet each file
        came from rather than leaving a caller to guess from the filename."""
        source = tmp_path / "sheets.json"
        source.write_text(
            '[{"name": "Q1|Draft", "header": ["A"], "rows": [["x"]]}]', encoding="utf-8"
        )
        created = run("create", "-o", tmp_path / "src.xlsx", "--from-json", source)
        assert created.exit_code == 0
        out = tmp_path / "csvs"
        result = run("data", tmp_path / "src.xlsx", "--format", "csv", "-o", out)
        assert result.exit_code == 0
        [entry] = payload(result)
        assert entry["sheet"] == "Q1|Draft"
        assert "|" not in Path(entry["output"]).name

    def test_images_extracted(self, rich_workbook_path, tmp_path):
        out = tmp_path / "images"
        result = run("images", rich_workbook_path, "-o", out)
        assert result.exit_code == 0
        assert out.is_dir()

    def test_append_with_rows(self, plain_workbook, tmp_path):
        result = run(
            "append",
            plain_workbook,
            "--sheet",
            "Sheet1",
            "--rows",
            "[[1, 2]]",
            "-o",
            tmp_path / "o.xlsx",
        )
        assert result.exit_code == 0

    def test_append_needs_exactly_one_source(self, plain_workbook, tmp_path):
        result = run("append", plain_workbook, "--sheet", "Sheet1", "-o", tmp_path / "o.xlsx")
        assert result.exit_code == 1

    def test_replace(self, plain_workbook, tmp_path):
        result = run(
            "replace", plain_workbook, "--map", '{"hello": "hi"}', "-o", tmp_path / "o.xlsx"
        )
        assert result.exit_code == 0

    def test_template_fill(self, house_like_template, tmp_path):
        result = run(
            "template",
            house_like_template,
            "--context",
            '{"client": {"name": "Acme"}, "report": {"date": "2024"}}',
            "-o",
            tmp_path / "filled.xlsx",
        )
        assert result.exit_code == 0

    def test_template_fill_strict_failure_exits_one(self, house_like_template, tmp_path):
        result = run(
            "template",
            house_like_template,
            "--context",
            "{}",
            "-o",
            tmp_path / "filled.xlsx",
        )
        assert result.exit_code == 1

    def test_sheets_list_add_rename_delete(self, plain_workbook, tmp_path):
        listed = run("sheets", "list", plain_workbook)
        assert listed.exit_code == 0
        assert payload(listed) == ["Sheet1"]

        added = run("sheets", "add", plain_workbook, "--name", "New", "-o", tmp_path / "a.xlsx")
        assert added.exit_code == 0

        renamed = run(
            "sheets",
            "rename",
            tmp_path / "a.xlsx",
            "--from",
            "New",
            "--to",
            "Renamed",
            "-o",
            tmp_path / "b.xlsx",
        )
        assert renamed.exit_code == 0

        deleted = run(
            "sheets",
            "delete",
            tmp_path / "b.xlsx",
            "--sheet",
            "Renamed",
            "-o",
            tmp_path / "c.xlsx",
        )
        assert deleted.exit_code == 0

    def test_templates_list_inspect_manifest_synthesize(
        self, house_like_template, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("RP_XLSX_TEMPLATE_DIR", str(house_like_template.parent))

        listed = run("templates", "list")
        assert listed.exit_code == 0

        inspected = run("templates", "inspect", house_like_template.stem)
        assert inspected.exit_code == 0

        manifest_path = tmp_path / "m.manifest.json"
        manifested = run("templates", "manifest", house_like_template, "-o", manifest_path)
        assert manifested.exit_code == 0
        assert manifest_path.is_file()

        synthesized = run("templates", "synthesize", manifest_path, "-o", tmp_path / "synth.xltx")
        assert synthesized.exit_code == 0
        assert (tmp_path / "synth.xltx").is_file()

    def test_doctor_reports_capabilities(self):
        result = run("doctor")
        assert result.exit_code == 0
        names = [row["name"] for row in payload(result)]
        assert "soffice" in names


class TestEntryPoints:
    def test_both_entry_points_produce_identical_output(self, plain_workbook):
        via_console_script = subprocess.run(
            ["rp-xlsx", "index", str(plain_workbook)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        via_umbrella = subprocess.run(
            ["rp", "xlsx", "index", str(plain_workbook)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert via_console_script.returncode == via_umbrella.returncode == 0
        assert json.loads(via_console_script.stdout) == json.loads(via_umbrella.stdout)
