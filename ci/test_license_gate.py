"""The license gate must actually fail on the things it claims to catch.

A gate nobody has watched fail is a gate that passes for the wrong reason.
"""

from __future__ import annotations

import license_gate
import pytest


def _lock(tmp_path, *names: str) -> None:
    body = "\n".join(f'[[package]]\nname = "{n}"\nversion = "1.0"' for n in names)
    (tmp_path / "uv.lock").write_text(body, encoding="utf-8")


def _allowlist(tmp_path, *names: str) -> None:
    (tmp_path / "ci").mkdir(exist_ok=True)
    body = "[direct]\n" + "\n".join(f'{n} = "MIT"' for n in names)
    (tmp_path / "ci" / "allowed-packages.toml").write_text(body, encoding="utf-8")


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Point the gate at a throwaway tree instead of the real repository."""
    (tmp_path / "packages").mkdir()
    monkeypatch.setattr(license_gate, "ROOT", tmp_path)
    monkeypatch.setattr(license_gate, "LOCKFILE", tmp_path / "uv.lock")
    monkeypatch.setattr(license_gate, "ALLOWLIST", tmp_path / "ci" / "allowed-packages.toml")
    return tmp_path


class TestNormalize:
    @pytest.mark.parametrize(
        "name", ["pdfminer-six", "pdfminer_six", "pdfminer.six", "PDFMiner-Six"]
    )
    def test_spelling_variants_collapse(self, name):
        assert license_gate.normalize(name) == "pdfminer.six"


class TestGate:
    def test_passes_when_everything_is_allowlisted(self, sandbox, capsys):
        _lock(sandbox, "pypdf", "typer")
        _allowlist(sandbox, "pypdf", "typer")
        assert license_gate.main() == 0
        assert "passed" in capsys.readouterr().out

    def test_fails_on_an_unreviewed_package(self, sandbox, capsys):
        _lock(sandbox, "pypdf", "mystery-lib")
        _allowlist(sandbox, "pypdf")
        assert license_gate.main() == 1
        err = capsys.readouterr().err
        assert "UNREVIEWED: mystery.lib" in err

    @pytest.mark.parametrize(
        ("package", "reason"),
        [
            ("docxtpl", "LGPL"),
            ("pymupdf", "AGPL"),
            ("pypandoc", "GPL"),
            ("aspose-words", "commercial"),
            ("Spire.Doc", "commercial"),
        ],
    )
    def test_fails_on_a_forbidden_package(self, sandbox, capsys, package, reason):
        _lock(sandbox, package)
        _allowlist(sandbox, package)  # even allowlisted, it must still fail
        assert license_gate.main() == 1
        assert "FORBIDDEN" in capsys.readouterr().err

    def test_forbidden_beats_the_allowlist(self, sandbox, capsys):
        """Someone allowlisting a blocker must not silence the gate."""
        _lock(sandbox, "pymupdf")
        _allowlist(sandbox, "pymupdf")
        assert license_gate.main() == 1
        assert "do not allowlist it" in capsys.readouterr().err

    def test_workspace_members_need_no_allowlist_entry(self, sandbox):
        (sandbox / "packages" / "rp-docx").mkdir(parents=True)
        (sandbox / "packages" / "rp-docx" / "pyproject.toml").write_text("", encoding="utf-8")
        _lock(sandbox, "rp-docx")
        _allowlist(sandbox)
        assert license_gate.main() == 0

    def test_missing_lockfile_is_an_error(self, sandbox, capsys):
        _allowlist(sandbox)
        assert license_gate.main() == 1
        assert "not found" in capsys.readouterr().err


class TestRealRepository:
    def test_the_actual_lockfile_passes(self, capsys):
        assert license_gate.main() == 0

    def test_the_spec_blockers_are_all_covered(self):
        """Every package docs/specs/robo-papyro-spec.md §7 names as forbidden."""
        for blocker in ("docxtpl", "pandoc", "pymupdf", "fitz", "aspose", "spire"):
            assert blocker in license_gate.FORBIDDEN
