"""The rp-xlsx tool surface.

Same shape as :mod:`rp_mcp.pptx`: reads always, writes only with a write root,
and every write names a new output because there is no ``--in-place`` over MCP.

**``allow_lossy`` is exposed on every write tool that opens an existing
workbook**, unlike anywhere else in this package — an agent that cannot
override rp-xlsx section 6's fidelity guard will retry the same failing call
forever, and this is the tool's only way to opt in. ``xlsx_create`` and
``xlsx_fill_template`` never open one, so they have no flag, matching the
CLI's own ``create``/``template`` exemption. Every other write tool's
docstring says what the flag actually does: a workbook a write touches loses
every formula's cached value until a real spreadsheet application recomputes
it, which is true whether or not ``allow_lossy`` was needed for anything else
in that same file.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from rp_mcp.sandbox import Sandbox
from rp_mcp.tools import OutputArg, OutputDirArg, PathArg, guarded, sandboxed_template
from rp_xlsx import fidelity as fidelity_module
from rp_xlsx import templates as templates_module
from rp_xlsx.models import (
    Cell,
    CellComment,
    CellValue,
    ChartRef,
    CoreProperties,
    EmbeddedImage,
    ExcelTable,
    FidelityReport,
    FillResult,
    NamedRange,
    ReplaceResult,
    SheetData,
    SheetOpResult,
    SheetSpec,
    TemplateInfo,
    WorkbookIndex,
    WriteResult,
)
from rp_xlsx.xlsx import read, write
from rp_xlsx.xlsx import sheets as sheets_module
from rp_xlsx.xlsx import template as template_module

SheetsArg = Annotated[
    str,
    Field(description="Sheet position spec, 1-based: 'all', '2', '1-3', '2,4'."),
]

SheetNamesArg = Annotated[
    list[str] | None,
    Field(
        description="Sheet names to select instead of positions. A workbook can have a "
        "sheet literally named '2', which sheets='2' would not select — use this instead. "
        "Mutually exclusive with a non-default sheets value."
    ),
]

CellsArg = Annotated[
    str | None,
    Field(description="A1-notation range: 'A1:D20', 'B:B' (whole column), '3:3' (whole row)."),
]

AllowLossyArg = Annotated[
    bool,
    Field(
        description="Proceed even if this edit would drop parts openpyxl cannot model "
        "(threaded comments, pivot caches, slicers, form controls, custom XML). The "
        "workbook's formulas lose their cached values on any edit regardless — the file "
        "needs opening in Excel or LibreOffice to recompute them."
    ),
]

TemplateArg = Annotated[
    str | None,
    Field(
        description="Template to build on: a name from xlsx_list_templates, or a path to an "
        "'.xltx'/'.xltm'/'.xlsx' under an allowed root. Omit to start from a blank workbook — "
        "openpyxl has no bundled default to fall back to."
    ),
]

RequiredTemplateArg = Annotated[
    str,
    Field(
        description="Template to use: a name from xlsx_list_templates, or a path to an "
        "'.xltx'/'.xltm'/'.xlsx' under an allowed root."
    ),
]


def register(server: MCPServer, sandbox: Sandbox) -> None:
    """Add the `xlsx_*` tools to `server`, gating the write half on the sandbox."""

    @server.tool(name="xlsx_index")
    @guarded
    def xlsx_index(path: PathArg) -> WorkbookIndex:
        """Summarize a workbook: sheets, formulas, defined names, at-risk parts.

        The cheapest first call on an unfamiliar workbook. `at_risk` and
        `has_cached_values` come from the same fidelity scan `xlsx_fidelity`
        reports in full, and `get_index` never fails because of what it finds.
        """
        return read.get_index(sandbox.resolve_input(path))

    @server.tool(name="xlsx_data")
    @guarded
    def xlsx_data(
        path: PathArg,
        sheets: SheetsArg = "all",
        names: SheetNamesArg = None,
        cells: CellsArg = None,
        header: Annotated[bool, Field(description="Treat the first row as a header.")] = True,
        max_rows: Annotated[int | None, Field(description="Cap rows returned per sheet.")] = None,
        formulas_only: Annotated[
            bool, Field(description="Report formula text instead of cached values.")
        ] = False,
    ) -> list[SheetData]:
        """Sheet data as a grid of values — never display strings.

        A cell showing '25.00%' reports 0.25; use `xlsx_cells` for the
        `number_format` needed to reproduce the display string.
        """
        return read.get_data(
            sandbox.resolve_input(path),
            sheets=sheets,
            names=names,
            cells=cells,
            header=header,
            max_rows=max_rows,
            values="formulas" if formulas_only else "cached",
        )

    @server.tool(name="xlsx_cells")
    @guarded
    def xlsx_cells(
        path: PathArg,
        sheets: SheetsArg = "all",
        names: SheetNamesArg = None,
        cells: CellsArg = None,
        empty: Annotated[
            bool, Field(description="Include cells with no value and no formula.")
        ] = False,
    ) -> list[Cell]:
        """Every selected cell, with both its formula and its cached value.

        `value_available` is false for a formula with no cached value —
        common on an openpyxl-authored file, which has never been through a
        calculating application.
        """
        return read.get_cells(
            sandbox.resolve_input(path), sheets=sheets, names=names, cells=cells, empty=empty
        )

    @server.tool(name="xlsx_formulas")
    @guarded
    def xlsx_formulas(path: PathArg, sheets: SheetsArg = "all") -> list[Cell]:
        """Only the formula cells, across the selected sheets."""
        return read.get_formulas(sandbox.resolve_input(path), sheets=sheets)

    @server.tool(name="xlsx_tables")
    @guarded
    def xlsx_tables(path: PathArg, sheets: SheetsArg = "all") -> list[ExcelTable]:
        """Excel table objects (ListObjects) — not Markdown or docx tables."""
        return read.get_tables(sandbox.resolve_input(path), sheets=sheets)

    @server.tool(name="xlsx_names")
    @guarded
    def xlsx_names(path: PathArg) -> list[NamedRange]:
        """Defined names, workbook- and sheet-scoped."""
        return read.get_names(sandbox.resolve_input(path))

    @server.tool(name="xlsx_comments")
    @guarded
    def xlsx_comments(path: PathArg, sheets: SheetsArg = "all") -> list[CellComment]:
        """Classic per-cell comments.

        Threaded comments are read nowhere: openpyxl reads only classic
        comments. `xlsx_fidelity` reports whether a workbook carries them.
        """
        return read.get_comments(sandbox.resolve_input(path), sheets=sheets)

    @server.tool(name="xlsx_images")
    @guarded
    def xlsx_images(
        path: PathArg, sheets: SheetsArg = "all", output_dir: OutputDirArg = None
    ) -> list[EmbeddedImage]:
        """List the images in a workbook: sheet, size, type, and anchor cell.

        With no `output_dir` this reports metadata and writes nothing. With
        one, each image is written there — that needs a write root.
        """
        target = sandbox.resolve_output_dir(output_dir) if output_dir else None
        return read.get_images(sandbox.resolve_input(path), sheets=sheets, output_dir=target)

    @server.tool(name="xlsx_charts")
    @guarded
    def xlsx_charts(path: PathArg, sheets: SheetsArg = "all") -> list[ChartRef]:
        """Read the charts: type, title, and series references.

        Values are never evaluated — `values_ref`/`categories_ref` are cell
        references, not the underlying numbers.
        """
        return read.get_charts(sandbox.resolve_input(path), sheets=sheets)

    @server.tool(name="xlsx_properties")
    @guarded
    def xlsx_properties(path: PathArg) -> CoreProperties:
        """Read the core workbook properties: title, author, dates, keywords."""
        return read.get_properties(sandbox.resolve_input(path))

    @server.tool(name="xlsx_markdown")
    @guarded
    def xlsx_markdown(
        path: PathArg,
        sheets: SheetsArg = "all",
        cells: CellsArg = None,
        max_rows: Annotated[int | None, Field(description="Cap rows per sheet.")] = 200,
    ) -> str:
        """Convert selected sheets to Markdown: a heading and a pipe table each."""
        return read.get_markdown(
            sandbox.resolve_input(path), sheets=sheets, cells=cells, max_rows=max_rows
        )

    @server.tool(name="xlsx_fidelity")
    @guarded
    def xlsx_fidelity(path: PathArg) -> FidelityReport:
        """What editing this workbook would cost, without editing it.

        openpyxl does not round-trip a workbook: every write silently drops a
        formula's cached value, and any part it does not model (threaded
        comments, pivot caches, slicers, form controls, custom XML). This
        reports both before any write tool is called, so an agent can decide
        whether `allow_lossy` is needed rather than discovering it from a
        failed call.
        """
        return fidelity_module.scan(sandbox.resolve_input(path))

    @server.tool(name="xlsx_list_templates")
    @guarded
    def xlsx_list_templates() -> list[TemplateInfo]:
        """List the house templates this installation can resolve by name."""
        return templates_module.list_templates()

    if not sandbox.writable:
        return

    @server.tool(name="xlsx_create")
    @guarded
    def xlsx_create(
        output: OutputArg,
        sheets: Annotated[
            list[dict] | None,
            Field(
                description="Sheets to write: [{'name', 'header'?, 'rows', "
                "'column_widths'?, 'freeze_header'?}, ...]. Omit for a blank workbook."
            ),
        ] = None,
        template_name: TemplateArg = None,
        header_style: Annotated[
            bool, Field(description="Bold the header row and freeze it.")
        ] = True,
    ) -> WriteResult:
        """Create a workbook, optionally starting from a template's shell.

        A resolved template's own sheets, styles, and defined names are kept;
        each entry in `sheets` becomes a freshly written sheet, replacing any
        template sheet of the same name outright.
        """
        specs = [SheetSpec.model_validate(item) for item in sheets] if sheets else None
        written = write.create(
            sandbox.resolve_output(output),
            sheets=specs,
            template=sandboxed_template(sandbox, template_name),
            header_style=header_style,
        )
        return WriteResult(
            output=written, cells_written=0, recalculation_required=False, dropped=[]
        )

    @server.tool(name="xlsx_set_cells")
    @guarded
    def xlsx_set_cells(
        path: PathArg,
        updates: Annotated[
            dict[str, dict[str, CellValue]],
            Field(description='Sheet name -> cell ref -> value: {"Sheet1": {"B2": 5}}.'),
        ],
        output: OutputArg,
        allow_lossy: AllowLossyArg = False,
    ) -> WriteResult:
        """Set specific cells. A value beginning with "=" is always a formula."""
        return write.set_cells(
            sandbox.resolve_input(path),
            updates,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_append_rows")
    @guarded
    def xlsx_append_rows(
        path: PathArg,
        sheet: Annotated[str, Field(description="Sheet to append to.")],
        rows: Annotated[list[list[CellValue]], Field(description="Rows to append.")],
        output: OutputArg,
        allow_lossy: AllowLossyArg = False,
    ) -> WriteResult:
        """Append rows after a sheet's last used row (never after a phantom dimension)."""
        return write.append_rows(
            sandbox.resolve_input(path),
            sheet,
            rows,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_replace_text")
    @guarded
    def xlsx_replace_text(
        path: PathArg,
        replacements: Annotated[
            dict[str, str],
            Field(description="Map of literal text to find to the text to put in its place."),
        ],
        output: OutputArg,
        sheets: SheetsArg = "all",
        match_case: bool = True,
        include_formulas: Annotated[
            bool, Field(description="Also rewrite text inside formulas.")
        ] = False,
        allow_lossy: AllowLossyArg = False,
    ) -> ReplaceResult:
        """Replace text in cell values and header/footer text.

        Skips formulas by default — a replacement landing inside
        '=SUM(Revenue!A1:A9)' would otherwise break it or silently repoint it.
        """
        return write.replace_text(
            sandbox.resolve_input(path),
            replacements,
            output=sandbox.resolve_output(output),
            sheets=sheets,
            match_case=match_case,
            include_formulas=include_formulas,
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_set_properties")
    @guarded
    def xlsx_set_properties(
        path: PathArg,
        properties: CoreProperties,
        output: OutputArg,
        allow_lossy: AllowLossyArg = False,
    ) -> WriteResult:
        """Set core workbook properties, writing a new file.

        Only the fields given are changed; the rest keep their current values.
        """
        target = write.set_properties(
            sandbox.resolve_input(path),
            properties,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )
        return WriteResult(output=target, cells_written=0, recalculation_required=False, dropped=[])

    @server.tool(name="xlsx_fill_template")
    @guarded
    def xlsx_fill_template(
        template_name: RequiredTemplateArg,
        context: Annotated[
            dict,
            Field(description="Nested placeholder values: {'client': {'name': 'Acme'}}."),
        ],
        output: OutputArg,
        strict: Annotated[
            bool, Field(description="Fail when a placeholder in the template has no value.")
        ] = True,
    ) -> FillResult:
        """Fill a `{{ placeholder }}` workbook template and write the result."""
        return template_module.fill_template(
            sandboxed_template(sandbox, template_name),
            context,
            sandbox.resolve_output(output),
            strict=strict,
        )

    @server.tool(name="xlsx_add_sheet")
    @guarded
    def xlsx_add_sheet(
        path: PathArg,
        name: Annotated[str, Field(description="New sheet name.")],
        output: OutputArg,
        index: Annotated[
            int | None, Field(description="1-based insert position. Omit to append.")
        ] = None,
        allow_lossy: AllowLossyArg = False,
    ) -> SheetOpResult:
        """Add a sheet, writing a new file."""
        return sheets_module.add_sheet(
            sandbox.resolve_input(path),
            name,
            index=index,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_delete_sheets")
    @guarded
    def xlsx_delete_sheets(
        path: PathArg,
        output: OutputArg,
        sheets: Annotated[
            str, Field(description="Sheets to delete, by position. Use `names` instead by name.")
        ] = "",
        names: SheetNamesArg = None,
        allow_lossy: AllowLossyArg = False,
    ) -> SheetOpResult:
        """Delete sheets, writing a new file. Refuses to leave no visible sheet."""
        return sheets_module.delete_sheets(
            sandbox.resolve_input(path),
            sheets,
            names,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_rename_sheet")
    @guarded
    def xlsx_rename_sheet(
        path: PathArg,
        old: Annotated[str, Field(description="Current sheet name.")],
        new: Annotated[str, Field(description="New sheet name.")],
        output: OutputArg,
        allow_lossy: AllowLossyArg = False,
    ) -> SheetOpResult:
        """Rename a sheet, writing a new file."""
        return sheets_module.rename_sheet(
            sandbox.resolve_input(path),
            old,
            new,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )

    @server.tool(name="xlsx_reorder_sheets")
    @guarded
    def xlsx_reorder_sheets(
        path: PathArg,
        order: Annotated[
            list[int],
            Field(
                description="Every sheet's 1-based number, in the order wanted. "
                "Must be a permutation of 1..sheet_count."
            ),
        ],
        output: OutputArg,
        allow_lossy: AllowLossyArg = False,
    ) -> SheetOpResult:
        """Reorder sheets, writing a new file."""
        return sheets_module.reorder_sheets(
            sandbox.resolve_input(path),
            order,
            output=sandbox.resolve_output(output),
            allow_lossy=allow_lossy,
        )


__all__ = ["register"]
