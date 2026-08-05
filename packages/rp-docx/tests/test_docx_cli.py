"""The CLI: JSON by default, --plain for humans, ErrorEnvelopes on stderr.

These drive the installed ``rp-docx`` console script through a subprocess, so
what is tested is what a user (or an agent) actually gets — entry-point wiring
included.
"""

from __future__ import annotations

import json

import pytest

from rp_docx import ooxml


class TestOutputShape:
    def test_json_is_the_default_with_no_flag(self, run_cli, simple_docx):
        """Parent spec section 4.6: a caller that passes no flag must get JSON
        without having to think about it."""
        result = run_cli("index", simple_docx)
        assert result.returncode == 0
        assert json.loads(result.stdout)["paragraph_count"] == 4

    def test_plain_is_the_human_opt_out(self, run_cli, simple_docx):
        result = run_cli("index", simple_docx, "--plain")
        assert result.returncode == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)
        assert "paragraph_count" in result.stdout

    def test_there_is_no_json_flag(self, run_cli, simple_docx):
        result = run_cli("index", simple_docx, "--json")
        assert result.returncode != 0
        assert "No such option" in result.stderr or "Usage" in result.stderr

    def test_results_go_to_stdout_and_nothing_else_does(self, run_cli, simple_docx):
        result = run_cli("text", simple_docx)
        json.loads(result.stdout)  # parses cleanly, so nothing leaked into it

    def test_a_list_result_is_a_json_array(self, run_cli, simple_docx):
        assert isinstance(json.loads(run_cli("text", simple_docx).stdout), list)


class TestErrors:
    def test_a_missing_file_exits_one_with_an_envelope(self, run_cli, cli_error, tmp_path):
        result = run_cli("index", tmp_path / "nope.docx")
        assert result.returncode == 1
        detail = cli_error(result)
        assert detail["type"] == "MissingFileError"
        assert detail["exit_code"] == 1

    def test_a_corrupt_file_exits_three(self, run_cli, cli_error, not_a_docx):
        result = run_cli("index", not_a_docx)
        assert result.returncode == 3
        assert cli_error(result)["type"] == "InvalidDocxError"

    def test_stdout_stays_empty_on_failure(self, run_cli, tmp_path):
        result = run_cli("index", tmp_path / "nope.docx")
        assert result.stdout == ""

    def test_the_envelope_is_the_last_line_of_stderr(self, run_cli, cli_error, tmp_path):
        """So it is findable without parsing the whole stream, whatever warnings
        preceded it."""
        result = run_cli("index", tmp_path / "nope.docx")
        assert set(cli_error(result)) == {"type", "message", "hint", "exit_code"}

    def test_an_unresolvable_template_exits_one(self, run_cli, cli_error, tmp_path, monkeypatch):
        result = run_cli("create", "--out", tmp_path / "o.docx", "--template", "nonexistent")
        assert result.returncode == 1
        assert cli_error(result)["type"] == "TemplateError"


class TestReadCommands:
    def test_text(self, run_cli, simple_docx):
        rows = json.loads(run_cli("text", simple_docx).stdout)
        assert rows[0]["text"] == "Title"

    def test_text_with_a_style_filter(self, run_cli, simple_docx):
        rows = json.loads(run_cli("text", simple_docx, "--style", "Heading 1").stdout)
        assert [row["text"] for row in rows] == ["Title"]

    def test_text_with_runs(self, run_cli, rich_docx):
        rows = json.loads(run_cli("text", rich_docx, "--runs").stdout)
        assert any(row["runs"] for row in rows)

    def test_text_plain_is_one_line_per_paragraph(self, run_cli, simple_docx):
        lines = run_cli("text", simple_docx, "--plain").stdout.strip().splitlines()
        assert len(lines) == 4
        assert "[Heading 1]" in lines[0]

    def test_markdown_to_stdout(self, run_cli, simple_docx):
        assert "# Title" in run_cli("markdown", simple_docx).stdout

    def test_markdown_to_a_file(self, run_cli, simple_docx, tmp_path):
        target = tmp_path / "out.md"
        result = run_cli("markdown", simple_docx, "-o", target)
        assert result.returncode == 0
        assert "# Title" in target.read_text(encoding="utf-8")

    def test_tables_as_json(self, run_cli, rich_docx):
        assert len(json.loads(run_cli("tables", rich_docx).stdout)) == 3

    def test_tables_as_csv(self, run_cli, rich_docx, tmp_path):
        result = run_cli("tables", rich_docx, "--format", "csv", "-o", tmp_path / "csv")
        written = json.loads(result.stdout)["written"]
        assert len(written) == 3
        assert "Region,Units,Revenue" in (tmp_path / "csv" / "table_01.csv").read_text()

    def test_csv_without_an_output_directory_is_an_error(self, run_cli, cli_error, rich_docx):
        result = run_cli("tables", rich_docx, "--format", "csv")
        assert result.returncode == 1
        assert "--out" in cli_error(result)["message"]

    def test_tables_as_markdown(self, run_cli, rich_docx):
        out = run_cli("tables", rich_docx, "--format", "md").stdout
        assert "| Region | Units | Revenue |" in out
        assert "|---|---|---|" in out

    def test_images_metadata_without_extracting(self, run_cli, rich_docx):
        rows = json.loads(run_cli("images", rich_docx).stdout)
        assert rows[0]["extracted_path"] is None

    def test_images_extracted(self, run_cli, rich_docx, tmp_path):
        rows = json.loads(run_cli("images", rich_docx, "-o", tmp_path / "img").stdout)
        assert (tmp_path / "img").is_dir()
        assert rows[0]["extracted_path"] is not None

    def test_comments(self, run_cli, comments_docx):
        rows = json.loads(run_cli("comments", comments_docx).stdout)
        assert {row["author"] for row in rows} == {"Ada Lovelace", "Grace Hopper"}

    def test_comments_filtered_by_author(self, run_cli, comments_docx):
        rows = json.loads(run_cli("comments", comments_docx, "--author", "Ada Lovelace").stdout)
        assert len(rows) == 1

    def test_changes(self, run_cli, tracked_changes_docx):
        rows = json.loads(run_cli("changes", tracked_changes_docx).stdout)
        assert {row["type"] for row in rows} == {"insertion", "deletion", "format"}

    def test_props(self, run_cli, rich_docx):
        assert json.loads(run_cli("props", rich_docx).stdout)["title"] == "Quarterly Report"


class TestWriteCommands:
    def test_create_from_markdown(self, run_cli, tmp_path):
        source = tmp_path / "in.md"
        source.write_text("# Title\n\nBody.", encoding="utf-8")
        target = tmp_path / "out.docx"
        result = run_cli("create", "-o", target, "--from-markdown", source)
        assert result.returncode == 0
        assert json.loads(result.stdout)["output"] == str(target)
        assert target.is_file()

    def test_create_reports_an_ignored_page_size(self, run_cli, tmp_path, minimal_template):
        """A template wins on page setup, and saying so beats silently dropping
        the flag the user typed."""
        result = run_cli(
            "create",
            "-o",
            tmp_path / "out.docx",
            "--template",
            minimal_template,
            "--page-size",
            "a4",
        )
        assert result.returncode == 0
        assert "page-size is ignored" in result.stderr

    def test_create_with_a_missing_markdown_file(self, run_cli, cli_error, tmp_path):
        result = run_cli("create", "-o", tmp_path / "o.docx", "--from-markdown", tmp_path / "no.md")
        assert result.returncode == 1
        assert "No such markdown file" in cli_error(result)["message"]

    def test_replace_with_inline_json(self, run_cli, split_runs_docx, tmp_path):
        result = run_cli(
            "replace",
            split_runs_docx,
            "--map",
            '{"{{ client.name }}": "Ada"}',
            "-o",
            tmp_path / "out.docx",
        )
        assert json.loads(result.stdout)["replacements"]["{{ client.name }}"] == 2

    def test_replace_with_a_json_file(self, run_cli, split_runs_docx, tmp_path):
        mapping = tmp_path / "map.json"
        mapping.write_text('{"{{ city }}": "Bath"}', encoding="utf-8")
        result = run_cli("replace", split_runs_docx, "--map", mapping, "-o", tmp_path / "o.docx")
        assert json.loads(result.stdout)["replacements"]["{{ city }}"] == 2

    def test_replace_rejects_malformed_json(self, run_cli, cli_error, simple_docx, tmp_path):
        result = run_cli("replace", simple_docx, "--map", "{not json", "-o", tmp_path / "o.docx")
        assert result.returncode == 1
        assert "not valid JSON" in cli_error(result)["message"]

    def test_an_editing_command_refuses_to_guess(self, run_cli, cli_error, simple_docx):
        """Never overwrite an input file without --in-place (spec section 10).
        The two plausible defaults are both surprises, so it asks."""
        result = run_cli("replace", simple_docx, "--map", "{}")
        assert result.returncode == 1
        message = cli_error(result)["message"]
        assert "--out" in message and "--in-place" in message

    def test_out_and_in_place_together_is_an_error(self, run_cli, cli_error, simple_docx, tmp_path):
        result = run_cli(
            "replace", simple_docx, "--map", "{}", "-o", tmp_path / "o.docx", "--in-place"
        )
        assert result.returncode == 1
        assert "not both" in cli_error(result)["message"]

    def test_in_place_edits_the_file(self, run_cli, split_runs_docx, tmp_path):
        copy = tmp_path / "copy.docx"
        copy.write_bytes(split_runs_docx.read_bytes())
        result = run_cli("replace", copy, "--map", '{"{{ city }}": "Bath"}', "--in-place")
        assert json.loads(result.stdout)["output"] == str(copy)

    def test_append(self, run_cli, simple_docx, tmp_path):
        source = tmp_path / "add.md"
        source.write_text("## Added", encoding="utf-8")
        result = run_cli("append", simple_docx, "--markdown", source, "-o", tmp_path / "o.docx")
        assert result.returncode == 0

    def test_template_fill(self, run_cli, split_runs_docx, tmp_path):
        context = '{"client": {"name": "Ada"}, "amount": "40", "city": "Bath"}'
        result = run_cli(
            "template", split_runs_docx, "--context", context, "-o", tmp_path / "f.docx"
        )
        assert json.loads(result.stdout)["unresolved"] == []

    def test_template_fill_strict_failure(self, run_cli, cli_error, split_runs_docx, tmp_path):
        result = run_cli("template", split_runs_docx, "--context", "{}", "-o", tmp_path / "f.docx")
        assert result.returncode == 1
        assert cli_error(result)["type"] == "PlaceholderError"

    def test_template_fill_no_strict(self, run_cli, split_runs_docx, tmp_path):
        result = run_cli(
            "template",
            split_runs_docx,
            "--context",
            "{}",
            "-o",
            tmp_path / "f.docx",
            "--no-strict",
        )
        assert sorted(json.loads(result.stdout)["unresolved"]) == ["amount", "city", "client.name"]

    def test_accept(self, run_cli, tracked_changes_docx, tmp_path):
        result = run_cli("accept", tracked_changes_docx, "-o", tmp_path / "a.docx")
        assert result.returncode == 0
        assert (tmp_path / "a.docx").is_file()

    def test_reject(self, run_cli, tracked_changes_docx, tmp_path):
        result = run_cli("reject", tracked_changes_docx, "-o", tmp_path / "r.docx")
        assert result.returncode == 0


class TestTemplatesCommands:
    def test_list(self, run_cli, monkeypatch, template_dir, minimal_template, house_like_template):
        result = run_cli_with_dir(run_cli, template_dir, "templates", "list")
        names = {row["name"] for row in json.loads(result.stdout)}
        assert {"minimal", "house_like"} <= names

    def test_inspect(self, run_cli, template_dir, house_like_template):
        result = run_cli_with_dir(run_cli, template_dir, "templates", "inspect", "house_like")
        assert json.loads(result.stdout)["page_size"] == "A4"

    def test_manifest_to_stdout(self, run_cli, house_like_template, secret_text):
        result = run_cli("templates", "manifest", house_like_template)
        assert secret_text not in result.stdout
        assert json.loads(result.stdout)["page_size"] == "A4"

    def test_manifest_to_a_file(self, run_cli, house_like_template, tmp_path):
        target = tmp_path / "h.manifest.json"
        run_cli("templates", "manifest", house_like_template, "-o", target)
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "house_like"

    def test_synthesize(self, run_cli, house_like_template, tmp_path):
        manifest = tmp_path / "h.manifest.json"
        run_cli("templates", "manifest", house_like_template, "-o", manifest)
        target = tmp_path / "rebuilt.dotx"
        result = run_cli("templates", "synthesize", manifest, "-o", target)
        assert result.returncode == 0
        assert ooxml.is_template(target)

    def test_stylemap_says_it_needs_review(self, run_cli, house_like_template):
        """Spec section 10 requires the command to say so: a generated stylemap
        that happens to be wrong is worse than none, because it looks reviewed."""
        result = run_cli("templates", "stylemap", house_like_template)
        assert "Review every role" in result.stderr
        assert json.loads(result.stdout)["table"] == "Table Grid"


def run_cli_with_dir(run_cli, template_dir, *args):
    """Run the CLI with RP_DOCX_TEMPLATE_DIR pointed at the fixtures.

    A helper rather than a fixture because monkeypatch does not reach a
    subprocess; the environment has to be set for the child.
    """
    import os
    import subprocess

    env = {**os.environ, "RP_DOCX_TEMPLATE_DIR": str(template_dir)}
    return subprocess.run(
        ["rp-docx", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


class TestDoctor:
    def test_doctor_reports_capabilities(self, run_cli):
        rows = json.loads(run_cli("doctor").stdout)
        assert {row["name"] for row in rows} == {"soffice", "pdftoppm", "pdfinfo"}


class TestUmbrella:
    def test_rp_docx_and_rp_docx_are_the_same_code_path(self, run_cli, run_umbrella, rich_docx):
        """Parent spec section 6: `rp docx index FILE` and `rp-docx index FILE`
        must be the same code path, asserted rather than assumed."""
        direct = run_cli("index", rich_docx)
        umbrella = run_umbrella("index", rich_docx)
        assert direct.returncode == umbrella.returncode == 0
        assert direct.stdout == umbrella.stdout

    def test_errors_match_through_the_umbrella_too(self, run_cli, run_umbrella, tmp_path):
        missing = tmp_path / "nope.docx"
        direct, umbrella = run_cli("index", missing), run_umbrella("index", missing)
        assert direct.returncode == umbrella.returncode == 1
        assert direct.stderr.splitlines()[-1] == umbrella.stderr.splitlines()[-1]
