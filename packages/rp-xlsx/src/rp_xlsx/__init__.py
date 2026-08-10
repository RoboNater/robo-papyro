"""rp-xlsx — a JSON-first spreadsheet toolkit.

The public surface is re-exported here so ``from rp_xlsx import get_index``
works without knowing which module it lives in. Everything returns a pydantic
model, takes and returns ``pathlib.Path``, and never prints.
"""

from rp_xlsx.errors import (
    InvalidXlsxError,
    LossyEditError,
    MissingFileError,
    RefSpecError,
    RpXlsxError,
    TemplateError,
)
from rp_xlsx.fidelity import scan as fidelity_scan
from rp_xlsx.templates import (
    build_manifest,
    inspect_template,
    list_templates,
    resolve_template,
    synthesize,
)
from rp_xlsx.xlsx.read import (
    get_cells,
    get_charts,
    get_comments,
    get_data,
    get_formulas,
    get_images,
    get_index,
    get_markdown,
    get_names,
    get_properties,
    get_tables,
)
from rp_xlsx.xlsx.sheets import add_sheet, delete_sheets, rename_sheet, reorder_sheets
from rp_xlsx.xlsx.tabular import from_csv, from_json, from_markdown, to_csv
from rp_xlsx.xlsx.template import fill_template
from rp_xlsx.xlsx.write import append_rows, create, replace_text, set_cells, set_properties

__version__ = "0.1.0"

__all__ = [
    "InvalidXlsxError",
    "LossyEditError",
    "MissingFileError",
    "RefSpecError",
    "RpXlsxError",
    "TemplateError",
    "__version__",
    "add_sheet",
    "append_rows",
    "build_manifest",
    "create",
    "delete_sheets",
    "fidelity_scan",
    "fill_template",
    "from_csv",
    "from_json",
    "from_markdown",
    "get_cells",
    "get_charts",
    "get_comments",
    "get_data",
    "get_formulas",
    "get_images",
    "get_index",
    "get_markdown",
    "get_names",
    "get_properties",
    "get_tables",
    "inspect_template",
    "list_templates",
    "rename_sheet",
    "reorder_sheets",
    "replace_text",
    "resolve_template",
    "set_cells",
    "set_properties",
    "synthesize",
    "to_csv",
]
