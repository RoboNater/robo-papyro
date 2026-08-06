"""The CLI surface: JSON by default, ``--plain`` for humans, envelopes on stderr.

Invoked through ``typer.CliRunner`` rather than a subprocess so failures show a
traceback, with one subprocess test to prove the console script and the umbrella
resolve to the same code path.

The options-are-options assertions are deliberate: typer turns a parameter
without a default into a positional argument, which is how the previous version
shipped a ``--map`` that did not exist while its own usage doc advertised one.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from rp_pptx.cli import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, [str(a) for a in args])


def payload(result):
    return json.loads(result.stdout)


@pytest.fixture
def deck(tmp_path, simple_deck):
    return simple_deck


class TestJsonByDefault:
    def test_reads_emit_json_with_no_flag(self, deck):
        result = run("index", deck)
        assert result.exit_code == 0
        assert payload(result)["slide_count"] == 3

    def test_plain_is_not_json(self, deck):
        result = run("index", deck, "--plain")
        assert result.exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)
        assert "slide_count" in result.stdout

    @pytest.mark.parametrize(
        "command", ["index", "text", "tables", "images", "notes", "comments", "charts", "props"]
    )
    def test_every_read_command_takes_plain(self, deck, command):
        assert run(command, deck, "--plain").exit_code == 0

    @pytest.mark.parametrize(
        "command", ["index", "text", "tables", "images", "notes", "comments", "charts", "props"]
    )
    def test_every_read_command_emits_json_by_default(self, deck, command):
        result = run(command, deck)
        assert result.exit_code == 0
        json.loads(result.stdout)


class TestOptionsAreOptions:
    """Section 10 spells these as flags. A positional would still "work" from
    the library's point of view and be undocumentable from the user's."""

    def test_slides_is_a_flag(self, deck):
        result = run("text", deck, "--slides", "2")
        assert result.exit_code == 0
        assert [s["index"] for s in payload(result)] == [2]

    def test_map_is_a_flag(self, deck, tmp_path):
        result = run("replace", deck, "--map", '{"Alpha":"AAA"}', "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0
        assert payload(result)["replacements"] == {"Alpha": 1}

    def test_order_is_a_flag(self, deck, tmp_path):
        result = run("slides", "reorder", deck, "--order", "3,1,2", "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0

    def test_slides_delete_takes_a_flag(self, deck, tmp_path):
        result = run("slides", "delete", deck, "--slides", "2", "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0
        assert payload(result)["slide_count"] == 2

    def test_markdown_is_a_flag_on_append(self, deck, tmp_path):
        source = tmp_path / "add.md"
        source.write_text("## Added\n- x\n", encoding="utf-8")
        result = run("append", deck, "--markdown", source, "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0


class TestJsonArguments:
    def test_a_map_may_be_a_file(self, deck, tmp_path):
        mapping = tmp_path / "m.json"
        mapping.write_text(json.dumps({"Alpha": "AAA"}), encoding="utf-8")
        result = run("replace", deck, "--map", mapping, "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0
        assert payload(result)["replacements"] == {"Alpha": 1}

    def test_malformed_json_is_an_input_error(self, deck, tmp_path):
        result = run("replace", deck, "--map", "{not json", "-o", tmp_path / "o.pptx")
        assert result.exit_code == 1

    def test_a_json_array_is_rejected(self, deck, tmp_path):
        result = run("replace", deck, "--map", "[1,2]", "-o", tmp_path / "o.pptx")
        assert result.exit_code == 1


class TestOutputRules:
    """Section 10: never overwrite an input without ``--in-place``."""

    def test_neither_out_nor_in_place_is_refused(self, deck):
        result = run("replace", deck, "--map", "{}")
        assert result.exit_code == 1
        assert "in-place" in result.stderr

    def test_both_together_are_refused(self, deck, tmp_path):
        result = run("replace", deck, "--map", "{}", "-o", tmp_path / "o.pptx", "--in-place")
        assert result.exit_code == 1

    def test_in_place_writes_to_the_input(self, deck):
        result = run("replace", deck, "--map", '{"Alpha":"AAA"}', "--in-place")
        assert result.exit_code == 0
        assert payload(result)["output"] == str(deck)


class TestExitCodes:
    """Parent spec section 4.1's taxonomy, at the boundary that reports it."""

    def test_success_is_zero(self, deck):
        assert run("index", deck).exit_code == 0

    def test_a_missing_file_is_one(self, tmp_path):
        assert run("index", tmp_path / "nope.pptx").exit_code == 1

    def test_a_non_package_is_three(self, tmp_path):
        broken = tmp_path / "fake.pptx"
        broken.write_text("not a zip", encoding="utf-8")
        assert run("index", broken).exit_code == 3

    def test_a_bad_slide_spec_is_one_not_three(self, deck):
        """The bug this replaced reported exit 3 — a corrupt file — for a typo."""
        assert run("text", deck, "--slides", "99").exit_code == 1

    def test_an_unknown_template_is_one(self, tmp_path, template_env):
        result = run("create", "-o", tmp_path / "x.pptx", "--template", "nonexistent")
        assert result.exit_code == 1

    def test_modern_comments_exit_three(self, modern_comments_deck):
        assert run("comments", modern_comments_deck).exit_code == 3

    def test_the_error_envelope_is_on_stderr_with_the_exit_code(self, tmp_path):
        broken = tmp_path / "fake.pptx"
        broken.write_text("not a zip", encoding="utf-8")
        isolated = CliRunner()
        result = isolated.invoke(app, ["index", str(broken)])
        assert result.exit_code == 3
        envelope = json.loads(result.stderr.strip().splitlines()[-1])
        assert envelope["error"]["type"] == "InvalidPptxError"
        assert envelope["error"]["exit_code"] == 3


class TestCommands:
    def test_create_from_markdown(self, tmp_path):
        source = tmp_path / "in.md"
        source.write_text("# Deck\n\n## One\n- a\n", encoding="utf-8")
        result = run("create", "-o", tmp_path / "d.pptx", "--from-markdown", source)
        assert result.exit_code == 0
        assert (tmp_path / "d.pptx").is_file()

    def test_markdown_to_stdout_and_to_a_file(self, deck, tmp_path):
        assert "## Alpha" in run("markdown", deck).stdout
        result = run("markdown", deck, "-o", tmp_path / "out.md")
        assert result.exit_code == 0
        assert "## Alpha" in (tmp_path / "out.md").read_text()

    def test_tables_in_csv_and_md(self, rich_deck, tmp_path):
        assert "origin" in run("tables", rich_deck, "--format", "csv").stdout
        assert "|---|" in run("tables", rich_deck, "--format", "md").stdout

    def test_tables_written_to_a_directory(self, rich_deck, tmp_path):
        result = run("tables", rich_deck, "--format", "csv", "-o", tmp_path / "tbl")
        assert result.exit_code == 0
        assert (tmp_path / "tbl" / "table-1.csv").is_file()

    def test_images_extracted(self, rich_deck, tmp_path):
        result = run("images", rich_deck, "-o", tmp_path / "img")
        assert result.exit_code == 0
        assert list((tmp_path / "img").iterdir())

    def test_comments_filtered_by_author(self, classic_comments_deck):
        result = run("comments", classic_comments_deck, "--author", "Grace Hopper")
        assert result.exit_code == 0
        assert [c["author"] for c in payload(result)] == ["Grace Hopper"]

    def test_set_notes_from_text(self, deck, tmp_path):
        result = run("set-notes", deck, "--slide", "1", "--text", "hi", "-o", tmp_path / "o.pptx")
        assert result.exit_code == 0

    def test_set_notes_needs_exactly_one_source(self, deck, tmp_path):
        assert run("set-notes", deck, "--slide", "1", "-o", tmp_path / "o.pptx").exit_code == 1

    def test_template_fill(self, tmp_path):
        source = tmp_path / "t.pptx"
        run("create", "-o", source, "--from-markdown", _md(tmp_path, "# Hi {{ name }}\n"))
        result = run("template", source, "--context", '{"name":"Ada"}', "-o", tmp_path / "f.pptx")
        assert result.exit_code == 0
        assert payload(result)["unresolved"] == []

    def test_template_fill_strict_failure_exits_one(self, tmp_path):
        source = tmp_path / "t.pptx"
        run("create", "-o", source, "--from-markdown", _md(tmp_path, "# Hi {{ name }}\n"))
        result = run(
            "template", source, "--context", '{"name":"A","extra":"B"}', "-o", tmp_path / "f.pptx"
        )
        assert result.exit_code == 1

    def test_templates_list_inspect_manifest_synthesize(self, template_env, tmp_path):
        assert run("templates", "list").exit_code == 0
        assert run("templates", "inspect", "house_like").exit_code == 0
        manifest = tmp_path / "m.manifest.json"
        assert (
            run("templates", "manifest", template_env / "house_like.potx", "-o", manifest).exit_code
            == 0
        )
        assert run("templates", "synthesize", manifest, "-o", tmp_path / "s.potx").exit_code == 0
        assert (tmp_path / "s.potx").is_file()

    def test_templates_layoutmap_scaffold_says_it_is_a_guess(self, template_env):
        result = run("templates", "layoutmap", template_env / "house_like.potx")
        assert result.exit_code == 0
        assert "guess" in result.stderr

    def test_doctor_reports_capabilities(self):
        result = run("doctor")
        assert result.exit_code == 0
        assert {entry["name"] for entry in payload(result)} >= {"soffice"}


def _md(tmp_path, body):
    source = tmp_path / "src.md"
    source.write_text(body, encoding="utf-8")
    return source


class TestUmbrellaIdentity:
    """Section 12 step 10: ``rp pptx`` and ``rp-pptx`` must be the same code.

    Run as installed console scripts, because that is the thing being claimed —
    the entry points, the umbrella's discovery of them, and the identical output.
    Invoking the module in-process would prove none of it.
    """

    @staticmethod
    def _scripts():
        direct, umbrella = shutil.which("rp-pptx"), shutil.which("rp")
        if not direct or not umbrella:
            pytest.skip("console scripts are not installed in this environment")
        return direct, umbrella

    def test_both_entry_points_produce_identical_output(self, simple_deck):
        direct, umbrella = self._scripts()
        first = subprocess.run([direct, "index", str(simple_deck)], capture_output=True, text=True)
        second = subprocess.run(
            [umbrella, "pptx", "index", str(simple_deck)], capture_output=True, text=True
        )
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout
        assert json.loads(first.stdout)["slide_count"] == 3

    def test_the_umbrella_lists_pptx(self):
        _, umbrella = self._scripts()
        listed = subprocess.run([umbrella, "--help"], capture_output=True, text=True)
        assert "pptx" in listed.stdout

    def test_exit_codes_survive_the_umbrella(self, tmp_path):
        """An exit code that only works on the direct entry point is worse than
        no exit code, because it looks right in half the invocations."""
        _, umbrella = self._scripts()
        broken = tmp_path / "fake.pptx"
        broken.write_text("not a zip", encoding="utf-8")
        result = subprocess.run(
            [umbrella, "pptx", "index", str(broken)], capture_output=True, text=True
        )
        assert result.returncode == 3
