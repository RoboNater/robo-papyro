"""Typer CLI wrapping rp_pdf.core. Parses args, calls core, serializes output.

Conventions:
- JSON to stdout by default; --plain/--csv for human/file variants.
- Errors: an rp_core ErrorEnvelope plus a human-readable message, both on
  stderr, and the exit code carried by the error class (rp_core.errors): 1 for
  input errors, 2 for a missing external binary, 3 for an unreadable PDF.

Options resolve by precedence flag -> env var -> config file -> built-in
default (see rp_pdf.config). Boolean flags are paired (--x/--no-x) and default to
None so an omitted flag falls through to the config file instead of forcing
False; this is what lets, e.g., --no-ai turn off an AI pass the config enabled.
Running `rp-pdf FILE.pdf` with no subcommand runs the command named in the config
file's [default] section (or `index` if none), against FILE.
"""

from __future__ import annotations

import csv
import enum
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from rp_core import clikit
from rp_pdf import config, core
from rp_pdf import markdown as md

app = typer.Typer(no_args_is_help=True, add_completion=False)

# On Windows, redirected/piped output defaults to the legacy code page (e.g. cp1252),
# which cannot encode arbitrary extracted PDF text. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

FileArg = Annotated[Path, typer.Argument(help="Path to the PDF file")]
# Options default to None so an omitted flag falls through to env/config/default.
PagesOpt = Annotated[
    str | None, typer.Option("--pages", help="Pages: 'all', '5', '3-7', '1,3-5,9'")
]
PasswordOpt = Annotated[str | None, typer.Option("--password", help="Password for encrypted PDFs")]
PhysicalOpt = Annotated[
    bool | None,
    typer.Option(
        "--physical/--no-physical",
        help="Interpret --pages as physical positions (first page = 1), "
        "ignoring the PDF's page labels",
    ),
]


class TextEngine(str, enum.Enum):
    poppler = "poppler"
    pypdf = "pypdf"
    pdfplumber = "pdfplumber"


EngineOpt = Annotated[
    TextEngine | None,
    typer.Option(
        "--engine",
        help="Text extractor: poppler (default; correct word spacing, needs poppler "
        "installed), or pypdf/pdfplumber (in-process, faster, but may run words "
        "together on some PDFs)",
    ),
]
PopplerPathOpt = Annotated[
    Path | None,
    typer.Option("--poppler-path", help="Poppler bin directory if not on PATH"),
]
OrgOpt = Annotated[
    str | None,
    typer.Option(
        "--organization",
        help="VLM API organization ID (or set RP_PDF_VLM_ORG); OpenAI-hosted, "
        "org-scoped accounts only — leave unset for local/third-party servers",
    ),
]

# Canonical subcommand names, used to decide whether `rp-pdf X ...` names a command
# or a file for the default action.
COMMAND_NAMES = frozenset(
    {
        "index",
        "text",
        "tables",
        "search",
        "images",
        "markdown",
        "render",
        "validate-vlm-ocr",
        "doctor",
    }
)


def _resolve_engine(command: str, value: TextEngine | None) -> str:
    """Resolve --engine through config to a validated engine string."""
    resolved = config.resolve(
        command, "engine", value.value if value is not None else None, "poppler"
    )
    valid = {engine.value for engine in TextEngine}
    if resolved not in valid:
        raise core.RpPdfError(
            f"Invalid engine {resolved!r} in config; choose from {', '.join(sorted(valid))}."
        )
    return resolved


def _resolve_path(
    command: str,
    key: str,
    value: Path | None,
    default: Path | None = None,
    env: str | None = None,
) -> Path | None:
    """Resolve a path option, expanding ~ on values that come from the config."""
    resolved = config.resolve(command, key, value, default, env=env)
    if resolved is None:
        return None
    if isinstance(resolved, Path):
        return resolved
    return Path(str(resolved)).expanduser()


def _announce_labels(file: Path, pages: str, physical: bool, password: str | None) -> None:
    """Tell the user (on stderr) when --pages is interpreted via page labels."""
    if physical or pages.strip().lower() == "all":
        return
    if core.get_page_labels(file, password=password) is not None:
        print(
            "Interpreting --pages using the PDF's page labels; "
            "pass --physical for 1-based physical page numbers.",
            file=sys.stderr,
        )


def _errors():
    """The suite's error contract: an ErrorEnvelope on stderr, exit code from
    the error class (rp_core.errors). Every rp-pdf error subclasses that
    hierarchy, so nothing extra needs listing here."""
    return clikit.error_handler()


def _dump(result: BaseModel | list[BaseModel] | dict) -> None:
    clikit.dump_json(result)


@app.callback()
def _configure(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to an rp-pdf TOML config file (overrides discovery and $RP_PDF_CONFIG)",
        ),
    ] = None,
) -> None:
    """rp-pdf — PDF extraction toolkit (JSON-first library and CLI)."""
    with _errors():
        config.set_active(config.load(config_path))


@app.command()
def index(file: FileArg, password: PasswordOpt = None) -> None:
    """Document index (metadata, outline, page summaries) as JSON."""
    with _errors():
        _dump(core.get_index(file, password=password))


@app.command()
def text(
    file: FileArg,
    pages: PagesOpt = None,
    layout: Annotated[
        bool | None,
        typer.Option(
            "--layout/--no-layout",
            help="Layout-preserving extraction (columns, indentation)",
        ),
    ] = None,
    engine: EngineOpt = None,
    plain: Annotated[
        bool | None, typer.Option("--plain/--no-plain", help="Raw text instead of JSON")
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Extract text; JSON by default, --plain for raw text."""
    with _errors():
        cmd = "text"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        _announce_labels(file, pages_v, physical_v, password)
        result = core.get_text(
            file,
            pages_v,
            layout=config.resolve(cmd, "layout", layout, False),
            engine=_resolve_engine(cmd, engine),
            password=password,
            physical=physical_v,
            poppler_path=_resolve_path(cmd, "poppler_path", poppler_path),
        )
        if config.resolve(cmd, "plain", plain, False):
            print("\n\n".join(page.text for page in result))
        else:
            _dump(result)


@app.command()
def tables(
    file: FileArg,
    pages: PagesOpt = None,
    csv_dir: Annotated[
        Path | None, typer.Option("--csv", help="Write one CSV per table to this directory")
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
) -> None:
    """Extract tables as JSON, or one CSV file per table with --csv."""
    with _errors():
        cmd = "tables"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        _announce_labels(file, pages_v, physical_v, password)
        result = core.get_tables(file, pages_v, password=password, physical=physical_v)
        csv_target = _resolve_path(cmd, "csv", csv_dir)
        if csv_target is None:
            _dump(result)
            return
        csv_target.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for table in result:
            stem = core.page_stem(table.physical_page, table.labeled_page)
            target = csv_target / f"table_{stem}_{table.index:02d}.csv"
            with open(target, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in table.rows:
                    writer.writerow(["" if cell is None else cell for cell in row])
            written.append(str(target))
        _dump({"written": written})


@app.command()
def search(
    file: FileArg,
    query: Annotated[str, typer.Argument(help="Phrase (or regex with --regex) to search for")],
    pages: PagesOpt = None,
    regex: Annotated[
        bool | None,
        typer.Option("--regex/--no-regex", help="Treat QUERY as a regular expression"),
    ] = None,
    case_sensitive: Annotated[
        bool | None,
        typer.Option("--case-sensitive/--no-case-sensitive", help="Match case exactly"),
    ] = None,
    context: Annotated[
        int | None, typer.Option("--context", help="Context characters around each match")
    ] = None,
    max_hits: Annotated[int | None, typer.Option("--max", help="Maximum number of hits")] = None,
    engine: EngineOpt = None,
    plain: Annotated[
        bool | None,
        typer.Option("--plain/--no-plain", help="One human-readable line per hit instead of JSON"),
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Search page text; hits report both physical and labeled page numbers."""
    with _errors():
        cmd = "search"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        max_v = config.resolve(cmd, "max", max_hits, 100)
        _announce_labels(file, pages_v, physical_v, password)
        result = core.search(
            file,
            query,
            pages_v,
            regex=config.resolve(cmd, "regex", regex, False),
            ignore_case=not config.resolve(cmd, "case_sensitive", case_sensitive, False),
            context=config.resolve(cmd, "context", context, 80),
            max_hits=max_v,
            engine=_resolve_engine(cmd, engine),
            password=password,
            physical=physical_v,
            poppler_path=_resolve_path(cmd, "poppler_path", poppler_path),
        )
        if config.resolve(cmd, "plain", plain, False):
            for hit in result:
                if hit.labeled_page is not None:
                    where = f"page {hit.labeled_page} (pp {hit.physical_page})"
                else:
                    where = f"page {hit.physical_page}"
                print(f"{where}: …{hit.before}[{hit.match}]{hit.after}…")
        else:
            _dump(result)
        if len(result) >= max_v:
            print(
                f"Results capped at {max_v}; pass --max to raise the limit.",
                file=sys.stderr,
            )


@app.command()
def images(
    file: FileArg,
    pages: PagesOpt = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Save images to this directory (metadata only if omitted)"),
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
) -> None:
    """Extract embedded images."""
    with _errors():
        cmd = "images"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        _announce_labels(file, pages_v, physical_v, password)
        _dump(
            core.get_images(
                file,
                pages_v,
                out_dir=_resolve_path(cmd, "out", out),
                password=password,
                physical=physical_v,
            )
        )


@app.command()
def markdown(
    file: FileArg,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write Markdown to this file instead of stdout"),
    ] = None,
    pages: PagesOpt = None,
    images_dir: Annotated[
        Path | None,
        typer.Option(
            "--images-dir",
            help="Extract embedded images here and link them (best placed next to the "
            "output file; images are skipped entirely when omitted)",
        ),
    ] = None,
    ai: Annotated[
        bool | None,
        typer.Option(
            "--ai/--no-ai",
            help="Review each page's draft against its rendered image with a "
            "vision-language model (OpenAI-compatible API; needs poppler and "
            "the 'ai' optional dependencies)",
        ),
    ] = None,
    ocr: Annotated[
        bool | None,
        typer.Option(
            "--ocr/--no-ocr",
            help="Transcribe scanned (no text layer) pages using the VLM (requires --ai)",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="VLM model name (or set RP_PDF_VLM_MODEL)"),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="OpenAI-compatible endpoint, e.g. an OpenRouter/Ollama/vLLM URL "
            "(or set RP_PDF_VLM_BASE_URL); key from RP_PDF_VLM_API_KEY or OPENAI_API_KEY",
        ),
    ] = None,
    organization: OrgOpt = None,
    jobs: Annotated[
        int | None, typer.Option("--jobs", help="Concurrent VLM requests for the AI pass")
    ] = None,
    dpi: Annotated[
        int | None, typer.Option("--dpi", help="Render resolution for the AI pass page images")
    ] = None,
    engine: EngineOpt = None,
    outline_headings: Annotated[
        bool | None,
        typer.Option(
            "--outline-headings/--no-outline-headings",
            help="Promote outline (bookmark) titles found on their pages to Markdown "
            "headings, leveled by outline depth; no-op without an outline",
        ),
    ] = None,
    outline_context: Annotated[
        bool | None,
        typer.Option(
            "--outline-context/--no-outline-context",
            help="Tell the VLM each page's position in the document outline so heading "
            "levels match the document hierarchy (requires --ai)",
        ),
    ] = None,
    full: Annotated[
        bool | None,
        typer.Option(
            "--full/--no-full",
            help="Emit the whole MarkdownResult as JSON — per-page detail and "
            "warnings as well as the Markdown body — instead of the Markdown alone",
        ),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", help="AI response cache location (default ~/.cache/rp-pdf)"),
    ] = None,
    cache: Annotated[
        bool | None,
        typer.Option("--cache/--no-cache", help="Use the AI response cache (default on)"),
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Convert pages to Markdown: programmatic extraction, plus --ai review and optional --ocr."""
    with _errors():
        cmd = "markdown"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        out_v = _resolve_path(cmd, "out", out)
        _announce_labels(file, pages_v, physical_v, password)
        result = md.to_markdown(
            file,
            pages_v,
            images_dir=_resolve_path(cmd, "images_dir", images_dir),
            ai=config.resolve(cmd, "ai", ai, False),
            ocr=config.resolve(cmd, "ocr", ocr, False),
            model=config.resolve(cmd, "model", model, None, env="RP_PDF_VLM_MODEL"),
            base_url=config.resolve(cmd, "base_url", base_url, None, env="RP_PDF_VLM_BASE_URL"),
            organization=config.resolve(
                cmd, "organization", organization, None, env="RP_PDF_VLM_ORG"
            ),
            jobs=config.resolve(cmd, "jobs", jobs, 1),
            dpi=config.resolve(cmd, "dpi", dpi, 150),
            engine=_resolve_engine(cmd, engine),
            outline_headings=config.resolve(cmd, "outline_headings", outline_headings, False),
            outline_context=config.resolve(cmd, "outline_context", outline_context, False),
            password=password,
            physical=physical_v,
            poppler_path=_resolve_path(cmd, "poppler_path", poppler_path),
            cache_dir=_resolve_path(cmd, "cache_dir", cache_dir, env="RP_PDF_CACHE_DIR"),
            use_cache=config.resolve(cmd, "cache", cache, True),
        )
        for warning in result.warnings:
            print(warning, file=sys.stderr)
        if config.resolve(cmd, "full", full, False):
            _dump(result)
        elif out_v is not None:
            out_v.write_text(result.markdown, encoding="utf-8")
            print(f"Wrote {out_v}", file=sys.stderr)
        else:
            print(result.markdown, end="")


@app.command()
def render(
    file: FileArg,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory for rendered images"),
    ] = None,
    pages: PagesOpt = None,
    dpi: Annotated[int | None, typer.Option("--dpi", help="Render resolution")] = None,
    fmt: Annotated[str | None, typer.Option("--format", help="Image format: png or jpeg")] = None,
    password: PasswordOpt = None,
    poppler_path: PopplerPathOpt = None,
    physical: PhysicalOpt = None,
) -> None:
    """Rasterize pages to image files."""
    with _errors():
        cmd = "render"
        pages_v = config.resolve(cmd, "pages", pages, "all")
        physical_v = config.resolve(cmd, "physical", physical, False)
        out_v = _resolve_path(cmd, "out", out)
        if out_v is None:
            raise core.RpPdfError(
                "render needs an output directory: pass --out or set [render].out in the config."
            )
        _announce_labels(file, pages_v, physical_v, password)
        _dump(
            core.render_pages(
                file,
                pages_v,
                out_v,
                dpi=config.resolve(cmd, "dpi", dpi, 200),
                fmt=config.resolve(cmd, "format", fmt, "png"),
                password=password,
                poppler_path=_resolve_path(cmd, "poppler_path", poppler_path),
                physical=physical_v,
            )
        )


@app.command()
def validate_vlm_ocr(
    model: Annotated[
        str | None,
        typer.Option("--model", help="VLM model name (or set RP_PDF_VLM_MODEL)"),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="OpenAI-compatible endpoint URL (or set RP_PDF_VLM_BASE_URL); "
            "key from RP_PDF_VLM_API_KEY or OPENAI_API_KEY",
        ),
    ] = None,
    organization: OrgOpt = None,
    dpi: Annotated[
        int | None, typer.Option("--dpi", help="Render resolution for the OCR page images")
    ] = None,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Check your VLM OCR setup by transcribing a synthetic scanned PDF.

    Generates a three-page PDF (page 1 with a text layer, pages 2-3 image-only),
    runs the real OCR path against the configured model, and scores the
    transcriptions against the known text. Exits nonzero if OCR produced
    nothing; 'warn' statuses report low similarity but still exit zero.
    """
    with _errors():
        from rp_pdf import ocr

        cmd = "validate-vlm-ocr"
        result = ocr.validate_ocr(
            model=config.resolve(cmd, "model", model, None, env="RP_PDF_VLM_MODEL"),
            base_url=config.resolve(cmd, "base_url", base_url, None, env="RP_PDF_VLM_BASE_URL"),
            organization=config.resolve(
                cmd, "organization", organization, None, env="RP_PDF_VLM_ORG"
            ),
            dpi=config.resolve(cmd, "dpi", dpi, 150),
            poppler_path=_resolve_path(cmd, "poppler_path", poppler_path),
        )
        _dump(result)
        if result["overall_status"] == "fail":
            raise typer.Exit(1)


# Capability report. rp-pdf's optional binaries are poppler's; LibreOffice is
# not on any rp-pdf code path.
app.command("doctor")(clikit.doctor_command("pdftotext", "pdftoppm", "pdfinfo"))


def _leading_global_options(args: list[str]) -> tuple[list[str], list[str]]:
    """Split leading group-level options (only --config/-c) from the rest, so a
    bare `rp-pdf --config x.toml FILE` can have its default command injected."""
    globals_: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in ("--config", "-c") and i + 1 < len(args):
            globals_.extend(args[i : i + 2])
            i += 2
            continue
        if token.startswith(("--config=", "-c=")):
            globals_.append(token)
            i += 1
            continue
        break
    return globals_, args[i:]


def _config_path_from(globals_: list[str]) -> str | None:
    for j, token in enumerate(globals_):
        if token in ("--config", "-c") and j + 1 < len(globals_):
            return globals_[j + 1]
        if token.startswith(("--config=", "-c=")):
            return token.split("=", 1)[1]
    return None


def _inject_default_command(argv: list[str]) -> list[str]:
    """Rewrite `rp-pdf [--config X] FILE ...` into `rp-pdf [--config X] CMD FILE ...`
    where CMD is the config's [default].command (or `index`). Leaves argv alone
    when the first token is already a subcommand or an option (e.g. --help)."""
    globals_, rest = _leading_global_options(argv[1:])
    if not rest:
        return argv
    first = rest[0]
    if first in COMMAND_NAMES or first.startswith("-"):
        return argv
    try:
        command = config.load(_config_path_from(globals_)).default_command()
    except core.RpPdfError:
        # A broken config surfaces cleanly later, via the callback's error path.
        command = None
    command = command or config.DEFAULT_COMMAND
    return [argv[0], *globals_, command, *rest]


def main() -> None:
    """Console-script entry point: apply default-action dispatch, then run Typer."""
    sys.argv = _inject_default_command(sys.argv)
    app()


if __name__ == "__main__":
    main()
