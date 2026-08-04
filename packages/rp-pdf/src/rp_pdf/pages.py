"""Page-spec parsing — re-exported from ``rp_core.pages``.

The implementation moved to ``rp-core`` so every package in the suite parses
page specs identically. This module exists only so ``rp_pdf.pages`` keeps
working as an import path; do not add logic here.
"""

from __future__ import annotations

from rp_core.pages import (
    PageSpec,
    PageSpecError,
    parse_page_labels,
    parse_pages,
)

__all__ = ["PageSpec", "PageSpecError", "parse_page_labels", "parse_pages"]
