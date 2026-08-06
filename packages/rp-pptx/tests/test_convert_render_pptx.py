"""Conversion and rendering — thin re-exports of ``rp_core`` (spec section 4).

No rendering implementation lives in this package, so what is tested here is the
wiring and the refusals, not the raster output. The LibreOffice-dependent tests
use the functional probe from ``conftest``: a container can ship ``soffice`` that
fails every conversion, and a presence check would turn that into confusing
failures rather than honest skips.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from rp_pptx.cli import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, [str(a) for a in args])


class TestRefusals:
    """These hold whether or not LibreOffice is installed."""

    def test_convert_refuses_to_overwrite_its_input(self, simple_deck):
        result = run("convert", simple_deck, "--to", "pdf", "-o", simple_deck)
        assert result.exit_code == 1
        assert "Refusing to overwrite" in result.stderr

    def test_convert_rejects_an_unknown_format(self, simple_deck, tmp_path):
        result = run("convert", simple_deck, "--to", "docx", "-o", tmp_path / "x.docx")
        assert result.exit_code != 0

    def test_render_requires_an_output_directory(self, simple_deck):
        assert run("render", simple_deck).exit_code != 0


@pytest.mark.requires_soffice
class TestConvert:
    def test_converting_to_pdf(self, simple_deck, tmp_path):
        out = tmp_path / "deck.pdf"
        result = run("convert", simple_deck, "--to", "pdf", "-o", out)
        assert result.exit_code == 0, result.stderr
        assert out.is_file()
        assert out.read_bytes().startswith(b"%PDF")

    def test_the_result_names_the_source_and_format(self, simple_deck, tmp_path):
        import json

        out = tmp_path / "deck.pdf"
        result = run("convert", simple_deck, "--to", "pdf", "-o", out)
        payload = json.loads(result.stdout)
        assert payload["format"] == "pdf"
        assert payload["output"] == str(out)


@pytest.mark.requires_soffice
class TestRender:
    def test_rendering_writes_one_image_per_slide(self, simple_deck, tmp_path):
        import json

        result = run("render", simple_deck, "-o", tmp_path / "img", "--dpi", "72")
        assert result.exit_code == 0, result.stderr
        pages = json.loads(result.stdout)
        assert len(pages) == 3, "a slide is a page"
        assert all((tmp_path / "img").joinpath(p["path"].split("/")[-1]).is_file() for p in pages)

    def test_a_slide_selector_limits_the_output(self, simple_deck, tmp_path):
        import json

        result = run("render", simple_deck, "-o", tmp_path / "img", "--slides", "2", "--dpi", "72")
        assert result.exit_code == 0, result.stderr
        assert len(json.loads(result.stdout)) == 1
