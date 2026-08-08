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

The commands that do real work also take three options about the run itself
rather than its result: --describe prints what the resolved options add up to
before starting, --progress shows a live stderr line while it runs, and
--save-config writes the options it was given to a TOML file so the next
document does not need the same command line. The first two default to on only
when stderr is a terminal, so nothing changes for a caller reading stdout from a
pipe. Each command resolves through one `Options` object that all three read, so
what is described, what runs, and what is saved cannot disagree.
"""

from __future__ import annotations

import csv
import enum
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from rp_core import clikit
from rp_pdf import config, core, describe
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
SaveConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--save-config",
        help="After a successful run, write the options you passed to this TOML file "
        "so the next document inherits them (built-in defaults and -o are left out). "
        "'rp-pdf.toml' in this directory or any parent is found automatically; "
        "anywhere else needs --config to read back",
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


def _errors():
    """The suite's error contract: an ErrorEnvelope on stderr, exit code from
    the error class (rp_core.errors). Every rp-pdf error subclasses that
    hierarchy, so nothing extra needs listing here."""
    return clikit.error_handler()


#: Options `--save-config` never writes, per command, even when they were given
#: explicitly: they name *this* document's output file, so carrying them to the
#: next document would silently overwrite this one's result. Directory targets
#: (`images --out`, `render --out`, `tables --csv`) are not here — reusing a
#: directory is the normal case, and `[render].out` is documented as a setting.
NEVER_SAVED: dict[str, frozenset[str]] = {"markdown": frozenset({"out"})}


class Options:
    """A command's resolved options, and which of them the user chose.

    Both are needed, for different reasons. The **resolved** values are what
    runs and what ``--describe`` reports: defaults included, because a default
    the user never typed is still part of what is about to happen. The **chosen**
    ones — those that came from an actual flag — are what ``--save-config``
    writes, because a saved built-in default would freeze today's default into
    the file, and the point of the file is to record a decision, not a snapshot.

    Values from the environment or an existing config file count as neither
    chosen nor lost: they already live somewhere that outlasts this run.

    One call per option, resolving and recording together, so the run, the
    description, and the saved file cannot drift apart.
    """

    def __init__(self, command: str) -> None:
        self.command = command
        self.values: dict[str, Any] = {}
        self.chosen: dict[str, Any] = {}

    def resolve(self, key: str, flag: Any, default: Any, *, env: str | None = None) -> Any:
        return self._record(key, flag, config.resolve(self.command, key, flag, default, env=env))

    def path(self, key: str, flag: Path | None, env: str | None = None) -> Path | None:
        return self._record(key, flag, _resolve_path(self.command, key, flag, None, env))

    def engine(self, flag: TextEngine | None) -> str:
        return self._record("engine", flag, _resolve_engine(self.command, flag))

    def display(self, key: str, flag: bool | None) -> bool:
        """Resolve --describe/--progress: flag -> RP_PDF_* -> config -> terminal.

        These read the config through `Config.lookup` rather than
        `config.resolve` because they have no fixed default to pass it: with
        nothing set the answer is whether stderr is a terminal, which is a fact
        about this process, not a configured value. Precedence is otherwise
        identical, and `[ui]` backs the per-command sections the way `[vlm]`
        backs the model settings — including on the way out, so an explicit
        `--no-progress --save-config` records `[ui] progress = false`.
        """
        return self._record(
            key,
            flag,
            clikit.display_enabled(
                flag,
                env_value=os.environ.get(f"RP_PDF_{key.upper()}"),
                config_value=config.active().lookup(self.command, key),
            ),
        )

    def _record(self, key: str, flag: Any, value: Any) -> Any:
        self.values[key] = value
        if flag is not None:
            self.chosen[key] = value
        return value

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def savable(self) -> dict[str, Any]:
        skip = NEVER_SAVED.get(self.command, frozenset())
        return {k: v for k, v in self.chosen.items() if k not in skip}

    def skipped(self) -> list[str]:
        return sorted(NEVER_SAVED.get(self.command, frozenset()) & set(self.chosen))


def _announce_labels(file: Path, opts: Options, password: str | None, reporter) -> None:
    """Tell the user (on stderr) when --pages is interpreted via page labels.

    Written through the reporter rather than with a bare print: this runs inside
    the job, so a progress line may be painted, and it also opens the PDF —
    which is why it belongs inside, where the reporter is already ticking.
    """
    if opts["physical"] or str(opts["pages"]).strip().lower() == "all":
        return
    if core.get_page_labels(file, password=password) is not None:
        reporter.message(
            "Interpreting --pages using the PDF's page labels; "
            "pass --physical for 1-based physical page numbers."
        )


def _save_config(options: Options, target: Path | None) -> None:
    """Persist the options this run was given, when --save-config asked for it.

    Called after the work succeeds, deliberately: what gets recorded is a
    command line that is known to have worked, not one that was merely typed.
    """
    if target is None:
        return
    command = options.command
    savable = options.savable()
    existed = Path(target).expanduser().is_file()
    written = config.save_command_options(target, command, savable)
    sections = ", ".join(f"[{name}]" for name in config.sections_for(command, savable))
    print(
        f"Saved the options you passed to {written}"
        + (f" as {sections}." if sections else " — you passed none, so nothing changed."),
        file=sys.stderr,
    )
    for key in options.skipped():
        print(
            f"'{key}' was not saved: it names this document's output, and reusing "
            "it would overwrite this run's result on the next document.",
            file=sys.stderr,
        )
    if existed:
        print(
            "An existing file was merged and rewritten from its parsed contents: "
            "other sections and keys are intact, but comments and formatting are not.",
            file=sys.stderr,
        )
    if config.is_auto_discovered(written):
        print("It will be picked up automatically on the next run.", file=sys.stderr)
    else:
        print(
            f"This path is not discovered automatically — pass --config {written} "
            f"(or set RP_PDF_CONFIG={written}) to use it, or save to "
            f"./{config.CONFIG_FILENAME} instead.",
            file=sys.stderr,
        )


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
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Extract text; JSON by default, --plain for raw text."""
    with _errors():
        opts = Options("text")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        opts.resolve("layout", layout, False)
        opts.engine(engine)
        opts.resolve("plain", plain, False)
        opts.path("poppler_path", poppler_path)
        title, entries = describe.text_job(file, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = core.get_text(
                file,
                opts["pages"],
                layout=opts["layout"],
                engine=opts["engine"],
                password=password,
                physical=opts["physical"],
                poppler_path=opts["poppler_path"],
                progress=reporter,
            )
        if opts["plain"]:
            print("\n\n".join(page.text for page in result))
        else:
            _dump(result)
        _save_config(opts, save_config)


@app.command()
def tables(
    file: FileArg,
    pages: PagesOpt = None,
    csv_dir: Annotated[
        Path | None, typer.Option("--csv", help="Write one CSV per table to this directory")
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = None,
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Extract tables as JSON, or one CSV file per table with --csv."""
    with _errors():
        opts = Options("tables")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        opts.path("csv", csv_dir)
        title, entries = describe.tables_job(file, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = core.get_tables(
                file,
                opts["pages"],
                password=password,
                physical=opts["physical"],
                progress=reporter,
            )
        csv_target = opts["csv"]
        if csv_target is None:
            _dump(result)
            _save_config(opts, save_config)
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
        _save_config(opts, save_config)


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
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Search page text; hits report both physical and labeled page numbers."""
    with _errors():
        opts = Options("search")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        max_v = opts.resolve("max", max_hits, 100)
        opts.resolve("regex", regex, False)
        opts.resolve("case_sensitive", case_sensitive, False)
        opts.resolve("context", context, 80)
        opts.engine(engine)
        opts.resolve("plain", plain, False)
        opts.path("poppler_path", poppler_path)
        title, entries = describe.search_job(file, query, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = core.search(
                file,
                query,
                opts["pages"],
                regex=opts["regex"],
                ignore_case=not opts["case_sensitive"],
                context=opts["context"],
                max_hits=max_v,
                engine=opts["engine"],
                password=password,
                physical=opts["physical"],
                poppler_path=opts["poppler_path"],
                progress=reporter,
            )
        if opts["plain"]:
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
        _save_config(opts, save_config)


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
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Extract embedded images."""
    with _errors():
        opts = Options("images")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        opts.path("out", out)
        title, entries = describe.images_job(file, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = core.get_images(
                file,
                opts["pages"],
                out_dir=opts["out"],
                password=password,
                physical=opts["physical"],
                progress=reporter,
            )
        _dump(result)
        _save_config(opts, save_config)


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
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Convert pages to Markdown: programmatic extraction, plus --ai review and optional --ocr."""
    with _errors():
        opts = Options("markdown")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        out_v = opts.path("out", out)
        opts.path("images_dir", images_dir)
        opts.resolve("ai", ai, False)
        opts.resolve("ocr", ocr, False)
        opts.resolve("model", model, None, env="RP_PDF_VLM_MODEL")
        opts.resolve("base_url", base_url, None, env="RP_PDF_VLM_BASE_URL")
        opts.resolve("organization", organization, None, env="RP_PDF_VLM_ORG")
        opts.resolve("jobs", jobs, 1)
        opts.resolve("dpi", dpi, 150)
        opts.engine(engine)
        opts.resolve("outline_headings", outline_headings, False)
        opts.resolve("outline_context", outline_context, False)
        opts.resolve("full", full, False)
        opts.resolve("cache", cache, True)
        opts.path("cache_dir", cache_dir, env="RP_PDF_CACHE_DIR")
        opts.path("poppler_path", poppler_path)
        title, entries = describe.markdown_job(file, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = md.to_markdown(
                file,
                opts["pages"],
                images_dir=opts["images_dir"],
                ai=opts["ai"],
                ocr=opts["ocr"],
                model=opts["model"],
                base_url=opts["base_url"],
                organization=opts["organization"],
                jobs=opts["jobs"],
                dpi=opts["dpi"],
                engine=opts["engine"],
                outline_headings=opts["outline_headings"],
                outline_context=opts["outline_context"],
                password=password,
                physical=opts["physical"],
                poppler_path=opts["poppler_path"],
                cache_dir=opts["cache_dir"],
                use_cache=opts["cache"],
                progress=reporter,
            )
        for warning in result.warnings:
            print(warning, file=sys.stderr)
        if opts["full"]:
            _dump(result)
        elif out_v is not None:
            out_v.write_text(result.markdown, encoding="utf-8")
            print(f"Wrote {out_v}", file=sys.stderr)
        else:
            print(result.markdown, end="")
        _save_config(opts, save_config)


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
    show_progress: clikit.progress_option = None,
    show_description: clikit.describe_option = None,
    save_config: SaveConfigOpt = None,
) -> None:
    """Rasterize pages to image files."""
    with _errors():
        opts = Options("render")
        opts.resolve("pages", pages, "all")
        opts.resolve("physical", physical, False)
        opts.path("out", out)
        opts.resolve("dpi", dpi, 200)
        opts.resolve("format", fmt, "png")
        opts.path("poppler_path", poppler_path)
        if opts["out"] is None:
            raise core.RpPdfError(
                "render needs an output directory: pass --out or set [render].out in the config."
            )
        title, entries = describe.render_job(file, opts.values)
        with clikit.job(
            title,
            entries,
            describe=opts.display("describe", show_description),
            progress=opts.display("progress", show_progress),
        ) as reporter:
            _announce_labels(file, opts, password, reporter)
            result = core.render_pages(
                file,
                opts["pages"],
                opts["out"],
                dpi=opts["dpi"],
                fmt=opts["format"],
                password=password,
                poppler_path=opts["poppler_path"],
                physical=opts["physical"],
                progress=reporter,
            )
        _dump(result)
        _save_config(opts, save_config)


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
