"""``{{ placeholder }}`` substitution over a template deck (spec section 8).

Deliberately not a template language. The syntax is ``{{ key }}`` and
``{{ key.subkey }}`` and nothing else: **no expression evaluation, no Jinja**, no
loops, no conditionals. Anything needing those should be generated from markdown
instead, where the structure is explicit and the failure modes are a parser's
rather than an interpreter's.

Replacement reuses :mod:`rp_pptx.pptx.runs`, so it inherits section 6's scope —
slides, tables, groups, and notes — which for a template deck is what covers the
title slide and any boilerplate slides carrying placeholders.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from rp_core.errors import InputError
from rp_pptx import templates
from rp_pptx.models import FillResult
from rp_pptx.pptx.write import replace_text


def flatten(context: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """``{"user": {"name": "Ada"}}`` → ``{"user.name": "Ada"}``.

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


def placeholder_for(key: str) -> str:
    return "{{ " + key + " }}"


def fill_template(
    template: str | Path,
    context: dict,
    output: Path,
    *,
    strict: bool = True,
    match_case: bool = True,
) -> FillResult:
    """Fill ``template``'s placeholders from ``context``.

    ``template`` goes through :func:`~rp_pptx.templates.resolve_template`, so a
    bare house-template name works here exactly as it does for ``create``.

    ``strict=True`` raises on any key that matched nothing, and — importantly —
    **writes no output when it does**. Replacement happens against a staged copy
    and is only moved into place once the check passes; a strict failure that
    still leaves a half-filled deck on disk is worse than no strict mode at all,
    because the next step in a pipeline cannot tell it apart from success.
    """
    source = templates.resolve_template(template)
    output = Path(output)
    values = flatten(context)
    replacements = {placeholder_for(key): value for key, value in values.items()}

    with tempfile.TemporaryDirectory(prefix="rp-pptx-fill-") as tmp:
        staged = Path(tmp) / f"filled{output.suffix or '.pptx'}"
        result = replace_text(source, replacements, output=staged, match_case=match_case)
        unresolved = sorted(
            key for key in values if result.replacements.get(placeholder_for(key), 0) == 0
        )
        if strict and unresolved:
            raise InputError(
                f"Unresolved placeholder(s): {', '.join(unresolved)}. "
                "Pass strict=False to leave them in place and have them reported instead."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(staged.read_bytes())

    return FillResult(
        output=output,
        # `filled` and `unresolved` are disjoint: a key that matched nothing was
        # not filled, whatever the caller passed for it.
        filled={key: value for key, value in values.items() if key not in unresolved},
        unresolved=unresolved,
    )
