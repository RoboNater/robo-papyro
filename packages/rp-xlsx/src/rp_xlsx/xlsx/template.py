"""``{{ placeholder }}`` substitution over a template workbook (spec section 8).

Deliberately not a template language: ``{{ key }}`` and ``{{ key.subkey }}``
only, **no expression evaluation, no Jinja**, no loops, no conditionals.
Anything needing those should generate rows instead — ``create``'s
``SheetSpec.rows`` is the answer to "repeat this row per record".

**Because a cell's text is a single string, substitution is a plain
``str.replace``** (via :func:`~rp_xlsx.xlsx.write.replace_text`) — the
three-step run-offset dance ``rp-docx``/``rp-pptx`` need because Word and
PowerPoint split a logical string across runs does not apply here and must
not be copied over. Overlapping placeholder keys still resolve
longest-first, so results never depend on dict ordering — that part of the
inherited rule does apply, and ``replace_text`` already provides it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from rp_core.errors import InputError
from rp_xlsx import templates
from rp_xlsx.models import FillResult
from rp_xlsx.xlsx.write import replace_text


def flatten(context: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """``{"client": {"name": "Ada"}}`` -> ``{"client.name": "Ada"}``.

    One level of dotted access is what section 8 promises, but nesting is
    flattened to whatever depth it arrives at — stopping at one would make
    ``{{ a.b.c }}`` fail in a way no error message could explain well.
    """
    flat: dict[str, str] = {}
    for key, value in context.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, prefix=f"{path}."))
        else:
            flat[path] = "" if value is None else str(value)
    return flat


def fill_template(
    template: str | Path,
    context: dict,
    output: Path,
    *,
    strict: bool = True,
) -> FillResult:
    """Fill ``template``'s placeholders from ``context``.

    ``template`` goes through :func:`~rp_xlsx.templates.resolve_template`, so
    a bare house-template name works here exactly as it does for ``create``.

    **"Unresolved" means a placeholder the *template* carries that the
    *context* did not supply a value for** — driven by
    :func:`~rp_xlsx.templates.find_placeholders`, not by which context keys
    happened to match something. A context key with no matching placeholder
    is simply unused; it is a placeholder left sitting in the output that
    strict mode exists to catch.

    ``strict=True`` raises on any such key, and — importantly — **writes no
    output when it does**. Replacement happens against a staged copy and is
    only moved into place once the check passes; a strict failure that
    still leaves a half-filled workbook on disk is worse than no strict
    mode at all, because the next step in a pipeline cannot tell it apart
    from success.
    """
    source = templates.resolve_template(template)
    if source is None:
        raise InputError(
            "No template resolved (template=None and RP_XLSX_TEMPLATE is unset); "
            "fill_template needs a real workbook to fill."
        )
    output = Path(output)
    keys = templates.find_placeholders(source)
    values = flatten(context)

    filled = {key: values[key] for key in keys if key in values}
    unresolved = sorted(key for key in keys if key not in values)

    if strict and unresolved:
        raise InputError(
            f"Unresolved placeholder(s): {', '.join(unresolved)}. "
            "Pass strict=False to leave them in place and have them reported instead."
        )

    replacements = {templates.placeholder_for(key): value for key, value in filled.items()}
    with tempfile.TemporaryDirectory(prefix="rp-xlsx-fill-") as tmp:
        staged = Path(tmp) / f"filled{output.suffix or '.xlsx'}"
        replace_text(source, replacements, output=staged)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(staged.read_bytes())

    return FillResult(output=output, filled=filled, unresolved=unresolved)


__all__ = ["fill_template", "flatten"]
