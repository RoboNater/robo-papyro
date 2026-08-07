"""Rasterizing any supported document to page images.

Two layers, because two kinds of caller need different things:

* :func:`rasterize` is the primitive — one PDF, one contiguous physical page
  range, images on disk. It owns the poppler invocation, format normalization,
  and error mapping, and nothing else. It takes physical page numbers only: page
  *labels* are a PDF concept that rp-core deliberately does not model, so a
  caller that has them resolves them first and passes a ``name`` callback to
  control the output filenames.
* :func:`render_pages` is the convenience wrapper — any file, a page spec
  string, PNG paths out. Non-PDF sources are routed through LibreOffice first.
  This is what a leaf package's ``render`` command delegates to when it has no
  format-specific naming to preserve.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from rp_core.binaries import POPPLER_INSTALL_HINT, soffice_convert
from rp_core.errors import MissingDependencyError
from rp_core.models import RasterImage
from rp_core.progress import NULL, Progress
from rp_core.ranges import contiguous_runs, parse_range_spec


def normalize_format(fmt: str) -> tuple[str, str]:
    """``fmt`` as poppler names it, plus the file extension to use for it."""
    fmt = fmt.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    return fmt, ("jpg" if fmt == "jpeg" else fmt)


def default_page_name(physical_page: int) -> str:
    return f"page{physical_page:04d}"


def rasterize(
    source: Path,
    out_dir: Path,
    *,
    first_page: int,
    last_page: int,
    dpi: int = 150,
    fmt: str = "png",
    password: str | None = None,
    poppler_path: str | Path | None = None,
    name: Callable[[int], str] = default_page_name,
) -> list[RasterImage]:
    """Rasterize physical pages ``first_page``..``last_page`` of a PDF.

    ``name`` maps a physical page number to the output file's stem, so callers
    keep control of their own naming scheme. Raises
    :class:`MissingDependencyError` when poppler is absent.
    """
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError

    fmt, ext = normalize_format(fmt)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        images = convert_from_path(
            str(source),
            dpi=dpi,
            fmt=fmt,
            first_page=first_page,
            last_page=last_page,
            userpw=password,
            poppler_path=str(poppler_path) if poppler_path else None,
        )
    except PDFInfoNotInstalledError as exc:
        raise MissingDependencyError(
            f"pdftoppm is required to render pages but was not found. {POPPLER_INSTALL_HINT}",
            binary="pdftoppm",
            install_hint=POPPLER_INSTALL_HINT,
        ) from exc

    results: list[RasterImage] = []
    for offset, image in enumerate(images):
        target = out_dir / f"{name(first_page + offset)}.{ext}"
        image.save(target)
        results.append(RasterImage(path=target, width=image.width, height=image.height))
    return results


def rasterize_pages(
    source: Path,
    out_dir: Path,
    numbers: Sequence[int],
    *,
    progress: Progress | None = None,
    **kwargs,
) -> list[RasterImage]:
    """:func:`rasterize` over an arbitrary set of physical pages, one poppler
    invocation per contiguous run.

    ``progress`` reports one step counted in pages. Poppler renders a whole run
    in a single invocation, so the count moves once per run rather than once per
    page — the elapsed clock, which the reporter ticks on its own thread, is what
    tells a watching human that a slow single-run render is alive.
    """
    reporter = progress if progress is not None else NULL
    results: list[RasterImage] = []
    with reporter.step("Rendering pages", total=len(numbers)) as step:
        for start, end in contiguous_runs(numbers):
            results.extend(rasterize(source, out_dir, first_page=start, last_page=end, **kwargs))
            step.advance(end - start + 1)
    return results


def _page_count(source: Path, poppler_path: str | Path | None = None) -> int:
    from pdf2image import pdfinfo_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError

    try:
        return int(
            pdfinfo_from_path(
                str(source), poppler_path=str(poppler_path) if poppler_path else None
            )["Pages"]
        )
    except PDFInfoNotInstalledError as exc:
        raise MissingDependencyError(
            f"pdfinfo is required to count pages but was not found. {POPPLER_INSTALL_HINT}",
            binary="pdfinfo",
            install_hint=POPPLER_INSTALL_HINT,
        ) from exc


def render_pages(
    source: Path,
    output_dir: Path,
    *,
    dpi: int = 150,
    pages: str | None = None,
    fmt: str = "png",
    poppler_path: str | Path | None = None,
    progress: Progress | None = None,
) -> list[Path]:
    """Render ``source`` to page images in ``output_dir``.

    A PDF goes straight to poppler; anything else is converted to PDF with
    LibreOffice in a temporary directory first. ``pages`` is a page spec
    (``"1-5"``, ``"1,3,7-9"``); ``None`` renders every page.

    ``progress`` reports the LibreOffice conversion and the rasterization as
    separate steps — worth separating because they fail for different reasons and
    a deck that takes a minute in soffice looks identical, from outside, to one
    that is stuck there.
    """
    source = Path(source)
    output_dir = Path(output_dir)
    reporter = progress if progress is not None else NULL

    if source.suffix.lower() == ".pdf":
        return _render_pdf(
            source,
            output_dir,
            dpi=dpi,
            pages=pages,
            fmt=fmt,
            poppler_path=poppler_path,
            progress=reporter,
        )

    with tempfile.TemporaryDirectory(prefix="robo-papyro-render-") as tmp:
        with reporter.step(f"Converting {source.name} to PDF with LibreOffice"):
            as_pdf = soffice_convert(source, "pdf", Path(tmp))
        return _render_pdf(
            as_pdf,
            output_dir,
            dpi=dpi,
            pages=pages,
            fmt=fmt,
            poppler_path=poppler_path,
            progress=reporter,
        )


def _render_pdf(
    source: Path,
    output_dir: Path,
    *,
    dpi: int,
    pages: str | None,
    fmt: str,
    poppler_path: str | Path | None,
    progress: Progress,
) -> list[Path]:
    count = _page_count(source, poppler_path)
    if pages is None or pages.strip().lower() == "all":
        numbers = list(range(1, count + 1))
    else:
        numbers = parse_range_spec(pages, count, noun="page")
    images = rasterize_pages(
        source,
        output_dir,
        numbers,
        dpi=dpi,
        fmt=fmt,
        poppler_path=poppler_path,
        progress=progress,
    )
    return [image.path for image in images]
