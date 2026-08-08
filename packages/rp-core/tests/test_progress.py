"""Progress reporting: what it writes, where, and — mostly — when it doesn't.

The reporter is driven with an explicit clock and ``background=False`` so the
ticking thread never makes a test depend on wall time. One test does start the
thread, because "the elapsed clock advances while the work is blocked" is the
whole feature and a test that stubs out the thread would not check it.
"""

from __future__ import annotations

import io
import threading

import pytest

from rp_core import progress as progress_module
from rp_core.progress import NULL, Progress, StderrProgress, is_interactive, reporter


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


class Stream(io.StringIO):
    """A StringIO with an encoding, which the reporter reads to decide whether
    it may use the Unicode spinner. (``encoding`` is read-only on StringIO
    itself, so it has to be a class attribute here.)"""

    encoding = "utf-8"


class AsciiStream(io.StringIO):
    encoding = "ascii"


def rendered(text: str) -> list[str]:
    """What a terminal would end up showing, with carriage returns applied.

    The raw stream is full of `\\r` and blanking spaces; asserting on it tests
    the mechanism rather than the result. This applies overwrite-from-column-0
    semantics so a test can say what the user sees.
    """
    lines = []
    for raw in text.split("\n"):
        current = ""
        for chunk in raw.split("\r"):
            current = chunk + current[len(chunk) :]
        lines.append(current.rstrip())
    return lines


def build(*, tty: bool, clock: FakeClock | None = None, **kwargs) -> tuple[StderrProgress, Stream]:
    stream = Stream()
    return (
        StderrProgress(
            stream,
            tty=tty,
            background=False,
            clock=clock or FakeClock(),
            **kwargs,
        ),
        stream,
    )


class TestNullProgress:
    """The default. Every library function gets this unless a CLI says otherwise,
    so its silence is a compatibility property, not a detail."""

    def test_writes_nothing(self, capsys):
        with NULL.step("Doing something", total=3) as step:
            step.advance()
            step.advance(2)
            step.set_total(5)
        NULL.close()
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", "")

    def test_reports_itself_disabled(self):
        assert NULL.enabled is False
        assert Progress().enabled is False

    def test_yields_a_step_that_accepts_the_whole_interface(self):
        """A no-op that raises on a legitimate call would make the argument
        unsafe to thread through core code, which is the point of it existing."""
        with NULL.step("x") as step:
            assert step.advance() is None
            assert step.set_total(None) is None

    def test_reporter_returns_the_shared_null_when_disabled(self):
        assert reporter(False) is NULL
        assert isinstance(reporter(True, stream=Stream()), StderrProgress)


class TestTerminalOutput:
    def test_repaints_one_line_and_leaves_a_summary(self):
        clock = FakeClock()
        rp, stream = build(tty=True, clock=clock)
        with rp.step("AI review", total=3) as step:
            for _ in range(3):
                clock.tick(1)
                step.advance()
        rp.close()
        text = stream.getvalue()
        assert "AI review 3/3" in text
        assert "✔" in text
        # In-place rewriting, and exactly one line left behind.
        assert "\r" in text
        assert text.count("\n") == 1

    def test_elapsed_time_is_reported(self):
        clock = FakeClock()
        rp, stream = build(tty=True, clock=clock)
        with rp.step("Slow thing"):
            clock.tick(75)
        rp.close()
        assert "[1m15s]" in stream.getvalue()

    def test_an_indeterminate_step_shows_no_count(self):
        rp, stream = build(tty=True)
        with rp.step("Converting with LibreOffice"):
            pass
        rp.close()
        final = stream.getvalue().rsplit("\r", 1)[-1]
        assert final.startswith("✔ Converting with LibreOffice [")
        assert "/" not in final

    def test_a_failed_step_is_marked_and_the_error_propagates(self):
        rp, stream = build(tty=True)
        with pytest.raises(ValueError):
            with rp.step("Doomed", total=2) as step:
                step.advance()
                raise ValueError("boom")
        rp.close()
        text = stream.getvalue()
        assert "✖ Doomed 1/2" in text
        # The half-painted line is cleared first, so the marker is not appended
        # to a stale spinner frame.
        assert text.rstrip().endswith("]")

    def test_close_clears_an_unfinished_line(self):
        """close() runs from `job`'s finally, including when the command is
        about to print an error: nothing may be left on the current line."""
        rp, stream = build(tty=True)
        cm = rp.step("Interrupted", total=10)
        cm.__enter__()
        rp.close()
        assert stream.getvalue().endswith("\r")

    def test_falls_back_to_ascii_when_the_encoding_cannot_take_unicode(self):
        stream = AsciiStream()
        rp = StderrProgress(stream, tty=True, background=False, clock=FakeClock())
        with rp.step("Plain", total=1) as step:
            step.advance()
        rp.close()
        text = stream.getvalue()
        assert "+ Plain 1/1" in text
        assert "✔" not in text and "⠋" not in text


class TestNonTerminalOutput:
    """A redirected stream cannot be rewritten, so each line stands alone. This
    is the shape a CI log or a `2> run.log` gets."""

    def test_one_line_per_boundary_no_carriage_returns(self):
        clock = FakeClock()
        rp, stream = build(tty=False, clock=clock)
        with rp.step("Rendering pages", total=2) as step:
            step.advance(2)
            clock.tick(3)
        rp.close()
        lines = stream.getvalue().splitlines()
        assert lines == ["Rendering pages: started (2)", "Rendering pages: done 2/2 [3s]"]
        assert "\r" not in stream.getvalue()

    def test_heartbeat_reports_liveness_between_boundaries(self):
        clock = FakeClock()
        rp, stream = build(tty=False, clock=clock, heartbeat=15.0)
        with rp.step("Extracting text", total=100) as step:
            step.advance(7)
            clock.tick(5)
            rp._tick()  # too early: nothing yet
            clock.tick(20)
            rp._tick()
        rp.close()
        lines = stream.getvalue().splitlines()
        assert lines[1] == "Extracting text: still working 7/100 [25s]"
        assert len(lines) == 3

    def test_failure_says_so(self):
        rp, stream = build(tty=False)
        with pytest.raises(RuntimeError):
            with rp.step("Doomed"):
                raise RuntimeError("boom")
        rp.close()
        assert "Doomed: failed" in stream.getvalue()


class TestConcurrency:
    def test_advance_is_safe_from_many_threads(self):
        """The AI pass advances from a ThreadPoolExecutor with --jobs workers;
        a lost update would make the count disagree with the work done."""
        rp, stream = build(tty=True)
        with rp.step("Parallel", total=200) as step:
            threads = [
                threading.Thread(target=lambda: [step.advance() for _ in range(50)])
                for _ in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        rp.close()
        assert "Parallel 200/200" in stream.getvalue()

    def test_the_clock_advances_while_the_caller_is_blocked(self):
        """The feature in one test: the reporter repaints from its own thread,
        so a step that makes no progress at all still visibly ticks. Without
        this, a stuck network read and a finished job look identical."""
        stream = Stream()
        rp = StderrProgress(stream, tty=True, interval=0.01, heartbeat=0.02, background=True)
        painted = threading.Event()
        with rp.step("Blocked on the network"):
            for _ in range(200):  # ~2s worst case; typically a few ms
                if stream.getvalue().count("\r") > 2:
                    painted.set()
                    break
                threading.Event().wait(0.01)
        rp.close()
        assert painted.is_set(), "the ticking thread never repainted"

    def test_close_stops_the_thread(self):
        before = threading.active_count()
        rp = StderrProgress(Stream(), tty=True, interval=0.01)
        with rp.step("Something"):
            pass
        rp.close()
        # join() is inside close(), so the thread is gone by the time it returns.
        assert threading.active_count() == before


class TestNesting:
    def test_the_inner_step_owns_the_display_and_the_outer_resumes(self):
        rp, stream = build(tty=True)
        with rp.step("Outer", total=2) as outer:
            outer.advance()
            with rp.step("Inner", total=1) as inner:
                inner.advance()
        rp.close()
        text = stream.getvalue()
        assert "✔ Inner 1/1" in text
        assert text.index("✔ Inner") < text.index("✔ Outer")


class TestIsInteractive:
    def test_plain_stream_is_not_a_terminal(self):
        assert is_interactive(io.StringIO()) is False

    def test_a_closed_stream_is_not_a_terminal(self):
        """isatty() on a closed file raises; a progress line is never worth an
        exception in a command that was otherwise going to succeed."""

        class Closed:
            def isatty(self):
                raise ValueError("I/O operation on closed file")

        assert is_interactive(Closed()) is False

    def test_a_terminal_is_detected(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        assert is_interactive(Tty()) is True


class TestWriteFailures:
    def test_a_broken_stream_does_not_break_the_job(self):
        """Progress is decoration. If stderr goes away mid-run (a closed pipe),
        the extraction it was reporting on must still finish."""

        class Broken(io.StringIO):
            encoding = "utf-8"

            def write(self, text):
                raise OSError("broken pipe")

        rp = StderrProgress(Broken(), tty=True, background=False, clock=FakeClock())
        with rp.step("Still fine", total=1) as step:
            step.advance()
        rp.close()  # no exception


def test_module_constants_are_sane():
    """The tick has to be fast enough to read as motion and slow enough not to
    flood a stream from a wide --jobs fan-out."""
    assert 0.05 <= progress_module.TICK <= 1.0
    assert progress_module.HEARTBEAT >= 5.0


class TestLivenessBeforeTheFirstStep:
    """The gap this closes: a job hung *opening* its file, before any counted
    work exists. A reporter that only wakes up on the first `step()` reports
    nothing at all for exactly the failure it was built to make visible."""

    def test_message_does_not_land_on_top_of_the_painted_line(self):
        rp, stream = build(tty=True)
        with rp.step("Working", total=2) as step:
            step.advance()
            rp.message("Interpreting --pages using the PDF's page labels")
        rp.close()
        shown = rendered(stream.getvalue())
        notice = "Interpreting --pages using the PDF's page labels"
        # Asserted against what a terminal would *display*, not the raw bytes:
        # the notice gets a line to itself, with no spinner text trailing off
        # the end of it, and the step line is repainted underneath.
        assert notice in shown
        assert any(line.startswith("✔ Working 1/2") for line in shown)

    def test_the_null_reporter_still_delivers_a_message(self):
        """A notice is output the command chose to emit, not decoration: it has
        to appear whether or not progress is switched on."""
        import io as _io
        import sys

        captured, original = _io.StringIO(), sys.stderr
        sys.stderr = captured
        try:
            NULL.message("still said")
        finally:
            sys.stderr = original
        assert captured.getvalue() == "still said\n"
