"""Discovery and invocation of the external binaries the suite can use.

Both binaries are optional and are only ever run as subprocesses — no linkage,
no license propagation (spec section 7). Every code path that needs one must go
through :func:`require_binary` so an absent binary produces a
:class:`~rp_core.errors.MissingDependencyError` carrying install instructions,
never a bare ``FileNotFoundError``.

| Binary | Provides | Search-path override |
|---|---|---|
| ``soffice`` | Office → PDF/ODT/HTML conversion | ``RP_SOFFICE_PATH`` |
| ``pdftoppm`` / ``pdftotext`` / ``pdfinfo`` | poppler rendering and text | ``RP_POPPLER_PATH`` |
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from rp_core.errors import ConversionError, MissingDependencyError

POPPLER_PATH_ENV = "RP_POPPLER_PATH"
SOFFICE_PATH_ENV = "RP_SOFFICE_PATH"

#: Environment variable naming a directory to search for each binary, when it is
#: not on PATH.
SEARCH_PATH_ENV: dict[str, str] = {
    "pdftoppm": POPPLER_PATH_ENV,
    "pdftotext": POPPLER_PATH_ENV,
    "pdfinfo": POPPLER_PATH_ENV,
    "soffice": SOFFICE_PATH_ENV,
}

POPPLER_INSTALL_HINT = (
    "Install poppler with 'apt install poppler-utils' (Linux), 'brew install "
    "poppler' (macOS), or 'winget install oschwartz10612.Poppler' (Windows); "
    f"alternatively set {POPPLER_PATH_ENV} to poppler's bin directory."
)

SOFFICE_INSTALL_HINT = (
    "Install LibreOffice from https://www.libreoffice.org/download (or 'apt "
    "install libreoffice' / 'brew install --cask libreoffice'); alternatively "
    f"set {SOFFICE_PATH_ENV} to the directory containing the soffice executable."
)

INSTALL_HINTS: dict[str, str] = {
    "pdftoppm": POPPLER_INSTALL_HINT,
    "pdftotext": POPPLER_INSTALL_HINT,
    "pdfinfo": POPPLER_INSTALL_HINT,
    "soffice": SOFFICE_INSTALL_HINT,
}


def find_binary(name: str, *, search_path: str | Path | None = None) -> Path | None:
    """Locate ``name`` on PATH, or in ``search_path`` / its environment override.

    Returns ``None`` when the binary is absent — callers that require it should
    use :func:`require_binary` instead.
    """
    env_var = SEARCH_PATH_ENV.get(name)
    search_path = search_path or (os.environ.get(env_var) if env_var else None) or None
    exe = shutil.which(name, path=str(search_path)) if search_path else shutil.which(name)
    return Path(exe) if exe is not None else None


def require_binary(
    name: str,
    *,
    search_path: str | Path | None = None,
    install_hint: str | None = None,
) -> Path:
    """Locate ``name`` or raise :class:`MissingDependencyError` (exit code 2)."""
    found = find_binary(name, search_path=search_path)
    if found is not None:
        return found
    hint = install_hint if install_hint is not None else INSTALL_HINTS.get(name, "")
    message = f"{name} is required but was not found on PATH."
    raise MissingDependencyError(
        f"{message} {hint}".strip(), binary=name, install_hint=hint
    )


def run_binary(
    path: Path,
    args: list[str],
    *,
    timeout: int | None = 120,
) -> subprocess.CompletedProcess:
    """Run ``path`` with ``args``, capturing output.

    Does not check the return code — callers decide what a nonzero exit means
    for them. ``timeout=None`` waits indefinitely; every new call site should
    pass a real timeout, since both LibreOffice and poppler can hang on
    malformed input.
    """
    try:
        return subprocess.run([str(path), *args], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"{Path(path).name} did not finish within {timeout}s and was killed."
        ) from exc
    except OSError as exc:
        # Never let a bare FileNotFoundError from exec() reach the user.
        raise MissingDependencyError(
            f"Could not run {path}: {exc}",
            binary=Path(path).name,
            install_hint=INSTALL_HINTS.get(Path(path).name, ""),
        ) from exc


def soffice_convert(
    source: Path,
    to: str,
    outdir: Path,
    *,
    timeout: int = 120,
    soffice: Path | None = None,
) -> Path:
    """Convert ``source`` to format ``to`` inside ``outdir`` using LibreOffice.

    ``to`` is a LibreOffice target filter such as ``"pdf"``, ``"odt"``, or a
    qualified one like ``"pdf:writer_pdf_Export"``; the output file takes the
    source's stem and the part of ``to`` before any colon as its extension.

    Three non-obvious guarantees, each protecting against a failure mode that is
    silent otherwise:

    * **Profile isolation.** Every invocation gets a private
      ``-env:UserInstallation`` directory, removed afterwards. Concurrent
      invocations sharing a profile collide, exit zero, and write no output —
      and agents parallelize.
    * **Output verification.** A zero exit code is not evidence of success.
      The expected file must exist, or this raises :class:`ConversionError`.
    * **Timeout.** LibreOffice hangs indefinitely on some malformed inputs.
    """
    exe = soffice if soffice is not None else require_binary("soffice")
    source = Path(source)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    profile = Path(tempfile.gettempdir()) / f"robo-papyro-{uuid4()}"
    try:
        proc = run_binary(
            exe,
            [
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless",
                "--norestore",
                "--invisible",
                "--convert-to",
                to,
                "--outdir",
                str(outdir),
                str(source),
            ],
            timeout=timeout,
        )
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    expected = outdir / f"{source.stem}.{to.split(':')[0]}"
    if not expected.is_file():
        detail = proc.stderr.decode("utf-8", "replace").strip() or (
            f"exit code {proc.returncode}"
        )
        raise ConversionError(
            f"LibreOffice reported no error converting {source.name} to {to}, but "
            f"{expected.name} was not written ({detail})."
        )
    return expected
