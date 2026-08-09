"""rp-xlsx — a JSON-first spreadsheet toolkit.

The public surface is re-exported here so ``from rp_xlsx import get_index``
works without knowing which module it lives in. Everything returns a pydantic
model, takes and returns ``pathlib.Path``, and never prints.

Built out incrementally through Phase 3 (see ``docs/specs/rp-xlsx-spec.md``
section 12); this module's exports grow with each step.
"""

from rp_xlsx.errors import (
    InvalidXlsxError,
    LossyEditError,
    MissingFileError,
    RpXlsxError,
)

__version__ = "0.1.0"

__all__ = [
    "InvalidXlsxError",
    "LossyEditError",
    "MissingFileError",
    "RpXlsxError",
    "__version__",
]
