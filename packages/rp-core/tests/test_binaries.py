"""Binary discovery and invocation.

The subprocess is always mocked: LibreOffice must not be a prerequisite for
running this suite. The soffice_convert tests target the three failure modes
that are silent in production — a shared profile directory, a zero exit code
with no output file, and a hang.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rp_core import binaries
from rp_core.errors import ConversionError, MissingDependencyError


def _completed(returncode: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["soffice"], returncode=returncode, stdout=b"",
                                       stderr=stderr)


class TestFindBinary:
    def test_finds_on_path(self):
        # python3 is guaranteed present wherever this suite runs.
        assert binaries.find_binary("python3") is not None

    def test_absent_returns_none(self):
        assert binaries.find_binary("definitely-not-a-real-binary") is None

    def test_explicit_search_path_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(binaries.POPPLER_PATH_ENV, "/nonexistent")
        fake = tmp_path / "pdftoppm"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        assert binaries.find_binary("pdftoppm", search_path=tmp_path) == fake

    def test_env_var_search_path(self, tmp_path, monkeypatch):
        fake = tmp_path / "pdftotext"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setenv(binaries.POPPLER_PATH_ENV, str(tmp_path))
        assert binaries.find_binary("pdftotext") == fake

    def test_unknown_binary_ignores_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv(binaries.POPPLER_PATH_ENV, str(tmp_path))
        assert binaries.find_binary("definitely-not-a-real-binary") is None


class TestRequireBinary:
    def test_returns_path_when_present(self):
        assert binaries.require_binary("python3").name.startswith("python3")

    def test_missing_raises_with_exit_code_2(self):
        with pytest.raises(MissingDependencyError) as excinfo:
            binaries.require_binary("definitely-not-a-real-binary")
        assert excinfo.value.exit_code == 2

    def test_missing_names_the_binary_and_hint(self):
        with pytest.raises(MissingDependencyError) as excinfo:
            binaries.require_binary("soffice", search_path="/nonexistent")
        error = excinfo.value
        assert error.binary == "soffice"
        assert "LibreOffice" in error.install_hint
        assert error.hint == error.install_hint

    def test_custom_install_hint(self):
        with pytest.raises(MissingDependencyError) as excinfo:
            binaries.require_binary("nope-not-real", install_hint="brew install nope")
        assert "brew install nope" in str(excinfo.value)

    def test_envelope_reports_exit_code(self):
        with pytest.raises(MissingDependencyError) as excinfo:
            binaries.require_binary("nope-not-real")
        envelope = excinfo.value.to_envelope()
        assert envelope.error.exit_code == 2
        assert envelope.error.type == "MissingDependencyError"


class TestRunBinary:
    def test_captures_output(self):
        proc = binaries.run_binary(Path("/bin/sh"), ["-c", "echo hello"], timeout=10)
        assert proc.returncode == 0
        assert proc.stdout.strip() == b"hello"

    def test_nonzero_exit_is_returned_not_raised(self):
        proc = binaries.run_binary(Path("/bin/sh"), ["-c", "exit 7"], timeout=10)
        assert proc.returncode == 7

    def test_timeout_raises_conversion_error(self):
        with pytest.raises(ConversionError, match="did not finish"):
            binaries.run_binary(Path("/bin/sh"), ["-c", "sleep 5"], timeout=1)

    def test_missing_executable_is_not_a_bare_oserror(self, tmp_path):
        """A raw FileNotFoundError from exec() must never reach the user."""
        with pytest.raises(MissingDependencyError):
            binaries.run_binary(tmp_path / "not-there", [], timeout=5)


class TestSofficeConvert:
    """soffice_convert's three guarantees, each mocked at the subprocess boundary."""

    def _patch(self, monkeypatch, tmp_path, *, writes_output=True, returncode=0, stderr=b""):
        """Stand in for LibreOffice; record the args it was invoked with."""
        calls: list[list[str]] = []

        def fake_run(path, args, *, timeout=120):
            calls.append(args)
            if writes_output:
                outdir = Path(args[args.index("--outdir") + 1])
                source = Path(args[-1])
                target = outdir / f"{source.stem}.{args[args.index('--convert-to') + 1]}"
                target.write_bytes(b"%PDF-1.4 fake\n")
            return _completed(returncode, stderr)

        monkeypatch.setattr(binaries, "run_binary", fake_run)
        monkeypatch.setattr(binaries, "require_binary", lambda name, **kw: Path("/usr/bin/soffice"))
        return calls

    @pytest.fixture()
    def source(self, tmp_path) -> Path:
        path = tmp_path / "letter.docx"
        path.write_bytes(b"PK\x03\x04fake docx")
        return path

    def test_returns_the_converted_file(self, monkeypatch, tmp_path, source):
        self._patch(monkeypatch, tmp_path)
        out = binaries.soffice_convert(source, "pdf", tmp_path / "out")
        assert out == tmp_path / "out" / "letter.pdf"
        assert out.is_file()

    def test_profile_is_unique_per_invocation(self, monkeypatch, tmp_path, source):
        """Parallel invocations sharing a UserInstallation collide silently and
        return success with no output file. Each call must get its own."""
        calls = self._patch(monkeypatch, tmp_path)
        binaries.soffice_convert(source, "pdf", tmp_path / "a")
        binaries.soffice_convert(source, "pdf", tmp_path / "b")
        profiles = [
            arg for call in calls for arg in call if arg.startswith("-env:UserInstallation=")
        ]
        assert len(profiles) == 2
        assert profiles[0] != profiles[1]
        assert all(p.startswith("-env:UserInstallation=file://") for p in profiles)
        assert all("robo-papyro-" in p for p in profiles)

    def test_profile_directory_is_removed(self, monkeypatch, tmp_path, source):
        calls = self._patch(monkeypatch, tmp_path)
        binaries.soffice_convert(source, "pdf", tmp_path / "out")
        profile_uri = next(a for a in calls[0] if a.startswith("-env:UserInstallation="))
        profile = Path(profile_uri.split("file://", 1)[1])
        assert not profile.exists()

    def test_headless_flags_always_passed(self, monkeypatch, tmp_path, source):
        calls = self._patch(monkeypatch, tmp_path)
        binaries.soffice_convert(source, "pdf", tmp_path / "out")
        for flag in ("--headless", "--norestore", "--invisible"):
            assert flag in calls[0]

    def test_zero_exit_without_output_is_an_error(self, monkeypatch, tmp_path, source):
        """A zero exit code is not evidence of success."""
        self._patch(monkeypatch, tmp_path, writes_output=False)
        with pytest.raises(ConversionError, match="was not written"):
            binaries.soffice_convert(source, "pdf", tmp_path / "out")

    def test_conversion_error_exit_code_is_3(self, monkeypatch, tmp_path, source):
        self._patch(monkeypatch, tmp_path, writes_output=False, returncode=1, stderr=b"boom")
        with pytest.raises(ConversionError) as excinfo:
            binaries.soffice_convert(source, "pdf", tmp_path / "out")
        assert excinfo.value.exit_code == 3
        assert "boom" in str(excinfo.value)

    def test_timeout_propagates(self, monkeypatch, tmp_path, source):
        """LibreOffice hangs indefinitely on some malformed inputs."""

        def hang(path, args, *, timeout=120):
            raise ConversionError(f"soffice did not finish within {timeout}s and was killed.")

        monkeypatch.setattr(binaries, "run_binary", hang)
        monkeypatch.setattr(binaries, "require_binary", lambda name, **kw: Path("/usr/bin/soffice"))
        with pytest.raises(ConversionError, match="did not finish within 30s"):
            binaries.soffice_convert(source, "pdf", tmp_path / "out", timeout=30)

    def test_profile_removed_even_when_conversion_fails(self, monkeypatch, tmp_path, source):
        captured: list[str] = []

        def fail(path, args, *, timeout=120):
            captured.extend(a for a in args if a.startswith("-env:UserInstallation="))
            raise ConversionError("boom")

        monkeypatch.setattr(binaries, "run_binary", fail)
        monkeypatch.setattr(binaries, "require_binary", lambda name, **kw: Path("/usr/bin/soffice"))
        with pytest.raises(ConversionError):
            binaries.soffice_convert(source, "pdf", tmp_path / "out")
        assert not Path(captured[0].split("file://", 1)[1]).exists()

    def test_qualified_filter_uses_extension_before_colon(self, monkeypatch, tmp_path, source):
        def fake_run(path, args, *, timeout=120):
            outdir = Path(args[args.index("--outdir") + 1])
            (outdir / "letter.pdf").write_bytes(b"%PDF")
            return _completed()

        monkeypatch.setattr(binaries, "run_binary", fake_run)
        monkeypatch.setattr(binaries, "require_binary", lambda name, **kw: Path("/usr/bin/soffice"))
        out = binaries.soffice_convert(source, "pdf:writer_pdf_Export", tmp_path / "out")
        assert out.name == "letter.pdf"

    def test_missing_soffice_raises_missing_dependency(self, tmp_path, source, monkeypatch):
        monkeypatch.setattr(binaries, "find_binary", lambda name, **kw: None)
        with pytest.raises(MissingDependencyError) as excinfo:
            binaries.soffice_convert(source, "pdf", tmp_path / "out")
        assert excinfo.value.exit_code == 2
