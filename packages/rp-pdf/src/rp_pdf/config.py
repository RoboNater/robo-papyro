"""Optional TOML config file for rp-pdf CLI defaults.

Precedence for every option is **flag → env var → config file → built-in
default**: the config file sits below command-line flags and ``RP_PDF_*``
environment variables, but above rp-pdf's built-in defaults. This module lives in
the CLI layer only — ``core`` never imports it, so the library and the future
MCP server stay free of config-file concerns.

The file is TOML (stdlib :mod:`tomllib`, no new dependencies). **There is no
single config file** — up to two apply at once, and both have fixed names:

1. an explicit path from ``--config PATH`` or ``$RP_PDF_CONFIG``. When given, it
   is the *only* file read, and it must exist;
2. otherwise, the **project** file: the nearest ``rp-pdf.toml`` walking up from
   the current directory — that name, in that place, is what a bare ``rp-pdf``
   picks up automatically;
3. and the **user** file, always at ``~/.config/rp-pdf/config.toml``.

2 and 3 are merged per key with the project file winning, so a repository can
override a personal default without restating the rest of it. Layout::

    [default]
    command = "markdown"          # what `rp-pdf FILE.pdf` runs; omit → "index"

    [markdown]                    # per-command defaults
    ai = true
    engine = "pypdf"

    [vlm]                         # shared VLM settings (model/base_url/...)
    base_url = "https://openrouter.ai/api/v1"
    organization = "org-abc123"
    # the API key is intentionally NOT read from the config file — env only.

    [ui]                          # shared human-output settings
    progress = true               # also settable per command, e.g. [markdown]
    describe = false

A VLM key set in a command section (e.g. ``[markdown].model``) overrides the
same key in ``[vlm]`` for that command; the same is true of the ``[ui]`` keys.

:func:`save_command_options` writes this file back out — it is what
``--save-config`` uses to turn a command line that worked into the default for
next time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomllib

from rp_core.errors import InputError
from rp_pdf.errors import RpPdfError

CONFIG_FILENAME = "rp-pdf.toml"
USER_CONFIG_PATH = Path.home() / ".config" / "rp-pdf" / "config.toml"
CONFIG_ENV_VAR = "RP_PDF_CONFIG"

# VLM settings fall back from a command section to the shared [vlm] section.
# The API key is deliberately absent: secrets stay in the environment.
_VLM_KEYS = frozenset({"model", "base_url", "organization", "cache_dir"})

# Human-output settings fall back to the shared [ui] section the same way, so
# "never show me progress" is one line rather than one line per command.
_UI_KEYS = frozenset({"progress", "describe"})

# The default action run by `rp-pdf FILE.pdf` when no [default].command is set.
# A cheap, local, network-free command — config must opt in to costly paths.
DEFAULT_COMMAND = "index"


class ConfigError(RpPdfError, InputError):
    """The config file could not be read or parsed."""


class Config:
    """Parsed rp-pdf config with precedence-aware lookups.

    An empty ``Config`` (no file found) is valid and makes every lookup fall
    through to the built-in default, so callers never special-case "no config".
    """

    def __init__(self, data: dict[str, Any], source: Path | None = None) -> None:
        self._data = data
        self.source = source

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name)
        return value if isinstance(value, dict) else {}

    def lookup(self, command: str | None, key: str) -> Any | None:
        """Config value for ``key`` under ``command``, falling back to the
        shared ``[vlm]`` / ``[ui]`` section for keys that have one, or ``None``
        if unset."""
        if command is not None:
            section = self.section(command)
            if key in section:
                return section[key]
        for keys, shared in ((_VLM_KEYS, "vlm"), (_UI_KEYS, "ui")):
            if key in keys and key in self.section(shared):
                return self.section(shared)[key]
        return None

    def default_command(self) -> str | None:
        command = self.section("default").get("command")
        return command if isinstance(command, str) else None


def _walk_up_for_project_config(start: Path) -> Path | None:
    """Nearest ``rp-pdf.toml`` at ``start`` or any ancestor, else ``None``."""
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge per section; ``override`` (project) wins per key."""
    merged: dict[str, Any] = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load(explicit_path: str | Path | None = None) -> Config:
    """Discover, parse, and merge the config file(s).

    An explicit path (from ``--config`` or ``$RP_PDF_CONFIG``) must exist and be
    valid — a missing/malformed explicit file is an error. Auto-discovered files
    that are absent are simply skipped; a malformed discovered file still errors,
    so a typo surfaces rather than being silently ignored.
    """
    explicit = explicit_path if explicit_path is not None else os.environ.get(CONFIG_ENV_VAR)
    if explicit:
        path = Path(explicit).expanduser()
        return Config(_read_toml(path), source=path)

    user = _read_toml(USER_CONFIG_PATH) if USER_CONFIG_PATH.is_file() else {}
    project_path = _walk_up_for_project_config(Path.cwd())
    project = _read_toml(project_path) if project_path is not None else {}
    if not user and not project:
        return Config({}, source=None)
    return Config(_merge(user, project), source=project_path or USER_CONFIG_PATH)


# --- writing a config file back out (--save-config) -------------------------


def _toml_scalar(value: Any) -> str:
    """One TOML value. Deliberately narrow: config options are scalars and lists
    of scalars, and a writer that only handles what rp-pdf actually stores
    cannot silently emit something tomllib will not read back."""
    if isinstance(value, bool):  # before int — bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_toml(data: dict[str, dict[str, Any]]) -> str:
    """Serialize ``{section: {key: value}}`` as TOML.

    Sections are written in the order given; empty sections are skipped so a
    save never leaves a bare header behind.
    """
    chunks: list[str] = []
    for section, values in data.items():
        if not values:
            continue
        lines = [f"[{section}]"]
        lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in values.items())
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + "\n" if chunks else ""


def save_command_options(path: Path, command: str, values: dict[str, Any]) -> Path:
    """Merge ``values`` into the config file at ``path`` and write it back.

    Keys land in ``[command]``, except the shared VLM ones, which land in
    ``[vlm]`` where every command can see them — the layout a hand-written file
    would use, since this function's other job is to teach that layout.
    ``None`` values are dropped rather than written as anything: an option that
    was never set has no default to record.

    An existing file is *merged*, not replaced — other sections and other keys
    survive — but it is rewritten from its parsed contents, so **comments and
    formatting in it are lost**. Callers say so; this function does not print.
    """
    path = Path(path).expanduser()
    existing = _read_toml(path) if path.is_file() else {}
    merged: dict[str, dict[str, Any]] = {
        key: dict(value) if isinstance(value, dict) else value  # type: ignore[misc]
        for key, value in existing.items()
    }
    for key, value in values.items():
        if value is None:
            continue
        section = "vlm" if key in _VLM_KEYS else command
        merged.setdefault(section, {})[key] = value.as_posix() if isinstance(value, Path) else value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(merged), encoding="utf-8")
    return path


def is_auto_discovered(path: Path) -> bool:
    """Whether a bare ``rp-pdf`` run would find ``path`` on its own.

    True for the user file and for a ``rp-pdf.toml`` at or above the current
    directory. Anywhere else the file is real but inert until ``--config`` or
    ``$RP_PDF_CONFIG`` names it — worth telling someone who just saved one.
    """
    path = Path(path).expanduser().resolve()
    if path == USER_CONFIG_PATH.expanduser().resolve():
        return True
    if path.name != CONFIG_FILENAME:
        return False
    cwd = Path.cwd().resolve()
    return path.parent in (cwd, *cwd.parents)


# The active config for this process, loaded once by the CLI callback so every
# command resolves against the same file(s).
_active: Config | None = None


def set_active(config: Config) -> None:
    global _active
    _active = config


def active() -> Config:
    return _active if _active is not None else Config({}, source=None)


def resolve(
    command: str | None,
    key: str,
    flag_value: Any | None,
    default: Any,
    *,
    env: str | None = None,
) -> Any:
    """Resolve one option by precedence: flag → env → config → default.

    ``flag_value`` is the value parsed from the command line, or ``None`` when
    the flag was not given (booleans use paired ``--x/--no-x`` flags so an
    omitted flag is genuinely ``None``, not ``False``). ``env`` names the
    environment variable to consult, if any (only the VLM settings and the
    cache dir have one). Config values come from the active config's ``command``
    section, falling back to ``[vlm]`` for VLM keys.
    """
    if flag_value is not None:
        return flag_value
    if env is not None:
        env_value = os.environ.get(env)
        if env_value:
            return env_value
    config_value = active().lookup(command, key)
    if config_value is not None:
        return config_value
    return default
