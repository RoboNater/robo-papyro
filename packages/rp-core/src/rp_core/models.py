"""Pydantic models shared across the suite.

Format-specific models live in their own package (``rp_pdf.models``,
``rp_docx.models``); only what every package needs belongs here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Capability(BaseModel):
    """Availability of one external binary, as reported by ``doctor``."""

    name: str
    available: bool
    version: str | None = None
    path: Path | None = None
    install_hint: str = ""


class ErrorDetail(BaseModel):
    type: str
    message: str
    hint: str | None = None
    exit_code: int


class ErrorEnvelope(BaseModel):
    """The structured form of an error — the suite's only serialized error shape."""

    error: ErrorDetail


class RasterImage(BaseModel):
    """One rasterized page: where it was written and how big it came out.

    Deliberately free of page-numbering policy. Callers that care about labels,
    file naming, or 1-based document positions layer that on top — rp-core does
    not know what a page label is.
    """

    path: Path
    width: int
    height: int
