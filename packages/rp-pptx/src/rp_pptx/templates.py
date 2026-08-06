from __future__ import annotations

import os
from pathlib import Path

import pptx
from pptx import Presentation

from rp_core.errors import InputError
from rp_pptx.models import LayoutDef, LayoutMap, PlaceholderDef, TemplateInfo, TemplateManifest
from rp_pptx.ooxml import is_template, opened, save
from rp_pptx.pptx.read import _ratio


def _roots() -> list[Path]:
    roots = []
    if value := os.getenv("RP_PPTX_TEMPLATE_DIR"):
        roots.append(Path(value))
    roots.extend([Path.cwd() / "templates/local", Path.cwd() / "templates"])
    return roots


def resolve_template(name_or_path: str | Path | None) -> Path:
    if name_or_path is None:
        if configured := os.getenv("RP_PPTX_TEMPLATE"):
            return resolve_template(configured)
        # python-pptx's public ``Presentation()`` uses this bundled file, but
        # resolve_template's contract returns a Path so callers can retain the
        # same explicit template lifecycle as house templates.
        return Path(pptx.__file__).parent / "templates" / "default.pptx"
    value = Path(name_or_path)
    if value.is_file():
        return value
    raw = str(name_or_path)
    if value.suffix or "/" in raw or "\\" in raw:
        raise InputError(f"No such template file: {value}")
    for root in _roots():
        for suffix in (".potx", ".pptx"):
            candidate = root / f"{raw}{suffix}"
            if candidate.is_file():
                return candidate
    available = ", ".join(t.name for t in list_templates()) or "none"
    raise InputError(f"Unknown template {raw!r}; available templates: {available}")


def _layouts(prs) -> list[LayoutDef]:
    result = []
    for master in prs.slide_masters:
        for index, layout in enumerate(master.slide_layouts, 1):
            placeholders = [
                PlaceholderDef(
                    idx=p.placeholder_format.idx,
                    type=str(p.placeholder_format.type).split(" (")[0].lower(),
                    name=p.name,
                )
                for p in layout.placeholders
            ]
            result.append(LayoutDef(name=layout.name, index=index, placeholders=placeholders))
    return result


def inspect_template(path: Path) -> TemplateInfo:
    path = Path(path)
    with opened(path) as prs:
        return TemplateInfo(
            name=path.stem,
            path=path,
            format="potx" if is_template(path) else "pptx",
            slide_width_emu=prs.slide_width,
            slide_height_emu=prs.slide_height,
            aspect_ratio=_ratio(prs.slide_width, prs.slide_height),
            master_count=len(prs.slide_masters),
            layouts=_layouts(prs),
        )


def list_templates() -> list[TemplateInfo]:
    found = {}
    for root in _roots():
        if root.is_dir():
            for path in sorted(root.glob("*.p[op]tx")):
                found.setdefault(path.stem, inspect_template(path))
    return list(found.values())


def load_layoutmap(template: Path) -> LayoutMap:
    sidecar = Path(template).with_suffix(Path(template).suffix + ".layoutmap.json")
    return LayoutMap.model_validate_json(sidecar.read_text()) if sidecar.is_file() else LayoutMap()


def build_manifest(path: Path) -> TemplateManifest:
    info = inspect_template(path)
    sidecar = Path(path).with_suffix(Path(path).suffix + ".layoutmap.json")
    return TemplateManifest(
        name=Path(path).name,
        format=info.format,
        slide_width_emu=info.slide_width_emu,
        slide_height_emu=info.slide_height_emu,
        aspect_ratio=info.aspect_ratio,
        master_count=info.master_count,
        layouts=info.layouts,
        layoutmap=LayoutMap.model_validate_json(sidecar.read_text()) if sidecar.is_file() else None,
    )


def synthesize(manifest: TemplateManifest, output: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = manifest.slide_width_emu, manifest.slide_height_emu
    # python-pptx cannot author masters/layouts; preserve geometry in a valid template.
    return save(prs, output)


def require_layout(prs, name: str):
    layouts = [layout for master in prs.slide_masters for layout in master.slide_layouts]
    for layout in layouts:
        if layout.name == name:
            return layout
    available = ", ".join(layout.name for layout in layouts)
    raise InputError(f"Required layout {name!r} is missing; available layouts: {available}")
