from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pptx import Presentation

from rp_core.errors import InputError
from rp_pptx.errors import InvalidPptxError, MissingFileError

PRESENTATION = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
TEMPLATE = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"


def check_readable(path: Path) -> Path:
    path = Path(path)
    if not path.is_file():
        raise MissingFileError(f"No such file: {path}")
    if not zipfile.is_zipfile(path):
        raise InvalidPptxError(f"{path.name} is not an OOXML PowerPoint package")
    return path


def _retype(source: Path, target: Path, old: str, new: str) -> Path:
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "[Content_Types].xml":
                data = data.replace(old.encode(), new.encode())
            dst.writestr(info, data, compress_type=info.compress_type)
    return target


def is_template(path: Path) -> bool:
    with zipfile.ZipFile(check_readable(path)) as archive:
        return TEMPLATE.encode() in archive.read("[Content_Types].xml")


@contextmanager
def opened(path: Path) -> Iterator[Presentation]:
    path = check_readable(path)
    with tempfile.TemporaryDirectory(prefix="rp-pptx-open-") as tmp:
        target = path
        if is_template(path):
            target = _retype(path, Path(tmp) / "template.pptx", TEMPLATE, PRESENTATION)
        try:
            yield Presentation(target)
        except Exception as exc:
            raise InvalidPptxError(f"Cannot open {path.name}: {exc}") from exc


def save(prs: Presentation, output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".potx":
        with tempfile.TemporaryDirectory(prefix="rp-pptx-save-") as tmp:
            staged = Path(tmp) / "deck.pptx"
            prs.save(staged)
            _retype(staged, output, PRESENTATION, TEMPLATE)
    else:
        prs.save(output)
    return output


def copy_for_edit(path: Path, output: Path | None) -> tuple[Presentation, Path]:
    if output is None:
        raise InputError("An output path is required (the library never overwrites implicitly)")
    with opened(path) as prs:
        target = Path(output)
        # detach the package by serializing before the context closes
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            tmp = Path(f.name)
        prs.save(tmp)
    detached = Presentation(tmp)
    tmp.unlink()
    return detached, target
