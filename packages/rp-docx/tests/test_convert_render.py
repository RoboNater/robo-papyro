"""Conversion and rendering — thin re-exports of ``rp_core`` (spec section 4).

No rendering implementation lives in rp-docx, so what is tested here is the
wiring: the right rp_core entry point, the right errors when a binary is
missing, and output landing where the CLI said it would.

Everything needing LibreOffice carries ``@pytest.mark.requires_soffice`` and
skips cleanly when it is absent (spec section 11.3).
"""

from __future__ import annotations

import json

import pytest

from rp_core.errors import MissingDependencyError


class TestWiring:
    def test_render_delegates_to_rp_core(self, monkeypatch, page_break_docx, tmp_path):
        """rp-docx has no numbering or naming requirements beyond the default,
        so it uses render_pages and never touches rasterize (spec section 4)."""
        from rp_core import render as core_render

        calls: list[tuple] = []

        def fake(source, output_dir, **kwargs):
            calls.append((source, output_dir, kwargs))
            return [output_dir / "page0001.png"]

        monkeypatch.setattr(core_render, "render_pages", fake)
        from rp_docx import cli

        monkeypatch.setattr(cli.core_render, "render_pages", fake)
        from typer.testing import CliRunner

        result = CliRunner().invoke(
            cli.app, ["render", str(page_break_docx), "-o", str(tmp_path), "--pages", "1-2"]
        )
        assert result.exit_code == 0
        assert calls[0][2]["pages"] == "1-2"
        assert calls[0][2]["dpi"] == 150

    def test_a_missing_binary_is_exit_code_two(self, monkeypatch, page_break_docx, tmp_path):
        from rp_docx import cli

        def missing(*_, **__):
            raise MissingDependencyError(
                "soffice is required but was not found on PATH.",
                binary="soffice",
                install_hint="Install LibreOffice.",
            )

        monkeypatch.setattr(cli.binaries, "soffice_convert", missing)
        from typer.testing import CliRunner

        result = CliRunner().invoke(
            cli.app, ["convert", str(page_break_docx), "--to", "pdf", "-o", str(tmp_path / "o.pdf")]
        )
        assert result.exit_code == 2

    def test_convert_delegates_to_rp_core(self, monkeypatch, page_break_docx, tmp_path):
        """soffice_convert carries the profile isolation, output verification,
        and timeout the suite depends on (parent spec section 4.4); rp-docx must
        route through it rather than shelling out itself."""
        from rp_docx import cli

        def fake(source, to, outdir, **kwargs):
            produced = outdir / f"{source.stem}.{to}"
            produced.write_bytes(b"%PDF-1.4\n")
            return produced

        monkeypatch.setattr(cli.binaries, "soffice_convert", fake)
        from typer.testing import CliRunner

        target = tmp_path / "out.pdf"
        result = CliRunner().invoke(
            cli.app, ["convert", str(page_break_docx), "--to", "pdf", "-o", str(target)]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["output"] == str(target)
        assert target.is_file()

    def test_convert_refuses_to_overwrite_its_input(self, monkeypatch, tmp_path):
        """Never overwrite an input file (parent spec section 10). Reached before
        LibreOffice is invoked, so it holds whether or not one is installed."""
        from rp_docx import cli

        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        monkeypatch.setattr(
            cli.binaries, "soffice_convert", lambda *a, **k: pytest.fail("must not be called")
        )
        from typer.testing import CliRunner

        result = CliRunner().invoke(
            cli.app, ["convert", str(source), "--to", "pdf", "-o", str(source)]
        )
        assert result.exit_code == 1
        assert "Refusing to overwrite" in result.output


@pytest.mark.requires_soffice
class TestWithLibreOffice:
    def test_convert_to_pdf(self, run_cli, page_break_docx, tmp_path):
        target = tmp_path / "out.pdf"
        result = run_cli("convert", page_break_docx, "--to", "pdf", "-o", target)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["format"] == "pdf"
        assert target.is_file() and target.read_bytes()[:5] == b"%PDF-"

    def test_convert_defaults_the_output_name(self, run_cli, page_break_docx, tmp_path):
        source = tmp_path / "doc.docx"
        source.write_bytes(page_break_docx.read_bytes())
        result = run_cli("convert", source, "--to", "odt")
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "doc.odt").is_file()

    def test_render_writes_page_images(self, run_cli, page_break_docx, tmp_path):
        result = run_cli("render", page_break_docx, "-o", tmp_path / "pages", "--dpi", "72")
        assert result.returncode == 0, result.stderr
        rows = json.loads(result.stdout)
        assert len(rows) == 3
        assert all(row["page"] == index for index, row in enumerate(rows, start=1))

    def test_render_honours_a_page_range(self, run_cli, page_break_docx, tmp_path):
        result = run_cli(
            "render", page_break_docx, "-o", tmp_path / "pages", "--dpi", "72", "--pages", "2"
        )
        assert result.returncode == 0, result.stderr
        assert len(json.loads(result.stdout)) == 1
