"""Phase 3 step 1: the distribution resolves and its CLI is reachable.

Superseded piecemeal as later steps add real coverage (test_errors_xlsx.py,
test_cli_xlsx.py, ...); kept minimal and non-overlapping until then.
"""

from __future__ import annotations

import subprocess

import rp_xlsx
from rp_xlsx.cli import app


def test_package_imports():
    assert rp_xlsx.__version__ == "0.1.0"


def test_cli_app_exists():
    assert app.info.help.startswith("rp-xlsx")


def test_console_script_help():
    result = subprocess.run(["rp-xlsx", "--help"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    assert "rp-xlsx" in result.stdout


def test_umbrella_help():
    result = subprocess.run(
        ["rp", "xlsx", "--help"], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0
