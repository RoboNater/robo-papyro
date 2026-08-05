"""Typer CLI wrapping rp_docx. Parses args, calls the library, serializes output.

Conventions, all inherited from ``rp_core.clikit`` rather than restated here:

* **JSON to stdout by default**; ``--plain`` is the human opt-out. There is no
  ``--json`` flag anywhere in the suite (parent spec section 4.6).
* Errors are an ``ErrorEnvelope`` on **stderr**, written after the
  human-readable message, with the exit code carried by the error class: 1 for
  input errors, 2 for a missing external binary, 3 for an unreadable file.
* **Never overwrite an input file** without ``--in-place``. Every editing
  command therefore insists on ``-o`` or ``--in-place``, and says so rather than
  guessing which was meant.

Rendering and conversion are thin re-exports of ``rp_core`` — no rendering
implementation lives in this package (spec section 4).
"""

from __future__ import annotations

import csv
import enum
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from rp_core import binaries, clikit
from rp_core import render as core_render
from rp_docx import templates as templates_module
from rp_docx.docx import read, write
from rp_docx.docx import template as template_module
from rp_docx.errors import RpDocxError
from rp_docx.models import ConversionResult, RenderResult, WriteResult

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rp-docx — Word document toolkit (JSON-first library and CLI).",
)
templates_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Inspect and build house templates."
)
app.add_typer(templates_app, name="templates")

# On Windows, redirected output defaults to the legacy code page, which cannot
# encode arbitrary document text. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


#: Canonical subcommand names. rp-docx does no argv preprocessing, so unlike
#: rp-pdf nothing dispatches on this set — it exists so the invariant test in
#: tests/test_invariants.py can hold the CLI to the surface spec section 10
#: specifies, in both directions.
COMMAND_NAMES = frozenset(
    {
        "accept",
        "append",
        "changes",
        "comments",
        "convert",
        "create",
        "doctor",
        "images",
        "index",
        "markdown",
        "props",
        "reject",
        "render",
        "replace",
        "tables",
        "template",
        "templates",
        "text",
    }
)

TEMPLATES_COMMAND_NAMES = frozenset({"inspect", "list", "manifest", "stylemap", "synthesize"})

FileArg = Annotated[Path, typer.Argument(help="Path to the .docx or .dotx file")]
AuthorOpt = Annotated[
    list[str] | None,
    typer.Option("--author", help="Limit to these authors; repeat for several"),
]
OutFileOpt = Annotated[
    Path | None, typer.Option("--out", "-o", help="Write the result to this file")
]
InPlaceOpt = Annotated[
    bool,
    typer.Option("--in-place", help="Edit the input file itself instead of writing a copy"),
]
TemplateOpt = Annotated[
    str | None,
    typer.Option("--template", help="Template name or path (default: $RP_DOCX_TEMPLATE)"),
]


class ConvertTarget(str, enum.Enum):
    pdf = "pdf"
    odt = "odt"
    html = "html"


class TableFormat(str, enum.Enum):
    json = "json"
    csv = "csv"
    md = "md"


class PageSize(str, enum.Enum):
    letter = "letter"
    a4 = "a4"


def _errors():
    """The suite's error contract: an ErrorEnvelope on stderr, exit code from
    the error class. Every rp-docx error subclasses that hierarchy, so nothing
    extra needs listing here."""
    return clikit.error_handler()


def _load_json(value: str, what: str) -> dict:
    """A JSON mapping given either as a file path or inline.

    Both spellings are accepted because both are natural: a person types a
    filename, and a script that already holds the mapping should not have to
    write it to disk first.
    """
    candidate = Path(value)
    try:
        text = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    except OSError as exc:
        raise RpDocxError(f"Could not read {what} from {value}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RpDocxError(
            f"{what} is not valid JSON ({exc}). Pass a path to a JSON file, or the JSON itself."
        ) from exc
    if not isinstance(data, dict):
        raise RpDocxError(f"{what} must be a JSON object, got {type(data).__name__}.")
    return data


def _destination(source: Path, out: Path | None, in_place: bool) -> Path | None:
    """Where an editing command writes, or an error saying it cannot tell.

    Refusing rather than defaulting is deliberate: the two plausible defaults
    are "overwrite the input" and "invent a filename", and both are surprises
    that only show up after the fact.
    """
    if out is not None and in_place:
        raise RpDocxError("Pass either --out or --in-place, not both.")
    if in_place:
        return None
    if out is None:
        raise RpDocxError(
            f"Refusing to overwrite {source.name}: pass --out to write a copy, "
            "or --in-place to edit it."
        )
    return out


# --- reading ---------------------------------------------------------------


@app.command()
def index(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Document overview: counts, headings, styles used, and core properties."""
    with _errors():
        clikit.emit(read.get_index(file), plain)


@app.command()
def text(
    file: FileArg,
    style: Annotated[
        str | None, typer.Option("--style", help="Only paragraphs with this style name")
    ] = None,
    runs: Annotated[
        bool, typer.Option("--runs", help="Include each paragraph's runs and their formatting")
    ] = False,
    plain: clikit.plain_option = False,
) -> None:
    """Paragraphs with their styles; --runs adds per-run formatting."""
    with _errors():
        result = read.get_text(file, style_filter=style, runs_wanted=runs)
        if plain:
            for paragraph in result:
                print(f"{paragraph.index:>4}  [{paragraph.style}]  {paragraph.text}")
        else:
            clikit.emit(result)


@app.command()
def markdown(
    file: FileArg,
    out: OutFileOpt = None,
    embed_images: Annotated[
        bool,
        typer.Option("--embed-images", help="Inline images as data URIs instead of dropping them"),
    ] = False,
) -> None:
    """Convert a document to Markdown (via mammoth)."""
    with _errors():
        result = read.get_markdown(file, embed_images=embed_images)
        if out is None:
            print(result, end="" if result.endswith("\n") else "\n")
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result, encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)


@app.command()
def tables(
    file: FileArg,
    index_: Annotated[int | None, typer.Option("--index", help="Only this table (1-based)")] = None,
    fmt: Annotated[TableFormat, typer.Option("--format", help="Output shape")] = TableFormat.json,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Directory for --format csv; file for --format md"),
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Extract tables as JSON, one CSV per table, or Markdown pipe tables."""
    with _errors():
        result = read.get_tables(file, table_index=index_)
        if fmt is TableFormat.json:
            clikit.emit(result, plain)
            return
        if fmt is TableFormat.md:
            rendered = "\n\n".join(_as_pipe_table(table.data) for table in result)
            if out is None:
                print(rendered)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(rendered + "\n", encoding="utf-8")
                print(f"Wrote {out}", file=sys.stderr)
            return
        if out is None:
            raise RpDocxError("--format csv needs an output directory: pass --out DIR.")
        out.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for table in result:
            target = out / f"table_{table.index:02d}.csv"
            with open(target, "w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(table.data)
            written.append(str(target))
        clikit.emit({"written": written}, plain)


def _as_pipe_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [[*row, *([""] * (width - len(row)))] for row in rows]
    lines = ["| " + " | ".join(cell.replace("|", "\\|") for cell in padded[0]) + " |"]
    lines.append("|" + "|".join(["---"] * width) + "|")
    for row in padded[1:]:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


@app.command()
def images(
    file: FileArg,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Extract images here (metadata only if omitted)"),
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """List embedded images, and extract them when --out is given."""
    with _errors():
        clikit.emit(read.get_images(file, output_dir=out), plain)


@app.command()
def comments(file: FileArg, author: AuthorOpt = None, plain: clikit.plain_option = False) -> None:
    """Comments with their authors, anchors, and resolved state."""
    with _errors():
        result = read.get_comments(file)
        if author:
            result = [comment for comment in result if comment.author in author]
        clikit.emit(result, plain)


@app.command()
def changes(file: FileArg, author: AuthorOpt = None, plain: clikit.plain_option = False) -> None:
    """Tracked insertions, deletions, and formatting changes."""
    with _errors():
        result = read.get_tracked_changes(file)
        if author:
            result = [change for change in result if change.author in author]
        clikit.emit(result, plain)


@app.command()
def props(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Core document properties."""
    with _errors():
        clikit.emit(read.get_properties(file), plain)


# --- writing ---------------------------------------------------------------


@app.command()
def create(
    out: Annotated[Path, typer.Option("--out", "-o", help="Document to write")],
    from_markdown: Annotated[
        Path | None,
        typer.Option("--from-markdown", help="Markdown file to render into the document"),
    ] = None,
    template: TemplateOpt = None,
    title: Annotated[str | None, typer.Option("--title", help="Document title property")] = None,
    page_size: Annotated[
        PageSize, typer.Option("--page-size", help="Page size when no template is given")
    ] = PageSize.letter,
    plain: clikit.plain_option = False,
) -> None:
    """Create a document, optionally from Markdown, on a house template."""
    with _errors():
        body = None
        if from_markdown is not None:
            if not from_markdown.is_file():
                raise RpDocxError(f"No such markdown file: {from_markdown}")
            body = from_markdown.read_text(encoding="utf-8")
        if template is not None and page_size is not PageSize.letter:
            print(
                "A template was given, so --page-size is ignored: the template's "
                "page setup wins (spec section 9).",
                file=sys.stderr,
            )
        written = write.create(
            out, markdown=body, template=template, title=title, page_size=page_size.value
        )
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def append(
    file: FileArg,
    markdown_file: Annotated[Path, typer.Option("--markdown", help="Markdown file to append")],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Append Markdown to an existing document, using its own styles."""
    with _errors():
        destination = _destination(file, out, in_place)
        if not markdown_file.is_file():
            raise RpDocxError(f"No such markdown file: {markdown_file}")
        written = write.append_markdown(
            file, markdown_file.read_text(encoding="utf-8"), output=destination
        )
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def replace(
    file: FileArg,
    mapping: Annotated[
        str,
        typer.Option("--map", help="JSON object of replacements, as a file path or inline JSON"),
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    preserve_formatting: Annotated[
        bool,
        typer.Option(
            "--preserve-formatting/--no-preserve-formatting",
            help="Keep the formatting of the run each match starts in",
        ),
    ] = True,
    ignore_case: Annotated[
        bool, typer.Option("--ignore-case", help="Match without regard to case")
    ] = False,
    plain: clikit.plain_option = False,
) -> None:
    """Replace text everywhere it appears — body, tables, headers, footers, notes."""
    with _errors():
        destination = _destination(file, out, in_place)
        replacements = {str(key): str(value) for key, value in _load_json(mapping, "--map").items()}
        result = write.replace_text(
            file,
            replacements,
            output=destination,
            match_case=not ignore_case,
            preserve_formatting=preserve_formatting,
        )
        clikit.emit(result, plain)


@app.command()
def template(
    template_name: Annotated[str, typer.Argument(help="Template name or path")],
    context: Annotated[
        str,
        typer.Option("--context", help="JSON object of values, as a file path or inline JSON"),
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Document to write")],
    strict: Annotated[
        bool,
        typer.Option(
            "--strict/--no-strict",
            help="Fail on placeholders the context does not supply, rather than leaving them",
        ),
    ] = True,
    plain: clikit.plain_option = False,
) -> None:
    """Fill a template's {{ placeholders }} from a JSON context."""
    with _errors():
        result = template_module.fill_template(
            template_name, _load_json(context, "--context"), out, strict=strict
        )
        clikit.emit(result, plain)


@app.command()
def accept(
    file: FileArg,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    author: AuthorOpt = None,
    plain: clikit.plain_option = False,
) -> None:
    """Accept tracked changes: keep insertions, discard deletions."""
    with _errors():
        destination = _destination(file, out, in_place)
        written = write.accept_changes(file, output=destination, authors=author or None)
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def reject(
    file: FileArg,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    author: AuthorOpt = None,
    plain: clikit.plain_option = False,
) -> None:
    """Reject tracked changes: discard insertions, restore deletions."""
    with _errors():
        destination = _destination(file, out, in_place)
        written = write.reject_changes(file, output=destination, authors=author or None)
        clikit.emit(WriteResult(output=written), plain)


# --- templates -------------------------------------------------------------


@templates_app.command("list")
def templates_list(plain: clikit.plain_option = False) -> None:
    """Templates resolvable by bare name, and where they were found."""
    with _errors():
        found = templates_module.list_templates()
        if not found:
            searched = ", ".join(str(d) for d in templates_module.template_dirs())
            print(
                f"No templates found. Searched: {searched or 'no template directories'}. "
                f"Set {templates_module.TEMPLATE_DIR_ENV} to point at one.",
                file=sys.stderr,
            )
        clikit.emit(found, plain)


@templates_app.command("inspect")
def templates_inspect(
    name: Annotated[str, typer.Argument(help="Template name or path")],
    plain: clikit.plain_option = False,
) -> None:
    """A template's styles, page size, and whether it carries a letterhead."""
    with _errors():
        resolved = templates_module.resolve_template(name)
        clikit.emit(templates_module.inspect_template(resolved), plain)


@templates_app.command("manifest")
def templates_manifest(
    file: Annotated[Path, typer.Argument(help="Template file to describe")],
    out: OutFileOpt = None,
    plain: clikit.plain_option = False,
) -> None:
    """Describe a template's shape as JSON, carrying none of its content.

    Safe to commit and to share: a manifest holds style names, page geometry,
    and presence flags, and never document text or image bytes (spec section 5.2).
    """
    with _errors():
        manifest = templates_module.build_manifest(file)
        if out is None:
            clikit.emit(manifest, plain)
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)


@templates_app.command("synthesize")
def templates_synthesize(
    manifest: Annotated[Path, typer.Argument(help="Manifest JSON to rebuild from")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Template to write")],
    plain: clikit.plain_option = False,
) -> None:
    """Rebuild a structurally equivalent template from a manifest."""
    with _errors():
        written = templates_module.synthesize(templates_module.load_manifest(manifest), out)
        clikit.emit(WriteResult(output=written), plain)


@templates_app.command("stylemap")
def templates_stylemap(
    file: Annotated[Path, typer.Argument(help="Template to scaffold a stylemap for")],
    out: OutFileOpt = None,
    plain: clikit.plain_option = False,
) -> None:
    """Scaffold a best-effort stylemap for a human to correct.

    Matches style names against common patterns. **Never authoritative** — a
    generated stylemap that happens to be wrong is worse than none, because it
    looks reviewed.
    """
    with _errors():
        scaffold = templates_module.scaffold_stylemap(file)
        print(
            "This stylemap is a guess from style names, not a reading of the "
            "template's intent. Review every role before using it.",
            file=sys.stderr,
        )
        if out is None:
            clikit.emit(scaffold, plain)
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(scaffold.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)


# --- convert and render ----------------------------------------------------


@app.command()
def convert(
    file: FileArg,
    to: Annotated[ConvertTarget, typer.Option("--to", help="Target format")],
    out: OutFileOpt = None,
    plain: clikit.plain_option = False,
) -> None:
    """Convert a document with LibreOffice. Needs soffice on PATH."""
    with _errors():
        destination = Path(out) if out is not None else file.with_suffix(f".{to.value}")
        if destination.resolve() == file.resolve():
            raise RpDocxError(f"Refusing to overwrite {file.name}: pass --out.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        produced = binaries.soffice_convert(file, to.value, destination.parent)
        if produced != destination:
            produced.replace(destination)
        clikit.emit(ConversionResult(source=file, output=destination, format=to.value), plain)


@app.command()
def render(
    file: FileArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory for the page images")],
    dpi: Annotated[int, typer.Option("--dpi", help="Render resolution")] = 150,
    pages: Annotated[
        str | None, typer.Option("--pages", help="Pages: 'all', '5', '3-7', '1,3-5,9'")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", help="Image format: png or jpeg")] = "png",
    plain: clikit.plain_option = False,
) -> None:
    """Rasterize pages to images. Needs LibreOffice and poppler."""
    with _errors():
        written = core_render.render_pages(file, out, dpi=dpi, pages=pages, fmt=fmt)
        clikit.emit(
            [RenderResult(page=number, path=path) for number, path in enumerate(written, start=1)],
            plain,
        )


# Capability report. rp-docx needs LibreOffice to convert or render, and
# poppler to turn the converted PDF into images.
app.command("doctor")(clikit.doctor_command("soffice", "pdftoppm", "pdfinfo"))


def _registered(target: typer.Typer) -> set[str]:
    """Command names registered on ``target`` — used by the invariant test."""
    import typer.main

    names: set[str] = set()
    for command in target.registered_commands:
        names.add(command.name or typer.main.get_command_name(command.callback.__name__))
    for group in target.registered_groups:
        if group.name:
            names.add(group.name)
    return names


def main() -> None:
    """Console-script entry point."""
    app()


__all__ = ["COMMAND_NAMES", "TEMPLATES_COMMAND_NAMES", "app", "main"]


if __name__ == "__main__":
    main()
