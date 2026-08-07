"""CLI tests run against the installed `rp-pdf` entry point via subprocess."""

import json

import pytest


def test_no_json_flag_on_any_command(run_cli):
    """Spec section 10: JSON is the default output and `--plain` is the human
    opt-out, so no `--json` flag exists in the suite."""
    from rp_pdf.cli import COMMAND_NAMES

    for command in sorted(COMMAND_NAMES):
        assert "--json" not in run_cli(command, "--help").stdout, command


def test_doctor_is_json_by_default(run_cli):
    report = json.loads(run_cli("doctor").stdout)
    assert {row["name"] for row in report} == {"pdftotext", "pdftoppm", "pdfinfo"}
    assert not run_cli("doctor", "--plain").stdout.lstrip().startswith(("[", "{"))


def test_index_json(run_cli, text_pdf):
    result = run_cli("index", text_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["page_count"] == 3
    assert data["metadata"]["title"] == "Test Document"
    assert len(data["outline"]) == 3


@pytest.mark.requires_poppler
def test_text_json(run_cli, text_pdf):
    result = run_cli("text", text_pdf, "--pages", "2")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["physical_page"] == 2
    assert "Chapter Two" in data[0]["text"]


@pytest.mark.requires_poppler
def test_text_default_engine_spaces_kerned_pdf(run_cli, kerned_pdf):
    result = run_cli("text", kerned_pdf, "--plain")
    assert result.returncode == 0
    assert "Whether you are looking for a" in result.stdout


def test_text_engine_pypdf(run_cli, kerned_pdf):
    # pure-Python engine: no poppler needed, but mis-segments this PDF (issue #1)
    result = run_cli("text", kerned_pdf, "--engine", "pypdf", "--plain")
    assert result.returncode == 0
    assert "Whetheryouarelooking" in result.stdout


@pytest.mark.requires_poppler
def test_text_plain(run_cli, text_pdf):
    result = run_cli("text", text_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Chapter One" in result.stdout
    assert not result.stdout.lstrip().startswith(("[", "{"))


def test_tables_json(run_cli, table_pdf, table_data):
    result = run_cli("tables", table_pdf, "--pages", "all")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["rows"] == table_data


def test_tables_csv(run_cli, table_pdf, tmp_path):
    result = run_cli("tables", table_pdf, "--csv", tmp_path)
    assert result.returncode == 0
    written = json.loads(result.stdout)["written"]
    assert len(written) == 1
    content = open(written[0], encoding="utf-8").read()
    assert "Name,Qty,Price" in content


def test_tables_csv_labeled_names(run_cli, labeled_table_pdf, tmp_path):
    from pathlib import Path

    result = run_cli("tables", labeled_table_pdf, "--csv", tmp_path)
    assert result.returncode == 0
    written = json.loads(result.stdout)["written"]
    assert Path(written[0]).name == "table_page0030_pp0001_00.csv"


def test_images_metadata(run_cli, image_pdf):
    result = run_cli("images", image_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["width"] == 64
    assert data[0]["saved_path"] is None


@pytest.mark.requires_poppler
def test_password_flag(run_cli, encrypted_pdf, encrypted_password):
    result = run_cli("text", encrypted_pdf, "--pages", "1", "--password", encrypted_password)
    assert result.returncode == 0
    assert "Chapter One" in json.loads(result.stdout)[0]["text"]


@pytest.mark.requires_poppler
def test_labels_default_with_notice(run_cli, labeled_pdf):
    result = run_cli("text", labeled_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Physical page 8" in result.stdout
    assert "page labels" in result.stderr


@pytest.mark.requires_poppler
def test_physical_flag(run_cli, labeled_pdf):
    result = run_cli("text", labeled_pdf, "--pages", "1", "--plain", "--physical")
    assert result.returncode == 0
    assert "Physical page 1" in result.stdout
    assert result.stderr.strip() == ""


@pytest.mark.requires_poppler
def test_no_notice_for_unlabeled_pdf(run_cli, text_pdf):
    result = run_cli("text", text_pdf, "--pages", "1")
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_unknown_label_error(run_cli, labeled_pdf, cli_error):
    result = run_cli("text", labeled_pdf, "--pages", "42")
    assert result.returncode == 1
    assert "No page labeled" in cli_error(result)["message"]


def test_index_shows_labels(run_cli, labeled_pdf):
    result = run_cli("index", labeled_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["has_page_labels"] is True
    assert data["pages"][0]["labeled_page"] == "cover"
    assert data["pages"][7]["labeled_page"] == "1"


@pytest.mark.requires_poppler
def test_unicode_output_is_utf8(run_cli, unicode_pdf):
    # run_cli decodes stdout strictly as UTF-8, so this fails if the CLI writes
    # console-code-page bytes (the Windows default for piped output)
    result = run_cli("text", unicode_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Café — Über naïve résumé" in result.stdout


@pytest.mark.requires_poppler
def test_unicode_json_output(run_cli, unicode_pdf):
    result = run_cli("text", unicode_pdf, "--pages", "1")
    assert result.returncode == 0
    assert "Café" in json.loads(result.stdout)[0]["text"]


def test_error_is_structured(run_cli, tmp_path, cli_error):
    """Spec section 4.1: the ErrorEnvelope on stderr, nothing on stdout."""
    result = run_cli("index", tmp_path / "missing.pdf")
    assert result.returncode == 1
    assert result.stdout == ""
    assert cli_error(result) == {
        "type": "MissingFileError",
        "message": f"No such file: {tmp_path / 'missing.pdf'}",
        "hint": None,
        "exit_code": 1,
    }


def test_page_range_error(run_cli, text_pdf, cli_error):
    result = run_cli("text", text_pdf, "--pages", "99")
    assert result.returncode == 1
    assert "1-3" in cli_error(result)["message"]


def test_markdown_stdout(run_cli, table_pdf):
    result = run_cli("markdown", table_pdf)
    assert result.returncode == 0
    assert "| Name | Qty | Price |" in result.stdout
    assert "<!-- page 1 -->" in result.stdout


def test_markdown_out_file(run_cli, table_pdf, tmp_path):
    target = tmp_path / "out.md"
    result = run_cli("markdown", table_pdf, "-o", target)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "| Apple | 3 | 1.20 |" in target.read_text(encoding="utf-8")


def test_markdown_full(run_cli, table_pdf):
    result = run_cli("markdown", table_pdf, "--full")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["pages"][0]["physical_page"] == 1
    assert data["pages"][0]["ai_refined"] is False
    assert "| Name | Qty | Price |" in data["markdown"]
    assert data["warnings"] == []


def test_markdown_ai_config_error(run_cli, table_pdf, cli_error):
    result = run_cli("markdown", table_pdf, "--ai")
    assert result.returncode == 1
    assert "model" in cli_error(result)["message"]


@pytest.mark.requires_poppler
def test_render(run_cli, text_pdf, tmp_path):
    result = run_cli("render", text_pdf, "--pages", "1", "--out", tmp_path, "--dpi", "72")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["physical_page"] == 1
    assert data[0]["dpi"] == 72


def test_markdown_ocr_requires_ai_flag(run_cli, table_pdf, cli_error):
    result = run_cli("markdown", table_pdf, "--ocr")
    assert result.returncode == 1
    assert "--ai" in cli_error(result)["message"]


def test_validate_vlm_ocr_config_error(run_cli, cli_error):
    result = run_cli("validate-vlm-ocr")
    assert result.returncode == 1
    assert "model" in cli_error(result)["message"]


# --------------------------------------------------------------------------- #
# --describe / --progress: human affordances on stderr, off for everyone else
# --------------------------------------------------------------------------- #
class TestDescribeAndProgress:
    """The contract that keeps these safe to add: stdout is byte-for-byte what
    it was, and stderr stays empty unless a human is watching or asked."""

    def test_neither_appears_when_stderr_is_a_pipe(self, run_cli, text_pdf):
        result = run_cli("index", text_pdf)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_describe_writes_to_stderr_and_leaves_stdout_parseable(self, run_cli, text_pdf):
        result = run_cli("images", text_pdf, "--describe", "--no-progress")
        assert result.returncode == 0
        assert result.stderr.startswith("rp-pdf images — ")
        assert isinstance(json.loads(result.stdout), list)

    def test_progress_writes_to_stderr_and_leaves_stdout_parseable(self, run_cli, text_pdf):
        result = run_cli("images", text_pdf, "--progress", "--no-describe")
        assert result.returncode == 0
        assert "Extracting images: done 3/3" in result.stderr
        assert isinstance(json.loads(result.stdout), list)

    def test_no_describe_and_no_progress_silence_them(self, run_cli, text_pdf):
        result = run_cli("images", text_pdf, "--no-describe", "--no-progress")
        assert result.stderr == ""

    def test_markdown_body_on_stdout_is_unaffected(self, run_cli, text_pdf):
        """The one that would actually corrupt output: `markdown` writes its
        body to stdout, so a description leaking there is a broken document."""
        described = run_cli("markdown", text_pdf, "--engine", "pypdf", "--describe", "--progress")
        quiet = run_cli("markdown", text_pdf, "--engine", "pypdf", "--no-describe")
        assert described.stdout == quiet.stdout
        assert "rp-pdf markdown" in described.stderr

    def test_describe_reports_the_resolved_options_not_the_typed_ones(self, run_cli, text_pdf):
        """Defaults the user never typed are part of what they need to check."""
        result = run_cli("markdown", text_pdf, "--engine", "pypdf", "--describe")
        assert "AI review  off" in result.stderr
        assert "pypdf" in result.stderr

    def test_the_describe_flag_appears_on_the_job_commands(self, run_cli):
        for command in ("text", "tables", "search", "images", "markdown", "render"):
            help_text = run_cli(command, "--help").stdout
            assert "--describe" in help_text, command
            assert "--progress" in help_text, command
            assert "--save-config" in help_text, command

    def test_the_flags_stay_off_commands_with_no_job_to_describe(self, run_cli):
        """`index` and `doctor` are near-instant and have nothing to configure;
        an option that never helps is still an option to read past."""
        for command in ("index", "doctor"):
            help_text = run_cli(command, "--help").stdout
            assert "--progress" not in help_text, command
