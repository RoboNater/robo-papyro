"""Human-readable descriptions of a job, from the options it resolved to.

The problem: by the time a command runs, its options have come from four places
(flag → env → config file → built-in default), and the expensive ones — the AI
pass, OCR, the model behind them — cost money and minutes when they are wrong.
Printing what is about to happen, before it happens, is cheaper than reading it
back out of a bill.

Every function here takes the ``values`` dict the CLI already built to resolve
and (with ``--save-config``) persist its options, and returns
``(title, entries)`` for :func:`rp_core.clikit.job`. That dict is the single
source of truth: a description cannot drift from what will actually run, and
cannot drift from what gets saved, because all three read the same mapping.
The keys are the *config* keys, which is what makes that sharing work.

Off switches are described as well as on ones, with the flag that turns them on
in parentheses. That is the half people check: "did I remember ``--ocr``?" is a
question the description should answer without being asked.

Pure formatting — nothing here reads a file, a flag, or the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

Entries = list[tuple[str, str]]


def _title(command: str, file: Path | str | None = None) -> str:
    return f"rp-pdf {command}" if file is None else f"rp-pdf {command} — {file}"


def _pages(values: dict[str, Any]) -> Entries:
    """Page selection and how the spec will be read, which is the setting most
    often wrong by accident: page 5 of a book is rarely the fifth page."""
    spec = str(values.get("pages", "all"))
    entries: Entries = [("pages", spec)]
    if spec.strip().lower() != "all":
        entries.append(
            (
                "numbering",
                "physical positions (first page = 1)"
                if values.get("physical")
                else "the PDF's page labels where it has them (--physical to override)",
            )
        )
    return entries


def _output(target: Path | str | None, *, otherwise: str) -> tuple[str, str]:
    return ("output", str(target) if target is not None else otherwise)


def text_job(file: Path, values: dict[str, Any]) -> tuple[str, Entries]:
    entries = _pages(values)
    entries.append(("engine", _engine(values)))
    entries.append(("layout", "preserved" if values.get("layout") else "not preserved"))
    entries.append(("output", "raw text" if values.get("plain") else "JSON"))
    return _title("text", file), entries


def tables_job(file: Path, values: dict[str, Any]) -> tuple[str, Entries]:
    entries = _pages(values)
    entries.append(_output(values.get("csv"), otherwise="JSON on stdout (--csv DIR for files)"))
    return _title("tables", file), entries


def search_job(file: Path, query: str, values: dict[str, Any]) -> tuple[str, Entries]:
    entries: Entries = [
        ("query", f"{query!r} ({'regex' if values.get('regex') else 'phrase'})"),
        (
            "matching",
            "case-sensitive" if values.get("case_sensitive") else "case-insensitive",
        ),
    ]
    entries.extend(_pages(values))
    entries.append(("engine", _engine(values)))
    entries.append(("limit", f"{values.get('max')} hits"))
    return _title("search", file), entries


def images_job(file: Path, values: dict[str, Any]) -> tuple[str, Entries]:
    entries = _pages(values)
    entries.append(
        _output(values.get("out"), otherwise="metadata only, no files written (--out DIR to save)")
    )
    return _title("images", file), entries


def render_job(file: Path, values: dict[str, Any]) -> tuple[str, Entries]:
    entries = _pages(values)
    entries.append(("format", f"{values.get('format')} at {values.get('dpi')} dpi"))
    entries.append(("output", str(values.get("out"))))
    return _title("render", file), entries


def markdown_job(file: Path, values: dict[str, Any]) -> tuple[str, Entries]:
    """The one that matters most: the AI and OCR passes are the slow, billable
    stages, so each says whether it will run, and with what."""
    entries = _pages(values)
    entries.append(("engine", _engine(values)))

    images_dir = values.get("images_dir")
    entries.append(
        (
            "images",
            f"extracted to {images_dir} and linked"
            if images_dir is not None
            else "skipped (--images-dir DIR to extract and link them)",
        )
    )

    ai = bool(values.get("ai"))
    entries.append(("AI review", _ai(values) if ai else "off (--ai to review pages with a VLM)"))
    entries.append(("OCR", _ocr(values, ai=ai)))
    entries.append(("outline", _outline(values, ai=ai)))
    if ai:
        entries.append(("cache", _cache(values)))
    entries.append(
        _output(values.get("out"), otherwise="Markdown on stdout (-o FILE to write a file)")
    )
    if values.get("full"):
        entries.append(("form", "full MarkdownResult as JSON (--full)"))
    return _title("markdown", file), entries


def _engine(values: dict[str, Any]) -> str:
    engine = str(values.get("engine", "poppler"))
    if engine == "poppler":
        return "poppler (needs pdftotext installed)"
    return f"{engine} (in-process; may run words together — see issue #1)"


def _ai(values: dict[str, Any]) -> str:
    """What the AI pass will actually talk to. An unset model is worth showing as
    unset: it is the single most common reason the pass fails on first use."""
    model = values.get("model") or "unset — RP_PDF_VLM_MODEL or --model is required"
    where = values.get("base_url") or "the OpenAI default endpoint"
    detail = f"on, model {model} at {where}"
    if values.get("organization"):
        detail += f", org {values['organization']}"
    return f"{detail}; {values.get('jobs')} concurrent, pages rendered at {values.get('dpi')} dpi"


def _ocr(values: dict[str, Any], *, ai: bool) -> str:
    if not values.get("ocr"):
        hint = "--ocr" if ai else "--ai --ocr"
        return f"off — pages with no text layer stay empty ({hint} to transcribe them)"
    return "on — pages with no text layer are transcribed by the same model"


def _outline(values: dict[str, Any], *, ai: bool) -> str:
    parts = []
    if values.get("outline_headings"):
        parts.append("bookmark titles promoted to headings")
    if values.get("outline_context"):
        parts.append("outline path sent to the VLM")
    if not parts:
        return "not used (--outline-headings, --outline-context; no-ops without bookmarks)"
    suffix = "" if ai or not values.get("outline_context") else " — requires --ai"
    return "; ".join(parts) + suffix


def _cache(values: dict[str, Any]) -> str:
    if not values.get("cache", True):
        return "off (--cache to reuse previous responses)"
    location = values.get("cache_dir") or "~/.cache/rp-pdf"
    return f"on — responses reused from {location}"
