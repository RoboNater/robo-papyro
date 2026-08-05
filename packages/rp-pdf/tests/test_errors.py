import subprocess
from pathlib import Path

import pytest

from rp_core.binaries import require_binary
from rp_core.errors import MissingDependencyError
from rp_pdf import PageSpecError, core


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.get_index(tmp_path / "nope.pdf")


def test_not_a_pdf(not_a_pdf):
    with pytest.raises(core.InvalidPdfError):
        core.get_index(not_a_pdf)


def test_encrypted_requires_password(encrypted_pdf):
    with pytest.raises(core.PasswordError, match="password"):
        core.get_index(encrypted_pdf)


def test_encrypted_wrong_password(encrypted_pdf):
    with pytest.raises(core.PasswordError):
        core.get_index(encrypted_pdf, password="wrong")


@pytest.mark.requires_poppler
def test_encrypted_correct_password(encrypted_pdf, encrypted_password):
    # default engine: the password must also reach the pdftotext subprocess
    result = core.get_text(encrypted_pdf, "1", password=encrypted_password)
    assert "Chapter One" in result[0].text


def test_encrypted_correct_password_pypdf(encrypted_pdf, encrypted_password):
    result = core.get_text(encrypted_pdf, "1", password=encrypted_password, engine="pypdf")
    assert "Chapter One" in result[0].text


def test_page_out_of_range(text_pdf):
    with pytest.raises(PageSpecError, match="1-3"):
        core.get_text(text_pdf, "9")


def test_bad_page_spec(text_pdf):
    with pytest.raises(PageSpecError):
        core.get_text(text_pdf, "one")


# --- exit codes (rp_core.errors, spec section 4.7) ---
#
# Before the rp-core extraction every CLI error exited 1. These assert the
# mapping that replaced it, which is the one behavior change the refactor made
# on purpose.


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["rp-pdf", *[str(a) for a in args]], capture_output=True, text=True, encoding="utf-8"
    )


def test_exit_code_input_error(text_pdf):
    """Bad page spec -> InputError -> 1."""
    result = _cli("text", text_pdf, "--pages", "99")
    assert result.returncode == 1


def test_exit_code_corrupt_file(not_a_pdf, cli_error):
    """Unreadable PDF -> CorruptFileError -> 3."""
    result = _cli("index", not_a_pdf)
    assert result.returncode == 3
    detail = cli_error(result)
    assert detail["type"] == "InvalidPdfError"
    assert detail["exit_code"] == 3


def test_exit_code_missing_dependency(text_pdf, tmp_path, cli_error):
    """Absent poppler -> MissingDependencyError -> 2. An empty --poppler-path
    directory stands in for an uninstalled poppler."""
    empty = tmp_path / "no-poppler"
    empty.mkdir()
    result = _cli("text", text_pdf, "--poppler-path", empty)
    assert result.returncode == 2
    detail = cli_error(result)
    assert detail["type"] == "PopplerNotFoundError"
    assert detail["exit_code"] == 2
    assert "poppler" in detail["message"]


def test_missing_dependency_carries_install_hint():
    with pytest.raises(MissingDependencyError) as excinfo:
        require_binary("definitely-not-a-real-binary")
    assert excinfo.value.exit_code == 2
    assert excinfo.value.binary == "definitely-not-a-real-binary"


def test_pdftotext_is_time_limited(text_pdf, monkeypatch):
    """Spec section 4.4: this call site was unbounded through Phase 0. The hang
    is mocked — no real one is needed to prove the limit is applied."""
    from rp_core import binaries
    from rp_core.errors import SubprocessTimeout

    monkeypatch.delenv(binaries.SUBPROCESS_TIMEOUT_ENV, raising=False)
    monkeypatch.setattr(binaries, "find_binary", lambda name, **kw: Path("/usr/bin/pdftotext"))
    seen: dict = {}

    def hang(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(SubprocessTimeout) as excinfo:
        core.get_text(text_pdf, "1")
    assert seen["timeout"] == binaries.DEFAULT_SUBPROCESS_TIMEOUT
    assert excinfo.value.exit_code == 3


def test_pdftotext_timeout_honors_the_environment(text_pdf, monkeypatch):
    from rp_core import binaries
    from rp_core.errors import SubprocessTimeout

    monkeypatch.setenv(binaries.SUBPROCESS_TIMEOUT_ENV, "5")
    monkeypatch.setattr(binaries, "find_binary", lambda name, **kw: Path("/usr/bin/pdftotext"))
    seen: dict = {}

    def hang(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(SubprocessTimeout):
        core.get_text(text_pdf, "1")
    assert seen["timeout"] == 5
