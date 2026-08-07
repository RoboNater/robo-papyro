"""Progress reporting for long-running work.

The problem this solves is a human's, not an agent's: a job that prints nothing
until it finishes is indistinguishable from one that is stuck on a file server
that stopped answering. A minute of silence during ``rp-pdf markdown --ai`` on a
200-page document is normal; a minute of silence because the read hung is not,
and there is currently no way to tell them apart.

**Nothing here is on by default.** :data:`NULL` — a :class:`Progress` whose
methods do nothing — is what every library function gets unless its caller
passes something else, so library behaviour, stdout, and the JSON contract are
untouched. Only a CLI swaps in :class:`StderrProgress`, and only when its stderr
is a terminal or ``--progress`` asked for it. An agent capturing stderr through
a pipe gets the silence it had before.

**Core logic still never prints** (the rule in AGENTS.md). A long-running
function takes a ``progress`` argument and *calls* it; what that call does is
the CLI's decision, made at the CLI layer. That is also what keeps this useful
from the library: a caller with its own UI passes its own :class:`Progress`.

Two kinds of step, and the difference matters:

* **Counted** — ``step("AI review", total=40)`` plus ``step.advance()`` per page.
  Reports "24/40" and, because the count moves, distinguishes slow from stuck.
* **Indeterminate** — ``step("Converting with LibreOffice")`` with no total, for
  a single opaque call. There is nothing to count, but the elapsed clock still
  ticks, which is the actual question a user has: *is it alive?* The clock is
  driven by a background thread rather than by the work, so it keeps moving
  while the calling thread is blocked in a socket read.

Everything is written to **stderr**, never stdout: stdout carries the result.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO

#: Repaint interval, seconds. Fast enough that the spinner reads as motion,
#: slow enough that a 32-way ``--jobs`` fan-out cannot turn it into a write
#: storm (every ``advance`` is rate-limited to this too).
TICK = 0.4

#: On a non-terminal stream there is no line to repaint, so liveness is reported
#: as an occasional extra line instead. Rare enough not to bury a log.
HEARTBEAT = 15.0

_UNICODE_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_ASCII_FRAMES = ("|", "/", "-", "\\")
_UNICODE_MARKS = ("✔", "✖")
_ASCII_MARKS = ("+", "!")


class Step:
    """One phase of a job. This is the no-op implementation.

    Library code holds one of these and calls :meth:`advance`; it never learns
    whether anything is being displayed.
    """

    def advance(self, n: int = 1) -> None:
        """Record ``n`` more completed items."""

    def set_total(self, total: int | None) -> None:
        """Set (or correct) the item count, once it is known."""


class Progress:
    """A progress sink. This base class is the no-op one — see :data:`NULL`.

    Subclasses override :meth:`step`. ``enabled`` lets a caller skip work that
    only exists to feed the display (counting pages up front, say) when nothing
    is listening.
    """

    enabled = False

    @contextmanager
    def step(self, name: str, total: int | None = None) -> Iterator[Step]:
        """Run a phase of the job named ``name``, over ``total`` items if known."""
        yield _NULL_STEP

    def close(self) -> None:
        """Release anything the reporter holds. Idempotent."""

    def __enter__(self) -> Progress:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


_NULL_STEP = Step()

#: The default reporter: does nothing, costs nothing, shares no state. Library
#: functions default their ``progress`` argument to ``None`` and substitute this.
NULL = Progress()


def is_interactive(stream: IO[str] | None = None) -> bool:
    """Whether ``stream`` (default stderr) is a terminal a human is watching."""
    stream = sys.stderr if stream is None else stream
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):  # closed or not a real stream
        return False


def reporter(enabled: bool, *, stream: IO[str] | None = None) -> Progress:
    """:class:`StderrProgress` when ``enabled``, otherwise :data:`NULL`."""
    return StderrProgress(stream) if enabled else NULL


class StderrProgress(Progress):
    """Reports progress on stderr, repainting a single line on a terminal.

    On a terminal the display is one line rewritten in place with ``\\r``, and
    every step ends by leaving a completed line behind. Off a terminal (a log
    file, a CI job) there is no line to rewrite, so each step's start and end get
    a line of their own plus a "still working" line every :data:`HEARTBEAT`
    seconds — which is the whole point, since that stream is exactly where a
    hung job needs to be visible after the fact.

    A daemon thread does the repainting, so the elapsed clock advances while the
    work is blocked in a subprocess or a socket read. The thread starts with the
    first step and stops on :meth:`close`; it holds no reference to the work, and
    every write goes through one lock, so an ``advance`` from a worker thread
    cannot interleave with a repaint.
    """

    enabled = True

    def __init__(
        self,
        stream: IO[str] | None = None,
        *,
        interval: float = TICK,
        heartbeat: float = HEARTBEAT,
        tty: bool | None = None,
        background: bool = True,
        clock: object = time.monotonic,
    ) -> None:
        self._stream = sys.stderr if stream is None else stream
        self._interval = interval
        self._heartbeat = heartbeat
        self._tty = is_interactive(self._stream) if tty is None else tty
        self._background = background
        self._clock = clock
        unicode_ok = _supports_unicode(self._stream)
        self._frames = _UNICODE_FRAMES if unicode_ok else _ASCII_FRAMES
        self._marks = _UNICODE_MARKS if unicode_ok else _ASCII_MARKS
        self._lock = threading.RLock()
        self._stack: list[_LiveStep] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame = 0
        self._painted = 0
        self._last_paint = 0.0

    # --- the Progress interface ---

    @contextmanager
    def step(self, name: str, total: int | None = None) -> Iterator[Step]:
        live = _LiveStep(self, name, total, self._now())
        with self._lock:
            self._stack.append(live)
            self._begin(live)
        self._ensure_thread()
        try:
            yield live
        except BaseException:
            # A failed step still gets a closing line: the last thing on stderr
            # before the error should not be a half-painted progress line.
            self._end(live, ok=False)
            raise
        self._end(live, ok=True)

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2 * self._interval + 1)
        with self._lock:
            self._clear()
            self._stack.clear()

    # --- painting ---

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def _begin(self, live: _LiveStep) -> None:
        if self._tty:
            self._paint(force=True)
        else:
            self._line(f"{live.name}: started{_of(live.total)}")

    def _end(self, live: _LiveStep, *, ok: bool) -> None:
        with self._lock:
            if live in self._stack:
                self._stack.remove(live)
            now = self._now()
            self._clear()
            if self._tty:
                mark = self._marks[0 if ok else 1]
                self._line(_join(mark, live.name, live.counts(), _bracket(now - live.started)))
            else:
                self._line(self._status(live, "done" if ok else "failed", now))
            # The step underneath, if any, owns the line again.
            if self._stack:
                self._paint(force=True)

    def _status(self, live: _LiveStep, word: str, now: float) -> str:
        """One self-contained line for a non-terminal stream, where nothing is
        rewritten and each line has to stand on its own in a log."""
        return _join(f"{live.name}:", word, live.counts(), _bracket(now - live.started))

    def _tick(self) -> None:
        """One repaint, called by the background thread (and by tests)."""
        with self._lock:
            if not self._stack:
                return
            self._frame = (self._frame + 1) % len(self._frames)
            if self._tty:
                self._paint(force=True)
                return
            live = self._stack[-1]
            now = self._now()
            if now - live.last_heartbeat >= self._heartbeat:
                live.last_heartbeat = now
                self._line(self._status(live, "still working", now))

    def _paint(self, *, force: bool = False) -> None:
        """Rewrite the terminal line. A no-op off a terminal, where the
        heartbeat carries liveness instead."""
        with self._lock:
            if not self._tty or not self._stack:
                return
            now = self._now()
            if not force and now - self._last_paint < self._interval:
                return
            self._last_paint = now
            live = self._stack[-1]
            text = _fit(
                _join(
                    self._frames[self._frame],
                    live.name,
                    live.counts(),
                    _bracket(now - live.started),
                )
            )
            pad = max(0, self._painted - len(text))
            self._write("\r" + text + " " * pad)
            self._painted = len(text)

    def _clear(self) -> None:
        """Blank the in-place line so the next write starts from column zero."""
        if self._painted:
            self._write("\r" + " " * self._painted + "\r")
            self._painted = 0

    def _line(self, text: str) -> None:
        self._write(text + "\n")

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (ValueError, OSError):
            # A closed or broken stderr must never take down the actual job.
            pass

    # --- the ticking thread ---

    def _ensure_thread(self) -> None:
        if not self._background or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rp-progress", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._tick()


class _LiveStep(Step):
    """A step being displayed. Counters are guarded by the reporter's lock, so
    workers in a ThreadPoolExecutor can all call ``advance``."""

    def __init__(self, owner: StderrProgress, name: str, total: int | None, started: float) -> None:
        self.name = name
        self.total = total
        self.started = started
        self.last_heartbeat = started
        self.done = 0
        self._owner = owner

    def advance(self, n: int = 1) -> None:
        with self._owner._lock:
            self.done += n
        self._owner._paint()

    def set_total(self, total: int | None) -> None:
        with self._owner._lock:
            self.total = total
        self._owner._paint()

    def counts(self) -> str:
        if self.total is not None:
            return f"{self.done}/{self.total}"
        return str(self.done) if self.done else ""


def _of(total: int | None) -> str:
    return f" ({total})" if total is not None else ""


def _join(*parts: str) -> str:
    """Space-join, dropping empties — an indeterminate step has no count, and
    must not read as though it had one."""
    return " ".join(part for part in parts if part)


def _bracket(seconds: float) -> str:
    return f"[{_elapsed(seconds)}]"


def _elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole}s" if whole < 60 else f"{whole // 60}m{whole % 60:02d}s"


def _fit(text: str) -> str:
    """Truncate to the terminal width: a line that wraps cannot be rewritten in
    place, and leaves a trail of stale fragments behind instead."""
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    return text if len(text) < width else text[: max(1, width - 2)] + "…"


def _supports_unicode(stream: IO[str]) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    try:
        "⠋✔✖…".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True
