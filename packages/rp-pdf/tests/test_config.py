"""Tests for the optional TOML config file (rp_pdf.config) and its integration
with the CLI: discovery, the flag → env → config → default precedence matrix,
the `rp-pdf FILE` default action, and the guarantee that the API key is never
read from the config file.

The unit tests exercise rp_pdf.config directly (no subprocess). The integration
tests drive the installed `rp-pdf` entry point via subprocess with a controlled
working directory so config-file discovery is deterministic; they use the
`index` command and the `pypdf` text engine so no poppler binary is needed.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from rp_pdf import config
from rp_pdf.config import Config, ConfigError


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def restore_active():
    """Save/restore the process-wide active config around a test."""
    saved = config._active
    try:
        yield
    finally:
        config._active = saved


@pytest.fixture()
def clean_env(monkeypatch):
    for var in (
        "RP_PDF_VLM_MODEL",
        "RP_PDF_VLM_BASE_URL",
        "RP_PDF_VLM_ORG",
        "RP_PDF_CACHE_DIR",
        "RP_PDF_CONFIG",
    ):
        monkeypatch.delenv(var, raising=False)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_explicit_path_wins(tmp_path, clean_env):
    cfg = write(tmp_path / "custom.toml", '[default]\ncommand = "text"\n')
    loaded = config.load(cfg)
    assert loaded.source == cfg
    assert loaded.default_command() == "text"


def test_explicit_missing_path_errors(tmp_path, clean_env):
    with pytest.raises(ConfigError, match="not found"):
        config.load(tmp_path / "nope.toml")


def test_rp_pdf_config_env_var(tmp_path, clean_env, monkeypatch):
    cfg = write(tmp_path / "env.toml", '[text]\nengine = "pypdf"\n')
    monkeypatch.setenv("RP_PDF_CONFIG", str(cfg))
    assert config.load().lookup("text", "engine") == "pypdf"


def test_nearest_rp_pdf_toml_walking_up(tmp_path, clean_env, monkeypatch):
    write(tmp_path / "rp-pdf.toml", '[text]\nengine = "pypdf"\n')
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    # No user config in the picture.
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "no-user-config.toml")
    assert config.load().lookup("text", "engine") == "pypdf"


def test_no_config_anywhere_is_empty(tmp_path, clean_env, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    loaded = config.load()
    assert loaded.source is None
    assert loaded.default_command() is None
    assert loaded.lookup("text", "engine") is None


def test_project_overrides_user_per_key(tmp_path, clean_env, monkeypatch):
    user = write(tmp_path / "user.toml", '[text]\nengine = "pdfplumber"\nlayout = true\n')
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    write(project_dir / "rp-pdf.toml", '[text]\nengine = "pypdf"\n')
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", user)
    loaded = config.load()
    # project wins for engine; user's layout survives (merged per key).
    assert loaded.lookup("text", "engine") == "pypdf"
    assert loaded.lookup("text", "layout") is True


def test_malformed_config_raises_configerror(tmp_path, clean_env):
    bad = write(tmp_path / "bad.toml", "[default\ncommand = 'text'\n")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        config.load(bad)


# --------------------------------------------------------------------------- #
# lookup: command section vs shared [vlm]
# --------------------------------------------------------------------------- #
def test_vlm_key_falls_back_to_vlm_section():
    cfg = Config({"vlm": {"model": "shared"}})
    assert cfg.lookup("markdown", "model") == "shared"


def test_command_section_overrides_vlm_section():
    cfg = Config({"vlm": {"model": "shared"}, "markdown": {"model": "scoped"}})
    assert cfg.lookup("markdown", "model") == "scoped"
    assert cfg.lookup("validate-vlm-ocr", "model") == "shared"


def test_non_vlm_key_does_not_fall_back_to_vlm():
    cfg = Config({"vlm": {"engine": "pypdf"}})
    assert cfg.lookup("text", "engine") is None


# --------------------------------------------------------------------------- #
# resolve: full precedence matrix (flag > env > config > default)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def with_config(restore_active):
    def _set(data):
        config.set_active(Config(data))

    return _set


def test_flag_beats_everything(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("RP_PDF_VLM_MODEL", "env")
    assert config.resolve("markdown", "model", "flag", None, env="RP_PDF_VLM_MODEL") == "flag"


def test_env_beats_config(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("RP_PDF_VLM_MODEL", "env")
    assert config.resolve("markdown", "model", None, None, env="RP_PDF_VLM_MODEL") == "env"


def test_config_beats_default(with_config, clean_env):
    with_config({"markdown": {"model": "cfg"}})
    assert config.resolve("markdown", "model", None, "builtin", env="RP_PDF_VLM_MODEL") == "cfg"


def test_default_when_nothing_set(with_config, clean_env):
    with_config({})
    assert config.resolve("markdown", "model", None, "builtin", env="RP_PDF_VLM_MODEL") == "builtin"


def test_bool_tristate_config_turns_on(with_config, clean_env):
    with_config({"markdown": {"ai": True}})
    assert config.resolve("markdown", "ai", None, False) is True


def test_bool_negation_flag_beats_config(with_config, clean_env):
    with_config({"markdown": {"ai": True}})
    # --no-ai parses to False, which must override a config that enabled ai.
    assert config.resolve("markdown", "ai", False, False) is False


def test_int_option_from_config(with_config, clean_env):
    with_config({"markdown": {"dpi": 300}})
    assert config.resolve("markdown", "dpi", None, 150) == 300


def test_empty_env_var_is_ignored(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("RP_PDF_VLM_MODEL", "")
    # An empty env var must not shadow the config value.
    assert config.resolve("markdown", "model", None, None, env="RP_PDF_VLM_MODEL") == "cfg"


# --------------------------------------------------------------------------- #
# Secrets: the API key is never sourced from the config file
# --------------------------------------------------------------------------- #
def test_api_key_not_read_from_config(tmp_path, clean_env, monkeypatch):
    """Even with an api_key in the file, VLM setup still demands the env key."""
    from rp_pdf.vlm_utils import VlmError, make_client

    write(tmp_path / "rp-pdf.toml", '[vlm]\napi_key = "sk-should-be-ignored"\nmodel = "m"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    config.set_active(config.load())
    monkeypatch.delenv("RP_PDF_VLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # No base_url and no env key → make_client must fail asking for the key,
    # proving the config's api_key was not picked up.
    with pytest.raises(VlmError, match="API key"):
        make_client("m", None)


# --------------------------------------------------------------------------- #
# Integration: the `rp-pdf FILE` default action + CLI precedence via subprocess
# --------------------------------------------------------------------------- #
def run_cli(*args, cwd=None, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("RP_", "OPENAI_"))}
    if env:
        base.update(env)
    return subprocess.run(
        ["rp-pdf", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=base,
    )


def test_default_action_without_config_runs_index(text_pdf, tmp_path):
    result = run_cli(text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["page_count"] == 3  # index output


def test_default_action_uses_config_command(text_pdf, tmp_path):
    write(
        tmp_path / "rp-pdf.toml",
        '[default]\ncommand = "text"\n[text]\nengine = "pypdf"\npages = "2"\nplain = true\n',
    )
    result = run_cli(text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Chapter Two" in result.stdout
    assert not result.stdout.lstrip().startswith(("[", "{"))  # plain, not JSON


def test_flag_overrides_config_command_option(text_pdf, tmp_path):
    write(
        tmp_path / "rp-pdf.toml",
        '[default]\ncommand = "text"\n[text]\nengine = "pypdf"\npages = "2"\nplain = true\n',
    )
    # --pages 1 on the command line overrides the config's pages = "2".
    result = run_cli(text_pdf, "--pages", "1", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Chapter One" in result.stdout


def test_explicit_subcommand_still_works_with_config(text_pdf, tmp_path):
    write(tmp_path / "rp-pdf.toml", '[default]\ncommand = "text"\n')
    result = run_cli("index", text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["page_count"] == 3


def test_config_flag_points_at_explicit_file(text_pdf, tmp_path):
    cfg = write(tmp_path / "elsewhere.toml", '[default]\ncommand = "index"\n')
    # Run from a dir with no rp-pdf.toml; --config supplies the file.
    work = tmp_path / "work"
    work.mkdir()
    result = run_cli("--config", cfg, text_pdf, cwd=work)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["page_count"] == 3


def test_malformed_config_is_clean_cli_error(text_pdf, tmp_path, cli_error):
    write(tmp_path / "rp-pdf.toml", "[default\ncommand = 'index'\n")
    result = run_cli("index", text_pdf, cwd=tmp_path)
    assert result.returncode == 1
    assert "Invalid TOML" in cli_error(result)["message"]
    assert "Traceback" not in result.stderr


# --------------------------------------------------------------------------- #
# The [ui] section (--progress / --describe)
# --------------------------------------------------------------------------- #
def test_ui_key_falls_back_to_ui_section():
    cfg = Config({"ui": {"progress": False}})
    assert cfg.lookup("markdown", "progress") is False


def test_command_section_overrides_ui_section():
    cfg = Config({"ui": {"progress": False}, "markdown": {"progress": True}})
    assert cfg.lookup("markdown", "progress") is True
    assert cfg.lookup("text", "progress") is False


def test_non_ui_key_does_not_fall_back_to_ui():
    """[ui] backs exactly two keys. A stray one there must not leak into an
    unrelated option of the same name."""
    cfg = Config({"ui": {"pages": "1-5"}})
    assert cfg.lookup("markdown", "pages") is None


# --------------------------------------------------------------------------- #
# Writing a config file back out (--save-config)
# --------------------------------------------------------------------------- #
def test_dump_toml_round_trips_through_tomllib():
    import tomllib

    data = {"markdown": {"ai": True, "jobs": 4, "pages": "1-5", "dpi": 150.0}}
    assert tomllib.loads(config.dump_toml(data)) == data


def test_dump_toml_quotes_and_escapes_strings():
    text = config.dump_toml({"markdown": {"out": 'a "b"\\c'}})
    import tomllib

    assert tomllib.loads(text)["markdown"]["out"] == 'a "b"\\c'


def test_dump_toml_writes_booleans_not_python_repr():
    """`True` is not TOML. Getting this wrong makes a file that cannot be read
    back, which the save path would not otherwise notice."""
    assert "ai = true" in config.dump_toml({"markdown": {"ai": True}})
    assert "True" not in config.dump_toml({"markdown": {"ai": True}})


def test_dump_toml_skips_empty_sections():
    assert config.dump_toml({"markdown": {}}) == ""


def test_save_writes_command_and_vlm_sections(tmp_path):
    target = tmp_path / "rp-pdf.toml"
    config.save_command_options(
        target, "markdown", {"ai": True, "jobs": 4, "model": "gpt-4o", "base_url": "https://x/v1"}
    )
    saved = config.load(target)
    assert saved.section("markdown") == {"ai": True, "jobs": 4}
    # VLM keys go where every command can see them, as a hand-written file would.
    assert saved.section("vlm") == {"model": "gpt-4o", "base_url": "https://x/v1"}


def test_save_omits_unset_options(tmp_path):
    target = tmp_path / "rp-pdf.toml"
    config.save_command_options(target, "markdown", {"ai": True, "out": None, "model": None})
    assert config.load(target).section("markdown") == {"ai": True}
    assert "model" not in config.load(target).section("vlm")


def test_save_serializes_paths_as_strings(tmp_path):
    from pathlib import Path

    target = tmp_path / "rp-pdf.toml"
    config.save_command_options(target, "markdown", {"images_dir": Path("images")})
    assert config.load(target).section("markdown") == {"images_dir": "images"}


def test_save_merges_into_an_existing_file(tmp_path):
    target = write(
        tmp_path / "rp-pdf.toml",
        '[default]\ncommand = "markdown"\n\n[markdown]\nai = true\npages = "1-5"\n',
    )
    config.save_command_options(target, "markdown", {"ai": False, "jobs": 8})
    saved = config.load(target)
    assert saved.default_command() == "markdown"  # other sections survive
    assert saved.section("markdown") == {"ai": False, "pages": "1-5", "jobs": 8}


def test_save_round_trips_so_the_next_run_can_read_it(tmp_path):
    """The whole point of the feature: what is written must resolve as a default."""
    target = tmp_path / "rp-pdf.toml"
    config.save_command_options(target, "markdown", {"ai": True, "engine": "pypdf"})
    config.set_active(config.load(target))
    try:
        assert config.resolve("markdown", "ai", None, False) is True
        assert config.resolve("markdown", "engine", None, "poppler") == "pypdf"
    finally:
        config.set_active(Config({}))


def test_save_creates_missing_parent_directories(tmp_path):
    target = tmp_path / "nested" / "deeper" / "rp-pdf.toml"
    config.save_command_options(target, "text", {"engine": "pypdf"})
    assert target.is_file()


def test_is_auto_discovered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.is_auto_discovered(tmp_path / "rp-pdf.toml") is True
    # A parent's rp-pdf.toml is found by walking up.
    assert config.is_auto_discovered(tmp_path.parent / "rp-pdf.toml") is True
    # The right name in the wrong place, and the wrong name in the right place.
    assert config.is_auto_discovered(tmp_path / "sub" / "rp-pdf.toml") is False
    assert config.is_auto_discovered(tmp_path / "other.toml") is False
    assert config.is_auto_discovered(config.USER_CONFIG_PATH) is True


# --------------------------------------------------------------------------- #
# Integration: --save-config end to end
# --------------------------------------------------------------------------- #
def test_save_config_then_the_next_run_inherits_it(text_pdf, tmp_path):
    """The feature as a user experiences it: get the options right once, and the
    next document does not need them."""
    saved = run_cli(
        "text",
        text_pdf,
        "--engine",
        "pypdf",
        "--pages",
        "2",
        "--plain",
        "--save-config",
        "rp-pdf.toml",
        cwd=tmp_path,
    )
    assert saved.returncode == 0, saved.stderr
    assert (tmp_path / "rp-pdf.toml").is_file()
    assert "picked up automatically" in saved.stderr

    # No options at all this time: everything comes from the file just written.
    again = run_cli("text", text_pdf, cwd=tmp_path)
    assert again.returncode == 0, again.stderr
    assert "Chapter Two" in again.stdout
    assert not again.stdout.lstrip().startswith(("[", "{"))  # plain = true persisted


def test_save_config_warns_when_the_path_is_not_auto_discovered(text_pdf, tmp_path):
    target = tmp_path / "elsewhere" / "options.toml"
    result = run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert target.is_file()
    assert "not discovered automatically" in result.stderr
    assert "--config" in result.stderr


def test_save_config_reports_that_comments_are_lost_only_when_rewriting(text_pdf, tmp_path):
    target = tmp_path / "rp-pdf.toml"
    first = run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert "comments" not in first.stderr  # nothing existed to lose
    second = run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert "comments and formatting are not" in second.stderr


def test_save_config_does_not_write_when_the_run_fails(tmp_path):
    """What gets recorded is a command line known to have worked."""
    target = tmp_path / "rp-pdf.toml"
    result = run_cli("text", tmp_path / "missing.pdf", "--save-config", target, cwd=tmp_path)
    assert result.returncode == 1
    assert not target.exists()


def test_save_config_message_goes_to_stderr_not_stdout(text_pdf, tmp_path):
    result = run_cli(
        "index", text_pdf, cwd=tmp_path
    )  # sanity: index has no --save-config to interfere
    assert json.loads(result.stdout)["page_count"] == 3
    saved = run_cli("images", text_pdf, "--save-config", "rp-pdf.toml", cwd=tmp_path)
    assert isinstance(json.loads(saved.stdout), list)
    assert "Saved the options you passed" in saved.stderr


def test_ui_section_turns_the_description_on_for_a_pipe(text_pdf, tmp_path):
    """`[ui]` is how someone who wants the description in a log gets it: the
    terminal default is only a default."""
    write(tmp_path / "rp-pdf.toml", "[ui]\ndescribe = true\n[text]\nengine = 'pypdf'\n")
    result = run_cli("text", text_pdf, "--pages", "1", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "rp-pdf text — " in result.stderr


def test_env_var_overrides_the_ui_section(text_pdf, tmp_path):
    write(tmp_path / "rp-pdf.toml", "[ui]\ndescribe = true\n[text]\nengine = 'pypdf'\n")
    result = run_cli("text", text_pdf, "--pages", "1", cwd=tmp_path, env={"RP_PDF_DESCRIBE": "0"})
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_the_flag_overrides_the_env_var(text_pdf, tmp_path):
    result = run_cli(
        "text",
        text_pdf,
        "--pages",
        "1",
        "--engine",
        "pypdf",
        "--describe",
        cwd=tmp_path,
        env={"RP_PDF_DESCRIBE": "0"},
    )
    assert "rp-pdf text — " in result.stderr


def test_save_config_records_only_what_was_passed(text_pdf, tmp_path):
    """Not a snapshot of every resolved value. Writing back a built-in default
    would freeze today's default into the file, and the file exists to record a
    decision."""
    target = tmp_path / "rp-pdf.toml"
    result = run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert config.load(target).section("text") == {"engine": "pypdf"}


def test_save_config_does_not_record_environment_values(text_pdf, tmp_path):
    """An env var already outlives the run; copying it into a file duplicates a
    setting the user manages somewhere else."""
    target = tmp_path / "rp-pdf.toml"
    run_cli(
        "markdown",
        text_pdf,
        "--engine",
        "pypdf",
        "--save-config",
        target,
        cwd=tmp_path,
        env={"RP_PDF_VLM_MODEL": "from-the-environment"},
    )
    assert "vlm" not in config.load(target)._data


def test_save_config_refuses_to_persist_the_markdown_output_file(text_pdf, tmp_path):
    """-o names *this* document's output. Persisted, the next document would
    silently overwrite this one's result."""
    target = tmp_path / "rp-pdf.toml"
    result = run_cli(
        "markdown",
        text_pdf,
        "--engine",
        "pypdf",
        "-o",
        tmp_path / "report.md",
        "--ai",
        "--no-ai",  # last wins; keeps the run local and cheap
        "--save-config",
        target,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    saved = config.load(target).section("markdown")
    assert "out" not in saved
    assert saved == {"engine": "pypdf", "ai": False}
    assert "was not saved" in result.stderr


def test_save_config_keeps_directory_targets(text_pdf, tmp_path):
    """A directory is reusable across documents, unlike an output *file*."""
    target = tmp_path / "rp-pdf.toml"
    run_cli("images", text_pdf, "--out", tmp_path / "media", "--save-config", target, cwd=tmp_path)
    assert config.load(target).section("images")["out"] == str(tmp_path / "media")


# --------------------------------------------------------------------------- #
# --save-config failure paths and the [ui] round trip
# --------------------------------------------------------------------------- #
def test_save_to_a_directory_is_a_clean_error_not_a_traceback(tmp_path):
    target = tmp_path / "adirectory"
    target.mkdir()
    with pytest.raises(ConfigError, match="Could not write config file"):
        config.save_command_options(target, "text", {"engine": "pypdf"})


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0,
    reason="root ignores directory permissions, so there is nothing to fail on",
)
def test_save_to_an_unwritable_parent_is_a_clean_error(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        with pytest.raises(ConfigError, match="Could not write config file"):
            config.save_command_options(locked / "rp-pdf.toml", "text", {"engine": "pypdf"})
    finally:
        locked.chmod(0o700)  # so tmp_path cleanup can remove it


def test_cli_reports_a_bad_save_target_as_an_error_envelope(text_pdf, tmp_path, cli_error):
    """The suite's contract holds on this path too: a message and an envelope on
    stderr, exit 1, no traceback."""
    target = tmp_path / "adirectory"
    target.mkdir()
    result = run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    detail = cli_error(result)
    assert detail["type"] == "ConfigError"
    assert detail["exit_code"] == 1
    assert str(target) in detail["message"]


def test_display_flags_are_saved_to_the_ui_section(text_pdf, tmp_path):
    """`--save-config` records the options you passed — with no carve-out for
    these two, which is what `[ui]` exists to hold."""
    target = tmp_path / "rp-pdf.toml"
    result = run_cli(
        "text",
        text_pdf,
        "--engine",
        "pypdf",
        "--no-progress",
        "--describe",
        "--save-config",
        target,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    saved = config.load(target)
    assert saved.section("ui") == {"progress": False, "describe": True}
    assert saved.section("text") == {"engine": "pypdf"}
    assert "[ui]" in result.stderr  # the message names the sections it wrote


def test_unpassed_display_flags_are_not_saved(text_pdf, tmp_path):
    """A run in a terminal resolves progress to True; that is a fact about the
    terminal, not a choice, and must not be frozen into the file."""
    target = tmp_path / "rp-pdf.toml"
    run_cli("text", text_pdf, "--engine", "pypdf", "--save-config", target, cwd=tmp_path)
    assert "ui" not in config.load(target)._data


def test_saved_ui_settings_are_read_back(text_pdf, tmp_path):
    write(tmp_path / "rp-pdf.toml", "[ui]\ndescribe = true\n[text]\nengine = 'pypdf'\n")
    result = run_cli("text", text_pdf, "--pages", "1", cwd=tmp_path)
    assert "rp-pdf text — " in result.stderr


def test_the_save_message_names_the_vlm_section(text_pdf, tmp_path):
    """A run that set only --model writes `[vlm]`; saying `[markdown]` would
    send someone looking in the wrong place."""
    target = tmp_path / "rp-pdf.toml"
    result = run_cli(
        "markdown",
        text_pdf,
        "--engine",
        "pypdf",
        "--model",
        "gpt-4o-mini",
        "--save-config",
        target,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "[markdown], [vlm]" in result.stderr


def test_sections_for_routes_shared_keys():
    assert config.sections_for("markdown", {"ai": True}) == ["markdown"]
    assert config.sections_for("markdown", {"model": "m"}) == ["vlm"]
    assert config.sections_for("text", {"progress": False}) == ["ui"]
    assert config.sections_for("text", {"engine": "pypdf", "model": "m", "describe": True}) == [
        "text",
        "ui",
        "vlm",
    ]


# --------------------------------------------------------------------------- #
# The write is atomic: a failure part-way through must not damage the file
# --------------------------------------------------------------------------- #
ORIGINAL = '[default]\ncommand = "markdown"\n\n[ui]\nprogress = false\n\n[text]\nengine = "pypdf"\n'


@pytest.mark.parametrize(
    ("victim", "what"),
    [
        ("fsync", "a full disk part-way through the write"),
        ("replace", "a failure at the final rename"),
    ],
)
def test_a_failed_write_leaves_the_previous_file_byte_identical(
    tmp_path, monkeypatch, victim, what
):
    """`write_text` would truncate the target first, so a failure here does not
    lose one option — it loses the file, including sections this call merged in
    from disk and never mentioned."""
    target = write(tmp_path / "rp-pdf.toml", ORIGINAL)
    before = target.read_bytes()

    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(config.os, victim, boom)
    with pytest.raises(ConfigError, match="Could not write config file"):
        config.save_command_options(target, "text", {"engine": "poppler", "layout": True})

    assert target.read_bytes() == before, f"the config was damaged by {what}"


@pytest.mark.parametrize("victim", ["fsync", "replace"])
def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path, monkeypatch, victim):
    target = write(tmp_path / "rp-pdf.toml", ORIGINAL)

    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(config.os, victim, boom)
    with pytest.raises(ConfigError):
        config.save_command_options(target, "text", {"engine": "poppler"})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["rp-pdf.toml"]


def test_the_new_contents_are_readable_after_an_atomic_replace(tmp_path):
    target = write(tmp_path / "rp-pdf.toml", ORIGINAL)
    config.save_command_options(target, "text", {"engine": "poppler"})
    saved = config.load(target)
    assert saved.section("text") == {"engine": "poppler"}
    assert saved.section("ui") == {"progress": False}  # merged, not lost
    assert saved.default_command() == "markdown"


def test_an_existing_file_keeps_its_permissions(tmp_path):
    """The replacement is a rename, so without care the file would inherit the
    temporary file's mode instead of its own."""
    target = write(tmp_path / "rp-pdf.toml", ORIGINAL)
    target.chmod(0o640)
    config.save_command_options(target, "text", {"engine": "poppler"})
    assert target.stat().st_mode & 0o777 == 0o640


def test_a_new_file_is_readable_by_the_usual_umask(tmp_path):
    """`tempfile.mkstemp` would force 0600 and make a shared project config
    unreadable to a teammate; a plain create respects the umask instead."""
    target = tmp_path / "rp-pdf.toml"
    config.save_command_options(target, "text", {"engine": "poppler"})
    mode = target.stat().st_mode & 0o777
    assert mode & 0o400  # owner can read
    assert mode == 0o666 & ~_current_umask()


def _current_umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def test_a_failed_save_is_a_clean_cli_error_and_keeps_the_old_file(text_pdf, tmp_path):
    """End to end. A directory standing where the config should be is the
    reachable version of "the write failed": the run reports the suite's
    envelope, and the file that was already there is untouched."""
    nested = tmp_path / "cfg"
    nested.mkdir()
    target = write(nested / "rp-pdf.toml", ORIGINAL)
    before = target.read_bytes()
    # Point --save-config at the *directory*: open() cannot write to it.
    result = run_cli("text", text_pdf, "--engine", "poppler", "--save-config", nested, cwd=tmp_path)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert target.read_bytes() == before
