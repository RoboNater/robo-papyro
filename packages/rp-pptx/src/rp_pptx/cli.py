"""Typer CLI wrapping rp_pptx. Parses args, calls the library, serializes output.

Conventions, all inherited from ``rp_core.clikit`` rather than restated here:

* **JSON to stdout by default**; ``--plain`` is the human opt-out. There is no
  ``--json`` flag anywhere in the suite (parent spec section 4.6).
* Errors are an ``ErrorEnvelope`` on **stderr**, with the exit code carried by
  the error class: 1 for input errors, 2 for a missing external binary, 3 for an
  unreadable or unsupported file.
* **Never overwrite an input file** without ``--in-place``. Every editing command
  insists on ``-o`` or ``--in-place`` and says so rather than guessing.

Options are options and arguments are arguments: ``--map``, ``--order``,
``--slides``, and ``--markdown`` are all flags in spec section 10, and a typer
parameter without a default silently becomes a positional argument instead — so
each one is spelled out with ``typer.Option`` rather than left to inference.

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
from rp_pptx import templates as templates_module
from rp_pptx.errors import RpPptxError
from rp_pptx.models import ConversionResult, RenderResult, WriteResult
from rp_pptx.pptx import read, slides, write
from rp_pptx.pptx import template as template_module

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="rp-pptx — PowerPoint toolkit (JSON-first library and CLI).",
)
slides_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Delete and reorder slides."
)
templates_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Inspect and build house templates."
)
app.add_typer(slides_app, name="slides")
app.add_typer(templates_app, name="templates")

# On Windows, redirected output defaults to the legacy code page, which cannot
# encode arbitrary slide text. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


#: Canonical subcommand names, held to spec section 10 by tests/test_invariants.py
#: in both directions: a command in the code but not here is an untested
#: addition, and one here but not in the code is a documented command that does
#: not exist.
COMMAND_NAMES = frozenset(
    {
        "append",
        "charts",
        "comments",
        "convert",
        "create",
        "doctor",
        "images",
        "index",
        "markdown",
        "notes",
        "props",
        "render",
        "replace",
        "set-notes",
        "slides",
        "tables",
        "template",
        "templates",
        "text",
    }
)
SLIDES_COMMAND_NAMES = frozenset({"delete", "reorder"})
TEMPLATES_COMMAND_NAMES = frozenset({"inspect", "layoutmap", "list", "manifest", "synthesize"})


FileArg = Annotated[Path, typer.Argument(help="The .pptx or .potx file")]
OutFileOpt = Annotated[Path | None, typer.Option("--out", "-o", help="Write here")]
InPlaceOpt = Annotated[bool, typer.Option("--in-place", help="Overwrite the input file")]
SlidesOpt = Annotated[str, typer.Option("--slides", help="Slides: 'all', '5', '3-7', '1,3-5,9'")]


def _errors():
    return clikit.error_handler()


def _job(title: str, entries: clikit.JobEntries, describe: bool | None, progress: bool | None):
    """Describe and report on a job, on stderr, when a human is watching.

    Only ``convert`` and ``render`` take these options: they are the two commands
    that shell out to LibreOffice and poppler, where a run takes long enough for
    silence to be ambiguous. Everything else here is in-process and finishes
    before a progress line would repaint once.
    """
    return clikit.job(
        title,
        entries,
        describe=clikit.display_enabled(describe),
        progress=clikit.display_enabled(progress),
    )


def _destination(file: Path, out: Path | None, in_place: bool) -> Path:
    """Where an editing command writes, or a refusal to guess (section 10)."""
    if out is not None and in_place:
        raise RpPptxError("Pass either --out or --in-place, not both.")
    if in_place:
        return file
    if out is None:
        raise RpPptxError(
            "Refusing to guess an output path: pass --out to write a copy, "
            "or --in-place to overwrite the input."
        )
    return out


def _json_argument(value: str, *, what: str) -> dict:
    """A JSON mapping given either as a path or inline (section 10)."""
    candidate = Path(value)
    try:
        text = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    except OSError as exc:
        raise RpPptxError(f"Cannot read {what} from {value}: {exc}") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RpPptxError(f"{what} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RpPptxError(f"{what} must be a JSON object, not {type(parsed).__name__}.")
    return parsed


# --- reads -------------------------------------------------------------------


@app.command()
def index(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Overview of a deck: geometry, counts, layouts, titles, properties."""
    with _errors():
        clikit.emit(read.get_index(file), plain)


@app.command()
def text(
    file: FileArg,
    slides_spec: SlidesOpt = "all",
    runs: Annotated[bool, typer.Option("--runs", help="Include per-run formatting")] = False,
    plain: clikit.plain_option = False,
) -> None:
    """Paragraph text, slide by slide."""
    with _errors():
        clikit.emit(read.get_text(file, slides=slides_spec, runs=runs), plain)


@app.command()
def markdown(
    file: FileArg,
    out: OutFileOpt = None,
    slides_spec: SlidesOpt = "all",
    images_dir: Annotated[
        Path | None, typer.Option("--images-dir", help="Extract images here and link them")
    ] = None,
    notes: Annotated[bool, typer.Option("--notes/--no-notes", help="Include speaker notes")] = True,
) -> None:
    """The deck as markdown, in the dialect `create` reads back."""
    with _errors():
        value = read.get_markdown(file, slides=slides_spec, notes=notes, images_dir=images_dir)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(value, encoding="utf-8")
            clikit.emit(WriteResult(output=out))
        else:
            typer.echo(value)


class TableFormat(str, enum.Enum):
    json = "json"
    csv = "csv"
    md = "md"


@app.command()
def tables(
    file: FileArg,
    slides_spec: SlidesOpt = "all",
    table_index: Annotated[
        int | None, typer.Option("--index", help="Only this table, numbered across the deck")
    ] = None,
    fmt: Annotated[TableFormat, typer.Option("--format", help="Output format")] = TableFormat.json,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Directory for csv/md files")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Tables, with their merge spans."""
    with _errors():
        found = read.get_tables(file, slides=slides_spec, table_index=table_index)
        if fmt is TableFormat.json:
            clikit.emit(found, plain)
            return
        rendered = {
            table.index: _table_as_csv(table) if fmt is TableFormat.csv else _table_as_md(table)
            for table in found
        }
        if out is None:
            typer.echo("\n\n".join(rendered.values()))
            return
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for table_number, body in rendered.items():
            destination = out / f"table-{table_number}.{fmt.value}"
            destination.write_text(body, encoding="utf-8")
            written.append(WriteResult(output=destination))
        clikit.emit(written, plain)


def _table_as_csv(table) -> str:
    import io

    buffer = io.StringIO()
    csv.writer(buffer).writerows(table.data)
    return buffer.getvalue()


def _table_as_md(table) -> str:
    from rp_pptx.pptx.read import _as_markdown_rows

    return "\n".join(_as_markdown_rows(table))


@app.command()
def images(
    file: FileArg,
    slides_spec: SlidesOpt = "all",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Extract the image bytes here")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Embedded pictures, optionally extracted."""
    with _errors():
        clikit.emit(read.get_images(file, slides=slides_spec, output_dir=out), plain)


@app.command()
def notes(
    file: FileArg, slides_spec: SlidesOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Speaker notes."""
    with _errors():
        clikit.emit(read.get_notes(file, slides=slides_spec), plain)


@app.command()
def comments(
    file: FileArg,
    slides_spec: SlidesOpt = "all",
    author: Annotated[
        list[str] | None, typer.Option("--author", help="Only these authors; repeatable")
    ] = None,
    plain: clikit.plain_option = False,
) -> None:
    """Classic comments. Modern threaded comments are deferred (spec section 7)."""
    with _errors():
        found = read.get_comments(file, slides=slides_spec)
        if author:
            wanted = {name.casefold() for name in author}
            found = [comment for comment in found if comment.author.casefold() in wanted]
        clikit.emit(found, plain)


@app.command()
def charts(
    file: FileArg, slides_spec: SlidesOpt = "all", plain: clikit.plain_option = False
) -> None:
    """Charts, with categories and series where python-pptx can read them."""
    with _errors():
        clikit.emit(read.get_charts(file, slides=slides_spec), plain)


@app.command()
def props(file: FileArg, plain: clikit.plain_option = False) -> None:
    """Core document properties."""
    with _errors():
        clikit.emit(read.get_properties(file), plain)


# --- writes ------------------------------------------------------------------


class Aspect(str, enum.Enum):
    widescreen = "16:9"
    standard = "4:3"


@app.command()
def create(
    out: Annotated[Path, typer.Option("--out", "-o", help="The deck to write")],
    from_markdown: Annotated[
        Path | None, typer.Option("--from-markdown", help="Build the slides from this markdown")
    ] = None,
    template: Annotated[
        str | None, typer.Option("--template", help="House template name or path")
    ] = None,
    aspect: Annotated[
        Aspect, typer.Option("--aspect", help="Only used when no template is given")
    ] = Aspect.widescreen,
    plain: clikit.plain_option = False,
) -> None:
    """Create a deck, optionally from markdown."""
    with _errors():
        source = from_markdown.read_text(encoding="utf-8") if from_markdown else None
        written = write.create(out, markdown=source, template=template, aspect=aspect.value)
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def append(
    file: FileArg,
    markdown_file: Annotated[
        Path, typer.Option("--markdown", help="Markdown to append as new slides")
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Append slides from markdown. Never changes an existing slide."""
    with _errors():
        written = write.append_markdown(
            file,
            markdown_file.read_text(encoding="utf-8"),
            output=_destination(file, out, in_place),
        )
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def replace(
    file: FileArg,
    mapping: Annotated[
        str, typer.Option("--map", help='JSON object, or a path to one: {"old": "new"}')
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    ignore_case: Annotated[
        bool, typer.Option("--ignore-case", help="Match case-insensitively")
    ] = False,
    preserve_formatting: Annotated[
        bool,
        typer.Option(
            "--preserve-formatting/--no-preserve-formatting",
            help="Keep the receiving run's formatting",
        ),
    ] = True,
    plain: clikit.plain_option = False,
) -> None:
    """Replace text across slides, tables, groups, and notes."""
    with _errors():
        clikit.emit(
            write.replace_text(
                file,
                _json_argument(mapping, what="--map"),
                output=_destination(file, out, in_place),
                match_case=not ignore_case,
                preserve_formatting=preserve_formatting,
            ),
            plain,
        )


@app.command(name="set-notes")
def set_notes(
    file: FileArg,
    slide: Annotated[int, typer.Option("--slide", help="1-based slide number")],
    text_value: Annotated[str | None, typer.Option("--text", help="The notes text")] = None,
    from_file: Annotated[
        Path | None, typer.Option("--from", help="Read the notes text from this file")
    ] = None,
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Set one slide's speaker notes."""
    with _errors():
        if (text_value is None) == (from_file is None):
            raise RpPptxError("Pass exactly one of --text or --from.")
        body = text_value if text_value is not None else from_file.read_text(encoding="utf-8")
        written = write.set_notes(file, slide, body, output=_destination(file, out, in_place))
        clikit.emit(WriteResult(output=written), plain)


@app.command()
def template(
    template_name: Annotated[str, typer.Argument(help="Template name or path")],
    context: Annotated[str, typer.Option("--context", help="JSON object, or a path to one")],
    out: Annotated[Path, typer.Option("--out", "-o", help="The deck to write")],
    strict: Annotated[
        bool,
        typer.Option("--strict/--no-strict", help="Fail when a placeholder is unresolved"),
    ] = True,
    plain: clikit.plain_option = False,
) -> None:
    """Fill a template's {{ placeholders }} from a JSON context."""
    with _errors():
        clikit.emit(
            template_module.fill_template(
                template_name,
                _json_argument(context, what="--context"),
                out,
                strict=strict,
            ),
            plain,
        )


# --- slide operations --------------------------------------------------------


@slides_app.command("delete")
def slides_delete(
    file: FileArg,
    slides_spec: Annotated[str, typer.Option("--slides", help="Slides to delete")],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Delete slides. Refuses to empty the deck."""
    with _errors():
        clikit.emit(
            slides.delete_slides(file, slides_spec, output=_destination(file, out, in_place)),
            plain,
        )


@slides_app.command("reorder")
def slides_reorder(
    file: FileArg,
    order: Annotated[
        str, typer.Option("--order", help="A complete permutation, comma separated: 3,1,2")
    ],
    out: OutFileOpt = None,
    in_place: InPlaceOpt = False,
    plain: clikit.plain_option = False,
) -> None:
    """Reorder slides. The order must be a complete permutation."""
    with _errors():
        try:
            wanted = [int(part) for part in order.split(",") if part.strip()]
        except ValueError as exc:
            raise RpPptxError(f"--order must be comma-separated integers, got {order!r}") from exc
        clikit.emit(
            slides.reorder_slides(file, wanted, output=_destination(file, out, in_place)), plain
        )


# --- templates ---------------------------------------------------------------


@templates_app.command("list")
def templates_list(plain: clikit.plain_option = False) -> None:
    """Every template resolution can find."""
    with _errors():
        clikit.emit(templates_module.list_templates(), plain)


@templates_app.command("inspect")
def templates_inspect(
    name: Annotated[str, typer.Argument(help="Template name or path")],
    plain: clikit.plain_option = False,
) -> None:
    """A template's geometry, masters, layouts, and placeholders."""
    with _errors():
        resolved = templates_module.resolve_template(name)
        clikit.emit(templates_module.inspect_template(resolved), plain)


@templates_app.command("manifest")
def templates_manifest(
    file: FileArg, out: OutFileOpt = None, plain: clikit.plain_option = False
) -> None:
    """A redacted description of a template's shape, safe to commit."""
    with _errors():
        manifest = templates_module.build_manifest(file)
        if out is None:
            clikit.emit(manifest, plain)
            return
        clikit.emit(WriteResult(output=templates_module.write_manifest(manifest, out)), plain)


@templates_app.command("synthesize")
def templates_synthesize(
    manifest_file: Annotated[Path, typer.Argument(help="A .manifest.json")],
    out: Annotated[Path, typer.Option("--out", "-o", help="The .potx to write")],
    plain: clikit.plain_option = False,
) -> None:
    """Rebuild a structurally equivalent template from a manifest."""
    with _errors():
        manifest = templates_module.read_manifest(manifest_file)
        clikit.emit(WriteResult(output=templates_module.synthesize(manifest, out)), plain)


@templates_app.command("layoutmap")
def templates_layoutmap(
    file: FileArg, out: OutFileOpt = None, plain: clikit.plain_option = False
) -> None:
    """Scaffold a layout map by guessing from layout names.

    A convenience and never authoritative: check every role before using it. A
    role guessed wrong fails loudly at the point of use rather than silently
    picking the wrong layout, which is the only reason a guess is safe to offer.
    """
    with _errors():
        guessed = templates_module.scaffold_layoutmap(templates_module.resolve_template(str(file)))
        if out is None:
            clikit.emit(guessed, plain)
            print(
                "This is a best-effort guess from layout names, not an authoritative "
                "map. Check every role before relying on it.",
                file=sys.stderr,
            )
            return
        clikit.emit(WriteResult(output=templates_module.write_layoutmap(guessed, out)), plain)


# --- convert and render ------------------------------------------------------


class ConvertTarget(str, enum.Enum):
    pdf = "pdf"
    odp = "odp"
    html = "html"


@app.command()
def convert(
    file: FileArg,
    to: Annotated[ConvertTarget, typer.Option("--to", help="Target format")],
    out: OutFileOpt = None,
    plain: clikit.plain_option = False,
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
) -> None:
    """Convert a deck with LibreOffice. Needs soffice on PATH."""
    with _errors():
        destination = Path(out) if out is not None else file.with_suffix(f".{to.value}")
        if destination.resolve() == file.resolve():
            raise RpPptxError(f"Refusing to overwrite {file.name}: pass --out.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        entries = [("to", f"{to.value}, via LibreOffice"), ("output", str(destination))]
        with _job(
            f"rp-pptx convert — {file}", entries, show_description, show_progress
        ) as reporter:
            with reporter.step(f"Converting {file.name} to {to.value}"):
                produced = binaries.soffice_convert(file, to.value, destination.parent)
                if produced != destination:
                    produced.replace(destination)
        clikit.emit(ConversionResult(source=file, output=destination, format=to.value), plain)


@app.command()
def render(
    file: FileArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Directory for the slide images")],
    dpi: Annotated[int, typer.Option("--dpi", help="Render resolution")] = 150,
    slides_spec: Annotated[
        str | None, typer.Option("--slides", help="Slides: 'all', '5', '3-7', '1,3-5,9'")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", help="Image format: png or jpeg")] = "png",
    plain: clikit.plain_option = False,
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
) -> None:
    """Rasterize slides to images. Needs LibreOffice and poppler."""
    with _errors():
        entries = [
            ("slides", slides_spec or "all"),
            ("format", f"{fmt} at {dpi} dpi"),
            ("output", str(out)),
            ("via", "LibreOffice to PDF, then poppler to images"),
        ]
        with _job(f"rp-pptx render — {file}", entries, show_description, show_progress) as reporter:
            written = core_render.render_pages(
                file, out, dpi=dpi, pages=slides_spec, fmt=fmt, progress=reporter
            )
        clikit.emit(
            [RenderResult(page=number, path=path) for number, path in enumerate(written, start=1)],
            plain,
        )


# Capability report. rp-pptx needs LibreOffice to convert or render, and poppler
# to turn the converted PDF into images.
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


__all__ = [
    "COMMAND_NAMES",
    "SLIDES_COMMAND_NAMES",
    "TEMPLATES_COMMAND_NAMES",
    "app",
    "main",
]
