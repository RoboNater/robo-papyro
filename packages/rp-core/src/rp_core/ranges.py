"""Range-specification parsing — generic, and generic only.

A range spec is a string of comma-separated items, each either a single number
("5") or an inclusive range ("3-7"). The literal "all" (any case) selects
everything. Numbers are 1-based, matching every user-facing index in the suite.

This serves PDF pages, docx sections, and whatever sheet or slide selection
comes later, so it knows nothing about any of them. ``noun`` only shapes the
error messages, so a PDF tool can say "page" where a spreadsheet tool says
"sheet"; it changes no parsing.

**PDF page *labels* are not handled here.** Resolving "iv" or "FM2" against a
document's label table is format knowledge and lives in ``rp_pdf.pages``.
"""

from __future__ import annotations

from collections.abc import Sequence

from rp_core.errors import InputError

RangeSpec = str


class RangeSpecError(InputError, ValueError):
    """Raised when a range spec is malformed or out of range.

    Also a ``ValueError`` so callers that predate the suite-wide hierarchy keep
    catching it; ``InputError`` is what gives it exit code 1.
    """


def parse_range_spec(spec: RangeSpec, count: int, *, noun: str = "item") -> list[int]:
    """Parse a range spec into a sorted, de-duplicated list of 1-based numbers.

    Raises :class:`RangeSpecError` for malformed specs or values outside
    ``1..count``.
    """
    spec = spec.strip()
    if not spec:
        raise RangeSpecError(
            f"Empty {noun} spec; expected 'all', a {noun} number, or a range like 3-7"
        )
    if spec.lower() == "all":
        return list(range(1, count + 1))

    numbers: set[int] = set()
    for item in spec.split(","):
        item = item.strip()
        if not item:
            raise RangeSpecError(f"Empty item in {noun} spec {spec!r}")
        first, sep, last = item.partition("-")
        start = _parse_number(first, spec, noun)
        end = _parse_number(last, spec, noun) if sep else start
        if end < start:
            raise RangeSpecError(f"Reversed range {item!r} in {noun} spec {spec!r}")
        for number in (start, end):
            if not 1 <= number <= count:
                raise RangeSpecError(
                    f"{noun.capitalize()} {number} is out of range; valid {noun}s are 1-{count}"
                )
        numbers.update(range(start, end + 1))
    return sorted(numbers)


def contiguous_runs(numbers: Sequence[int]) -> list[tuple[int, int]]:
    """Group a sorted list of numbers into inclusive contiguous (start, end)
    runs, so a tool that takes a first/last range can be invoked once per run
    instead of once per number."""
    runs: list[tuple[int, int]] = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def _parse_number(text: str, spec: str, noun: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise RangeSpecError(f"Invalid {noun} number {text!r} in {noun} spec {spec!r}")
    return int(text)
