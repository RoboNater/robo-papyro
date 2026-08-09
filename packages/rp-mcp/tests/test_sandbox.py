"""The path allowlist, tested against the guarantees its docstring makes.

Every claim in `rp_mcp.sandbox`'s module docstring has an assertion here — the
symlink case especially, because a lexical containment check passes every other
test in this file while leaving the hole the sandbox exists to close.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rp_mcp.errors import (
    NoRootsError,
    OutputExistsError,
    PathNotAllowedError,
    WritesNotEnabledError,
)
from rp_mcp.sandbox import ROOTS_ENV, WRITE_ROOT_ENV, Sandbox


class TestConstruction:
    def test_roots_are_resolved_and_deduplicated(self, docs: Path):
        sandbox = Sandbox([docs, docs / ".", docs])
        assert sandbox.roots == (docs.resolve(),)

    def test_a_symlinked_root_is_recorded_as_its_target(self, tmp_path: Path, docs: Path):
        link = tmp_path / "link-to-docs"
        link.symlink_to(docs)
        assert Sandbox([link]).roots == (docs.resolve(),)

    def test_no_roots_is_refused_rather_than_producing_a_useless_server(self):
        with pytest.raises(NoRootsError):
            Sandbox([])

    def test_the_write_root_is_also_readable(self, docs: Path, outbox: Path):
        """The docstring's claim: an agent can read back what it just wrote."""
        sandbox = Sandbox([docs], write_root=outbox)
        assert outbox.resolve() in sandbox.roots
        assert sandbox.resolve_input(outbox / "made.docx") == outbox.resolve() / "made.docx"

    def test_a_read_only_sandbox_says_so(self, docs: Path):
        assert Sandbox([docs]).writable is False
        assert Sandbox([docs]).info().writable is False

    def test_info_reports_the_roots_and_the_write_root(self, docs: Path, outbox: Path):
        info = Sandbox([docs], write_root=outbox).info()
        assert info.roots == [docs.resolve(), outbox.resolve()]
        assert info.write_root == outbox.resolve()
        assert info.writable is True


class TestFromSettings:
    def test_explicit_roots_win_over_the_environment(
        self, docs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ROOTS_ENV, str(tmp_path))
        assert Sandbox.from_settings(roots=[docs]).roots == (docs.resolve(),)

    def test_the_environment_is_read_when_no_roots_are_passed(
        self, docs: Path, outbox: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ROOTS_ENV, f"{docs}{os.pathsep}{outbox}")
        assert Sandbox.from_settings().roots == (docs.resolve(), outbox.resolve())

    def test_empty_entries_in_the_environment_are_dropped(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """`RP_MCP_ROOTS=":/docs:"` is one root, not three."""
        monkeypatch.setenv(ROOTS_ENV, f"{os.pathsep}{docs}{os.pathsep}")
        assert Sandbox.from_settings().roots == (docs.resolve(),)

    def test_an_empty_variable_falls_through_to_the_working_directory(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(ROOTS_ENV, "")
        monkeypatch.chdir(docs)
        assert Sandbox.from_settings().roots == (docs.resolve(),)

    def test_the_working_directory_is_the_last_resort(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(docs)
        assert Sandbox.from_settings().roots == (docs.resolve(),)

    def test_the_write_root_comes_from_the_environment_too(
        self, docs: Path, outbox: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(WRITE_ROOT_ENV, str(outbox))
        assert Sandbox.from_settings(roots=[docs]).write_root == outbox.resolve()

    def test_no_write_root_anywhere_means_read_only(
        self, docs: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(WRITE_ROOT_ENV, "")
        assert Sandbox.from_settings(roots=[docs]).writable is False


class TestResolveInput:
    def test_a_relative_path_is_taken_against_the_first_root(self, docs: Path, outbox: Path):
        sandbox = Sandbox([docs, outbox])
        assert sandbox.resolve_input("report.pdf") == docs.resolve() / "report.pdf"

    def test_an_absolute_path_under_any_root_is_allowed(self, docs: Path, outbox: Path):
        sandbox = Sandbox([docs, outbox])
        assert sandbox.resolve_input(outbox / "made.pptx") == outbox.resolve() / "made.pptx"

    def test_dot_dot_cannot_climb_out(self, docs: Path, outside: Path):
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs]).resolve_input(f"../outside/{outside.name}")

    def test_a_symlink_pointing_out_of_a_root_is_refused(self, docs: Path, outside: Path):
        """The claim containment is checked on the *real* path, not the spelled one.

        A lexical check — `str(path).startswith(root)` or an unresolved
        `is_relative_to` — passes every other test in this class and lets this
        one straight through to the file the server was never given.
        """
        (docs / "shortcut.docx").symlink_to(outside)
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs]).resolve_input(docs / "shortcut.docx")

    def test_a_missing_file_inside_a_root_is_not_the_sandbox_s_error(self, docs: Path):
        """Existence is the leaf's business — see the docstring's oracle argument."""
        assert Sandbox([docs]).resolve_input("absent.pdf") == docs.resolve() / "absent.pdf"

    def test_a_missing_file_outside_every_root_is_still_refused(self, docs: Path, elsewhere: str):
        """The same refusal whether or not the file is there, so nothing leaks."""
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs]).resolve_input(elsewhere)

    def test_a_null_byte_is_a_refusal_rather_than_a_traceback(self, docs: Path):
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs]).resolve_input("report\0.pdf")

    def test_a_root_itself_resolves(self, docs: Path):
        assert Sandbox([docs]).resolve_input(docs) == docs.resolve()

    def test_the_message_names_the_roots_that_were_allowed(self, docs: Path, elsewhere: str):
        with pytest.raises(PathNotAllowedError, match=str(docs.resolve())):
            Sandbox([docs]).resolve_input(elsewhere)

    def test_the_refusal_never_names_a_symlink_s_target(self, docs: Path, outside: Path):
        """Reported in review: the message interpolated the *resolved* path.

        Containment must be judged on the resolved path, but naming it in the
        error hands the caller a location they never asked about — and one they
        may have had no way to learn. The message may only echo the spelling
        they sent.
        """
        (docs / "shortcut.docx").symlink_to(outside)
        with pytest.raises(PathNotAllowedError) as caught:
            Sandbox([docs]).resolve_input("shortcut.docx")
        message = str(caught.value)
        assert str(outside) not in message
        assert outside.name not in message
        assert "shortcut.docx" in message

    def test_outside_paths_are_refused_the_same_way_however_they_resolve(
        self, docs: Path, outside: Path, elsewhere: str
    ):
        """The three cases §3 of docs/security-mcp.md says must not be tellable
        apart: a symlink that leaves a root, a path that is outside and exists,
        and one that is outside and does not.

        Each error may name only what the caller supplied, so the wording
        carries no information about what is on the disk.
        """
        sandbox = Sandbox([docs])
        (docs / "shortcut.docx").symlink_to(outside)
        spellings = {
            "symlink out": "shortcut.docx",
            "outside, present": str(outside),
            "outside, absent": elsewhere,
        }
        messages = {}
        for label, spelling in spellings.items():
            with pytest.raises(PathNotAllowedError) as caught:
                sandbox.resolve_input(spelling)
            messages[label] = str(caught.value)

        for label, spelling in spellings.items():
            assert repr(spelling) in messages[label], label
        assert str(outside) not in messages["symlink out"]
        # Strip the caller's own spelling and the three must be word-for-word equal.
        skeletons = {
            label: messages[label].replace(repr(spelling), "<path>")
            for label, spelling in spellings.items()
        }
        assert len(set(skeletons.values())) == 1, skeletons


class TestResolveOutput:
    def test_a_read_only_sandbox_refuses_every_write(self, docs: Path):
        with pytest.raises(WritesNotEnabledError):
            Sandbox([docs]).resolve_output("made.docx")

    def test_a_relative_path_is_taken_against_the_write_root(self, docs: Path, outbox: Path):
        sandbox = Sandbox([docs], write_root=outbox)
        assert sandbox.resolve_output("made.docx") == outbox.resolve() / "made.docx"

    def test_a_path_outside_the_write_root_is_refused_even_when_readable(
        self, docs: Path, outbox: Path
    ):
        """A readable root is not a writable one; the two grants stay separate."""
        sandbox = Sandbox([docs], write_root=outbox)
        with pytest.raises(PathNotAllowedError):
            sandbox.resolve_output(docs / "made.docx")

    def test_an_existing_file_is_never_overwritten(self, docs: Path, outbox: Path):
        (outbox / "taken.docx").write_text("existing", encoding="utf-8")
        with pytest.raises(OutputExistsError):
            Sandbox([docs], write_root=outbox).resolve_output("taken.docx")

    def test_an_existing_directory_is_not_a_usable_output(self, docs: Path, outbox: Path):
        (outbox / "sub").mkdir()
        with pytest.raises(OutputExistsError):
            Sandbox([docs], write_root=outbox).resolve_output("sub")

    def test_a_dangling_symlink_still_counts_as_taken(self, docs: Path, outbox: Path):
        """`exists()` is false for a broken link, and writing through one escapes."""
        (outbox / "link.docx").symlink_to(outbox / "never-created.docx")
        with pytest.raises(OutputExistsError):
            Sandbox([docs], write_root=outbox).resolve_output("link.docx")

    def test_parent_directories_are_created(self, docs: Path, outbox: Path):
        target = Sandbox([docs], write_root=outbox).resolve_output("a/b/made.docx")
        assert target.parent.is_dir()
        assert target == outbox.resolve() / "a" / "b" / "made.docx"

    def test_a_symlink_out_of_the_write_root_is_refused(
        self, docs: Path, outbox: Path, tmp_path: Path
    ):
        escape = tmp_path / "escape"
        escape.mkdir()
        (outbox / "sideways").symlink_to(escape)
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs], write_root=outbox).resolve_output("sideways/made.docx")


class TestResolveOutputDir:
    def test_a_read_only_sandbox_refuses(self, docs: Path):
        with pytest.raises(WritesNotEnabledError):
            Sandbox([docs]).resolve_output_dir("images")

    def test_a_missing_directory_is_created(self, docs: Path, outbox: Path):
        target = Sandbox([docs], write_root=outbox).resolve_output_dir("images")
        assert target.is_dir()

    def test_an_existing_directory_is_the_destination_not_a_conflict(
        self, docs: Path, outbox: Path
    ):
        (outbox / "images").mkdir()
        assert Sandbox([docs], write_root=outbox).resolve_output_dir("images").is_dir()

    def test_an_existing_file_is_refused(self, docs: Path, outbox: Path):
        (outbox / "images").write_text("not a directory", encoding="utf-8")
        with pytest.raises(OutputExistsError):
            Sandbox([docs], write_root=outbox).resolve_output_dir("images")

    def test_outside_the_write_root_is_refused(self, docs: Path, outbox: Path):
        with pytest.raises(PathNotAllowedError):
            Sandbox([docs], write_root=outbox).resolve_output_dir(docs / "images")
