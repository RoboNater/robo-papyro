"""Rasterization. The poppler-backed tests need poppler; the routing tests do
not, and mock soffice_convert instead so LibreOffice is never a prerequisite."""

from __future__ import annotations

import shutil

import pytest

from rp_core import render
from rp_core.errors import MissingDependencyError
from rp_core.models import RasterImage

requires_poppler = pytest.mark.skipif(
    not (shutil.which("pdftoppm") and shutil.which("pdfinfo")),
    reason="poppler (pdftoppm/pdfinfo) not installed",
)


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    """A three-page PDF, hand-built so this package needs no PDF library."""
    pages = []
    content = b"BT /F1 24 Tf 72 700 Td (Page) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>",
    ]
    for i in range(3):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 9 0 R >> >> /Contents %d 0 R >>" % (4 + i * 2)
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path = tmp_path_factory.mktemp("render") / "three.pdf"
    path.write_bytes(bytes(out))
    pages.append(path)
    return path


class TestNormalizeFormat:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [("png", ("png", "png")), ("jpg", ("jpeg", "jpg")), ("JPEG", ("jpeg", "jpg"))],
    )
    def test_aliases(self, given, expected):
        assert render.normalize_format(given) == expected


@requires_poppler
class TestRasterize:
    def test_writes_one_file_per_page(self, pdf, tmp_path):
        images = render.rasterize(pdf, tmp_path, first_page=1, last_page=3, dpi=72)
        assert len(images) == 3
        assert all(isinstance(i, RasterImage) and i.path.is_file() for i in images)

    def test_default_naming(self, pdf, tmp_path):
        images = render.rasterize(pdf, tmp_path, first_page=2, last_page=2, dpi=72)
        assert images[0].path.name == "page0002.png"

    def test_caller_controls_naming(self, pdf, tmp_path):
        """rp-core owns the poppler call; the caller owns the filenames."""
        images = render.rasterize(
            pdf, tmp_path, first_page=1, last_page=1, dpi=72, name=lambda n: f"custom-{n}"
        )
        assert images[0].path.name == "custom-1.png"

    def test_dpi_scales_output(self, pdf, tmp_path):
        at72 = render.rasterize(pdf, tmp_path / "a", first_page=1, last_page=1, dpi=72)
        at144 = render.rasterize(pdf, tmp_path / "b", first_page=1, last_page=1, dpi=144)
        assert at144[0].width == pytest.approx(at72[0].width * 2, abs=4)

    def test_jpeg_extension(self, pdf, tmp_path):
        images = render.rasterize(pdf, tmp_path, first_page=1, last_page=1, dpi=72, fmt="jpg")
        assert images[0].path.suffix == ".jpg"

    def test_creates_the_output_directory(self, pdf, tmp_path):
        target = tmp_path / "does" / "not" / "exist"
        render.rasterize(pdf, target, first_page=1, last_page=1, dpi=72)
        assert target.is_dir()

    def test_non_contiguous_pages(self, pdf, tmp_path):
        images = render.rasterize_pages(pdf, tmp_path, [1, 3], dpi=72)
        assert [i.path.name for i in images] == ["page0001.png", "page0003.png"]


@requires_poppler
class TestRenderPages:
    def test_all_pages_by_default(self, pdf, tmp_path):
        assert len(render.render_pages(pdf, tmp_path, dpi=72)) == 3

    def test_page_spec_selects_pages(self, pdf, tmp_path):
        paths = render.render_pages(pdf, tmp_path, dpi=72, pages="1,3")
        assert [p.name for p in paths] == ["page0001.png", "page0003.png"]

    def test_returns_paths(self, pdf, tmp_path):
        assert all(p.is_file() for p in render.render_pages(pdf, tmp_path, dpi=72, pages="2"))

    def test_out_of_range_page_spec_is_an_input_error(self, pdf, tmp_path):
        from rp_core.errors import InputError

        with pytest.raises(InputError):
            render.render_pages(pdf, tmp_path, dpi=72, pages="9")


class TestRouting:
    def test_non_pdf_goes_through_soffice(self, monkeypatch, tmp_path):
        """A .docx must be converted to PDF before poppler ever sees it."""
        converted: list[str] = []

        def fake_convert(source, to, outdir, **kwargs):
            converted.append(to)
            target = outdir / f"{source.stem}.pdf"
            target.write_bytes(b"%PDF")
            return target

        monkeypatch.setattr(render, "soffice_convert", fake_convert)
        monkeypatch.setattr(
            render, "_render_pdf", lambda source, output_dir, **kw: [output_dir / "page0001.png"]
        )
        source = tmp_path / "memo.docx"
        source.write_bytes(b"PK\x03\x04")
        render.render_pages(source, tmp_path / "out")
        assert converted == ["pdf"]

    def test_pdf_skips_soffice(self, monkeypatch, tmp_path):
        def explode(*args, **kwargs):
            raise AssertionError("soffice must not be invoked for a PDF source")

        monkeypatch.setattr(render, "soffice_convert", explode)
        monkeypatch.setattr(render, "_render_pdf", lambda source, output_dir, **kw: [])
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")
        assert render.render_pages(source, tmp_path / "out") == []

    def test_missing_poppler_raises_missing_dependency(self, monkeypatch, tmp_path):
        import pdf2image
        from pdf2image.exceptions import PDFInfoNotInstalledError

        def absent(*args, **kwargs):
            raise PDFInfoNotInstalledError("no pdftoppm")

        monkeypatch.setattr(pdf2image, "convert_from_path", absent)
        source = tmp_path / "doc.pdf"
        source.write_bytes(b"%PDF")
        with pytest.raises(MissingDependencyError) as excinfo:
            render.rasterize(source, tmp_path / "out", first_page=1, last_page=1)
        assert excinfo.value.exit_code == 2
        assert excinfo.value.binary == "pdftoppm"
