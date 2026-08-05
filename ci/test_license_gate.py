"""The license gate must actually fail on the things it claims to catch.

A gate nobody has watched fail is a gate that passes for the wrong reason.
"""

from __future__ import annotations

import license_gate
import pytest


def _lock(tmp_path, *names: str, deps: dict | None = None, extras: dict | None = None) -> None:
    """A minimal uv.lock. ``deps`` and ``extras`` shape the dependency graph the
    base-install-path walk has to get right."""
    deps = deps or {}
    extras = extras or {}
    blocks = []
    for name in names:
        block = ["[[package]]", f'name = "{name}"', 'version = "1.0"']
        if deps.get(name):
            block.append("dependencies = [")
            block += [f'    {{ name = "{d}" }},' for d in deps[name]]
            block.append("]")
        if extras.get(name):
            block.append("[package.optional-dependencies]")
            for extra, members in extras[name].items():
                block.append(f"{extra} = [")
                block += [f'    {{ name = "{m}" }},' for m in members]
                block.append("]")
        blocks.append("\n".join(block))
    (tmp_path / "uv.lock").write_text("\n\n".join(blocks), encoding="utf-8")


def _allowlist(
    tmp_path, *names: str, licenses: dict | None = None, tags: dict | None = None
) -> None:
    licenses = licenses or {}
    tags = tags or {}
    lines = ["[direct]"]
    for name in names:
        license_ = licenses.get(name, "MIT")
        if name in tags:
            lines.append(f'{name} = {{ license = "{license_}", tag = "{tags[name]}" }}')
        else:
            lines.append(f'{name} = "{license_}"')
    (tmp_path / "ci").mkdir(exist_ok=True)
    (tmp_path / "ci" / "allowed-packages.toml").write_text("\n".join(lines), encoding="utf-8")


def _member(tmp_path, name: str) -> None:
    """Make ``name`` a workspace member of the sandbox."""
    (tmp_path / "packages" / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "packages" / name / "pyproject.toml").write_text("", encoding="utf-8")


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
        _member(sandbox, "rp-docx")
        _lock(sandbox, "rp-docx")
        _allowlist(sandbox)
        assert license_gate.main() == 0

    def test_missing_lockfile_is_an_error(self, sandbox, capsys):
        _allowlist(sandbox)
        assert license_gate.main() == 1
        assert "not found" in capsys.readouterr().err


class TestWeakCopyleftDetection:
    @pytest.mark.parametrize(
        "expression", ["MPL-2.0", "MPL-2.0 AND MIT", "MIT OR MPL-2.0", "EPL-2.0", "CDDL-1.1"]
    )
    def test_recognized(self, expression):
        assert license_gate.weak_copyleft_in(expression)

    @pytest.mark.parametrize(
        "expression",
        ["MIT", "BSD-3-Clause", "Apache-2.0 OR BSD-2-Clause", "MIT-CMU", "PSF-2.0", "ISC"],
    )
    def test_permissive_expressions_are_clean(self, expression):
        assert license_gate.weak_copyleft_in(expression) == []

    def test_an_or_expression_still_counts(self):
        """A permissive alternative may make it fine, but that is a human's call
        to record — not something the gate should decide silently."""
        assert license_gate.weak_copyleft_in("MIT OR MPL-2.0") == ["MPL-2.0"]


class TestBaseInstallPath:
    """Spec §7.1: runtime dependencies of the published distributions, resolved
    with no extras and excluding the dev group."""

    def test_follows_runtime_dependencies_transitively(self, sandbox):
        _member(sandbox, "rp-pdf")
        _lock(
            sandbox,
            "rp-pdf",
            "typer",
            "rich",
            deps={"rp-pdf": ["typer"], "typer": ["rich"]},
        )
        base = license_gate.base_install_path(license_gate.locked())
        assert base == {"rp.pdf", "typer", "rich"}

    def test_extras_are_excluded(self, sandbox):
        _member(sandbox, "rp-pdf")
        _lock(
            sandbox,
            "rp-pdf",
            "typer",
            "openai",
            deps={"rp-pdf": ["typer"]},
            extras={"rp-pdf": {"ai": ["openai"]}},
        )
        assert "openai" not in license_gate.base_install_path(license_gate.locked())

    def test_a_package_reachable_both_ways_is_in_the_base_path(self, sandbox):
        """Being available through an extra does not remove it from the base
        path if a runtime dependency also reaches it."""
        _member(sandbox, "rp-pdf")
        _lock(
            sandbox,
            "rp-pdf",
            "typer",
            deps={"rp-pdf": ["typer"]},
            extras={"rp-pdf": {"ai": ["typer"]}},
        )
        assert "typer" in license_gate.base_install_path(license_gate.locked())

    def test_unlocked_names_do_not_crash_the_walk(self, sandbox):
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", deps={"rp-pdf": ["not-in-the-lock"]})
        assert license_gate.base_install_path(license_gate.locked()) == {
            "rp.pdf",
            "not.in.the.lock",
        }


class TestBasePathIsClean:
    def test_weak_copyleft_in_the_base_path_fails(self, sandbox, capsys):
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", "certifi", deps={"rp-pdf": ["certifi"]})
        _allowlist(sandbox, "certifi", licenses={"certifi": "MPL-2.0"})
        assert license_gate.main() == 1
        err = capsys.readouterr().err
        assert "BASE PATH: certifi" in err
        assert "allowlisting does not make this pass" in err

    def test_weak_copyleft_behind_an_extra_passes(self, sandbox):
        _member(sandbox, "rp-pdf")
        _lock(
            sandbox,
            "rp-pdf",
            "openai",
            "certifi",
            deps={"openai": ["certifi"]},
            extras={"rp-pdf": {"ai": ["openai"]}},
        )
        _allowlist(
            sandbox,
            "openai",
            "certifi",
            licenses={"openai": "Apache-2.0", "certifi": "MPL-2.0"},
            tags={"certifi": "extra:ai"},
        )
        assert license_gate.main() == 0

    def test_permissive_packages_in_the_base_path_pass(self, sandbox):
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", "typer", deps={"rp-pdf": ["typer"]})
        _allowlist(sandbox, "typer")
        assert license_gate.main() == 0


class TestTagsAreTrue:
    def test_a_tag_that_has_gone_stale_fails(self, sandbox, capsys):
        """The check that catches the graph moving under a claim: certifi is
        tagged extra-only but a runtime dependency now reaches it."""
        _member(sandbox, "rp-pdf")
        _lock(
            sandbox,
            "rp-pdf",
            "certifi",
            deps={"rp-pdf": ["certifi"]},
            extras={"rp-pdf": {"ai": []}},
        )
        _allowlist(sandbox, "certifi", tags={"certifi": "extra:ai"})
        assert license_gate.main() == 1
        assert "STALE TAG: certifi" in capsys.readouterr().err

    def test_a_stale_tag_fails_even_when_the_license_is_permissive(self, sandbox, capsys):
        """Independent of the base-path check — an MIT package with a false tag
        is still a false claim about the graph."""
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", "tqdm", deps={"rp-pdf": ["tqdm"]}, extras={"rp-pdf": {"ai": []}})
        _allowlist(sandbox, "tqdm", licenses={"tqdm": "MIT"}, tags={"tqdm": "extra:ai"})
        assert license_gate.main() == 1
        err = capsys.readouterr().err
        assert "STALE TAG: tqdm" in err
        assert "BASE PATH" not in err

    def test_a_malformed_tag_fails(self, sandbox, capsys):
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", "certifi", extras={"rp-pdf": {"ai": ["certifi"]}})
        _allowlist(sandbox, "certifi", tags={"certifi": "ai"})
        assert license_gate.main() == 1
        assert "is not of the form" in capsys.readouterr().err

    def test_a_tag_naming_an_undeclared_extra_fails(self, sandbox, capsys):
        _member(sandbox, "rp-pdf")
        _lock(sandbox, "rp-pdf", "certifi", extras={"rp-pdf": {"ai": ["certifi"]}})
        _allowlist(sandbox, "certifi", tags={"certifi": "extra:vlm"})
        assert license_gate.main() == 1
        assert "which no distribution declares" in capsys.readouterr().err


class TestRealRepository:
    def test_the_actual_lockfile_passes(self, capsys):
        assert license_gate.main() == 0

    def test_the_spec_blockers_are_all_covered(self):
        """Every package docs/specs/robo-papyro-spec.md §7 names as forbidden."""
        for blocker in ("docxtpl", "pandoc", "pymupdf", "fitz", "aspose", "spire"):
            assert blocker in license_gate.FORBIDDEN

    def test_the_two_weak_copyleft_packages_are_outside_the_base_path(self):
        """§7.1's whole argument rests on this being true, so it is checked."""
        base = license_gate.base_install_path(license_gate.locked())
        assert "certifi" not in base
        assert "tqdm" not in base

    def test_every_weak_copyleft_entry_is_tagged(self):
        """An untagged weak-copyleft entry would escape the tags-are-true check."""
        untagged = sorted(
            name
            for name, entry in license_gate.allowed().items()
            if license_gate.weak_copyleft_in(entry["license"]) and not entry.get("tag")
        )
        assert untagged == []
