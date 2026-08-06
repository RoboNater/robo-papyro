"""rp-pptx — a JSON-first PowerPoint toolkit.

The public surface is re-exported here so ``from rp_pptx import get_index``
works without knowing which module it lives in. Everything returns a pydantic
model, takes and returns ``pathlib.Path``, and never prints.
"""

from rp_pptx.errors import (
    InvalidPptxError,
    MissingFileError,
    RpPptxError,
    UnsupportedFeatureError,
)
from rp_pptx.pptx.read import (
    get_charts,
    get_comments,
    get_images,
    get_index,
    get_markdown,
    get_notes,
    get_properties,
    get_tables,
    get_text,
)
from rp_pptx.pptx.slides import delete_slides, reorder_slides
from rp_pptx.pptx.template import fill_template
from rp_pptx.pptx.write import (
    append_markdown,
    create,
    replace_text,
    set_notes,
    set_properties,
)
from rp_pptx.templates import (
    build_manifest,
    inspect_template,
    list_templates,
    load_layoutmap,
    resolve_template,
    synthesize,
)

__version__ = "0.1.0"

__all__ = [
    "InvalidPptxError",
    "MissingFileError",
    "RpPptxError",
    "UnsupportedFeatureError",
    "__version__",
    "append_markdown",
    "build_manifest",
    "create",
    "delete_slides",
    "fill_template",
    "get_charts",
    "get_comments",
    "get_images",
    "get_index",
    "get_markdown",
    "get_notes",
    "get_properties",
    "get_tables",
    "get_text",
    "inspect_template",
    "list_templates",
    "load_layoutmap",
    "reorder_slides",
    "replace_text",
    "resolve_template",
    "set_notes",
    "set_properties",
    "synthesize",
]
