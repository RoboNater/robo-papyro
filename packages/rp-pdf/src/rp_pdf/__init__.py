"""rp-pdf — PDF extraction toolkit: JSON-first library and CLI."""

from rp_pdf.pages import PageSpecError, parse_page_labels, parse_pages

__version__ = "0.2.0"

__all__ = ["PageSpecError", "parse_page_labels", "parse_pages", "__version__"]
