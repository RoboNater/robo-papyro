"""Run-spanning replacement for DrawingML text paragraphs."""


def replace_in_paragraph(paragraph, old: str, new: str, *, match_case: bool = True) -> int:
    runs = list(paragraph.runs)
    text = "".join(run.text for run in runs)
    haystack, needle = (text, old) if match_case else (text.casefold(), old.casefold())
    starts, cursor = [], 0
    while needle and (position := haystack.find(needle, cursor)) >= 0:
        starts.append(position)
        cursor = position + len(needle)
    for start in reversed(starts):
        end = start + len(old)
        offsets, total = [], 0
        for run in runs:
            offsets.append((total, total + len(run.text), run))
            total += len(run.text)
        touched = [(a, b, run) for a, b, run in offsets if a < end and b > start]
        if not touched:
            continue
        a, _b, first = touched[0]
        first.text = (
            first.text[: start - a] + new + (first.text[end - a :] if len(touched) == 1 else "")
        )
        for index, (a, b, run) in enumerate(touched[1:], 1):
            run.text = run.text[max(0, end - a) :] if index == len(touched) - 1 and end < b else ""
    return len(starts)
