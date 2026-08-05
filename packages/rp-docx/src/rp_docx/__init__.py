"""rp-docx — Word document toolkit for the robo-papyro suite.

A JSON-first library and CLI for reading, creating, and editing `.docx` files,
built so an agentic coding tool with no native document capability can operate
on them through a stable, scriptable interface.

```python
from rp_docx import get_index, get_text, create, fill_template

index = get_index(Path("report.docx"))          # pydantic model, not a dict
create(Path("out.docx"), markdown="# Title", template="memo")
```

Every public function returns a pydantic model (or a list of them) and takes
``pathlib.Path``s. Formatting and printing belong to the CLI; nothing in the
library prints, and nothing imports typer.

Errors come from ``rp_core.errors`` by way of :mod:`rp_docx.errors`, so their
exit codes and serialized shape match every other tool in the suite.
"""

from __future__ import annotations

from rp_docx.docx.read import (
    get_comments,
    get_images,
    get_index,
    get_markdown,
    get_properties,
    get_tables,
    get_text,
    get_tracked_changes,
)
from rp_docx.docx.template import fill_template, find_placeholders
from rp_docx.docx.write import (
    accept_changes,
    append_markdown,
    create,
    reject_changes,
    replace_text,
    set_properties,
)
from rp_docx.errors import (
    InvalidDocxError,
    MissingFileError,
    PlaceholderError,
    RpDocxError,
    TemplateError,
)
from rp_docx.models import (
    Comment,
    ConversionResult,
    CoreProperties,
    DocumentIndex,
    EmbeddedImage,
    FillResult,
    Heading,
    Paragraph,
    RenderResult,
    ReplaceResult,
    Run,
    StyleDef,
    StyleMap,
    Table,
    TemplateInfo,
    TemplateManifest,
    TrackedChange,
    WriteResult,
)
from rp_docx.templates import (
    build_manifest,
    inspect_template,
    list_templates,
    load_stylemap,
    resolve_template,
    scaffold_stylemap,
    synthesize,
)

__all__ = [
    "Comment",
    "ConversionResult",
    "CoreProperties",
    "DocumentIndex",
    "EmbeddedImage",
    "FillResult",
    "Heading",
    "InvalidDocxError",
    "MissingFileError",
    "Paragraph",
    "PlaceholderError",
    "RenderResult",
    "ReplaceResult",
    "RpDocxError",
    "Run",
    "StyleDef",
    "StyleMap",
    "Table",
    "TemplateError",
    "TemplateInfo",
    "TemplateManifest",
    "TrackedChange",
    "WriteResult",
    "accept_changes",
    "append_markdown",
    "build_manifest",
    "create",
    "fill_template",
    "find_placeholders",
    "get_comments",
    "get_images",
    "get_index",
    "get_markdown",
    "get_properties",
    "get_tables",
    "get_text",
    "get_tracked_changes",
    "inspect_template",
    "list_templates",
    "load_stylemap",
    "reject_changes",
    "replace_text",
    "resolve_template",
    "scaffold_stylemap",
    "set_properties",
    "synthesize",
]
