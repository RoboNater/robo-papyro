"""Capability reporting. Never requires the binaries it reports on."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rp_core import doctor
from rp_core.models import Capability


def test_available_binary_is_reported():
    result = doctor.capability("python3")
    assert result.available is True
    assert result.path is not None
    assert result.version is not None  # python3 --version always prints one


def test_absent_binary_is_reported_with_hint(monkeypatch):
    monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: None)
    result = doctor.capability("soffice")
    assert result.available is False
    assert result.path is None
    assert result.version is None
    assert "LibreOffice" in result.install_hint


def test_version_parsed_from_stderr(monkeypatch):
    """poppler tools print their version banner on stderr, not stdout."""
    monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: Path("/usr/bin/pdftoppm"))
    monkeypatch.setattr(
        doctor,
        "run_binary",
        lambda path, args, **kw: subprocess.CompletedProcess(
            args=args, returncode=0, stdout=b"", stderr=b"pdftoppm version 24.02.0\n"
        ),
    )
    assert doctor.capability("pdftoppm").version == "24.02.0"


def test_present_but_unversionable_binary_is_still_available(monkeypatch):
    """A binary that will not report a version is still a usable binary."""
    monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: Path("/usr/bin/soffice"))
    monkeypatch.setattr(
        doctor, "run_binary", lambda path, args, **kw: (_ for _ in ()).throw(OSError("nope"))
    )
    result = doctor.capability("soffice")
    assert result.available is True
    assert result.version is None


def test_report_preserves_order(monkeypatch):
    monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: None)
    names = [c.name for c in doctor.report("soffice", "pdftoppm", "pdftotext")]
    assert names == ["soffice", "pdftoppm", "pdftotext"]


def test_report_returns_capabilities(monkeypatch):
    monkeypatch.setattr(doctor, "find_binary", lambda name, **kw: None)
    assert all(isinstance(c, Capability) for c in doctor.report("soffice"))
