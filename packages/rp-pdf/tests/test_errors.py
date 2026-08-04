import json
import subprocess

import pytest
from conftest import ENCRYPTED_PASSWORD, requires_poppler
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


@requires_poppler
def test_encrypted_correct_password(encrypted_pdf):
    # default engine: the password must also reach the pdftotext subprocess
    result = core.get_text(encrypted_pdf, "1", password=ENCRYPTED_PASSWORD)
    assert "Chapter One" in result[0].text


def test_encrypted_correct_password_pypdf(encrypted_pdf):
    result = core.get_text(encrypted_pdf, "1", password=ENCRYPTED_PASSWORD, engine="pypdf")
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


def test_exit_code_corrupt_file(not_a_pdf):
    """Unreadable PDF -> CorruptFileError -> 3."""
    result = _cli("index", not_a_pdf)
    assert result.returncode == 3
    assert "error" in json.loads(result.stdout)


def test_exit_code_missing_dependency(text_pdf, tmp_path):
    """Absent poppler -> MissingDependencyError -> 2. An empty --poppler-path
    directory stands in for an uninstalled poppler."""
    empty = tmp_path / "no-poppler"
    empty.mkdir()
    result = _cli("text", text_pdf, "--poppler-path", empty)
    assert result.returncode == 2
    assert "poppler" in json.loads(result.stdout)["error"]


def test_missing_dependency_carries_install_hint():
    with pytest.raises(MissingDependencyError) as excinfo:
        require_binary("definitely-not-a-real-binary")
    assert excinfo.value.exit_code == 2
    assert excinfo.value.binary == "definitely-not-a-real-binary"
