from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from rp_core import clikit
from rp_pptx import templates
from rp_pptx.errors import RpPptxError
from rp_pptx.pptx import read, write
from rp_pptx.pptx import slides as slide_ops

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="PowerPoint toolkit (JSON-first)."
)
slides_app = typer.Typer(no_args_is_help=True)
templates_app = typer.Typer(no_args_is_help=True)
app.add_typer(slides_app, name="slides")
app.add_typer(templates_app, name="templates")

COMMAND_NAMES = frozenset(
    {
        "index",
        "text",
        "markdown",
        "tables",
        "images",
        "notes",
        "charts",
        "comments",
        "props",
        "create",
        "append",
        "replace",
        "set-notes",
        "slides",
        "templates",
        "doctor",
    }
)


def _errors():
    return clikit.error_handler()


def _destination(file: Path, out: Path | None, in_place: bool) -> Path:
    if out and in_place:
        raise RpPptxError("Pass either --out or --in-place, not both")
    if in_place:
        return file
    if out is None:
        raise RpPptxError("Pass --out to write a copy, or --in-place to overwrite the input")
    return out


@app.command()
def index(file: Path, plain: clikit.plain_option = False):
    with _errors():
        clikit.emit(read.get_index(file), plain)


@app.command()
def text(file: Path, slides: str = "all", runs: bool = False, plain: clikit.plain_option = False):
    with _errors():
        clikit.emit(read.get_text(file, slides=slides, runs=runs), plain)


@app.command()
def markdown(
    file: Path,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    slides: str = "all",
    notes: bool = True,
):
    with _errors():
        value = read.get_markdown(file, slides=slides, notes=notes)
        out.write_text(value, encoding="utf-8") if out else typer.echo(value)


def _read_command(fn):
    def command(file: Path, slides: str = "all", plain: clikit.plain_option = False):
        with _errors():
            clikit.emit(fn(file, slides=slides), plain)

    return command


app.command("tables")(_read_command(read.get_tables))
app.command("images")(_read_command(read.get_images))
app.command("notes")(_read_command(read.get_notes))
app.command("comments")(_read_command(read.get_comments))
app.command("charts")(_read_command(read.get_charts))


@app.command()
def props(file: Path, plain: clikit.plain_option = False):
    with _errors():
        clikit.emit(read.get_properties(file), plain)


@app.command()
def create(
    out: Annotated[Path, typer.Option("--out", "-o")],
    from_markdown: Annotated[Path | None, typer.Option()] = None,
    template: str | None = None,
    aspect: str = "16:9",
):
    with _errors():
        md = from_markdown.read_text(encoding="utf-8") if from_markdown else None
        output = write.create(out, markdown=md, template=template, aspect=aspect)
        clikit.emit({"output": str(output)})


@app.command()
def append(
    file: Path,
    markdown: Path,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    in_place: bool = False,
):
    with _errors():
        output = write.append_markdown(
            file, markdown.read_text(), output=_destination(file, out, in_place)
        )
        clikit.emit({"output": str(output)})


@app.command()
def replace(
    file: Path,
    map: str,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    in_place: bool = False,
    ignore_case: bool = False,
):
    with _errors():
        candidate = Path(map)
        values = json.loads(candidate.read_text() if candidate.is_file() else map)
        clikit.emit(
            write.replace_text(
                file, values, output=_destination(file, out, in_place), match_case=not ignore_case
            )
        )


@slides_app.command("delete")
def delete(
    file: Path,
    slides: str,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    in_place: bool = False,
):
    with _errors():
        clikit.emit(slide_ops.delete_slides(file, slides, output=_destination(file, out, in_place)))


@slides_app.command("reorder")
def reorder(
    file: Path,
    order: str,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    in_place: bool = False,
):
    with _errors():
        clikit.emit(
            slide_ops.reorder_slides(
                file, [int(x) for x in order.split(",")], output=_destination(file, out, in_place)
            )
        )


@templates_app.command("list")
def template_list(plain: clikit.plain_option = False):
    with _errors():
        clikit.emit(templates.list_templates(), plain)


@templates_app.command()
def inspect(name: str, plain: clikit.plain_option = False):
    with _errors():
        clikit.emit(templates.inspect_template(templates.resolve_template(name)), plain)


@templates_app.command()
def manifest(file: Path, out: Annotated[Path | None, typer.Option("--out", "-o")] = None):
    with _errors():
        value = templates.build_manifest(file)
        if out:
            out.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        else:
            clikit.emit(value)


@app.command()
def doctor():
    clikit.emit([])
