"""``{{ placeholder }}`` substitution, without docxtpl.

``docxtpl`` is LGPL-2.1-only and therefore a blocker rather than a preference
(spec section 7), so templating is native. What is deliberately *not*
reimplemented is the rest of what docxtpl does:

* Syntax is ``{{ key }}`` and ``{{ key.subkey }}``. Nothing else.
* **No expression evaluation and no Jinja.** A template is data, and rendering
  one must not be able to run anything.
* Loops and conditionals are out of scope — generate the varying part as
  markdown and pass that through :func:`rp_docx.docx.write.create` instead.

The hard part is not the syntax, it is that a placeholder is routinely split
across several ``w:r`` runs. That is :mod:`rp_docx.docx.runs`' problem, and this
module is a thin layer on top of it (spec section 8).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rp_docx import ooxml
from rp_docx.docx import write
from rp_docx.errors import PlaceholderError
from rp_docx.models import FillResult

#: ``{{ key }}`` / ``{{ key.subkey }}`` with any amount of inner whitespace.
#: Keys are dotted identifiers only — no calls, no indexing, no operators, so
#: there is no expression here to evaluate even by accident.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}")


def find_placeholders(path: Path) -> list[str]:
    """Every distinct placeholder key in a document, in first-seen order.

    Walks the same parts replacement does, so a placeholder hiding in a header
    is found before someone discovers it in a printed document.
    """
    seen: list[str] = []
    for name, _ in write.revisable_parts(path):
        root = ooxml.parse_part(path, name)
        if root is None:
            continue
        for _, paragraph in _paragraphs(root):
            for key in PLACEHOLDER.findall(_text(paragraph)):
                if key not in seen:
                    seen.append(key)
    return seen


def _paragraphs(root: Any):
    from rp_docx.docx.runs import iter_paragraphs

    return iter_paragraphs(root)


def _text(paragraph: Any) -> str:
    from rp_docx.docx.runs import paragraph_text

    return paragraph_text(paragraph)


def resolve(context: dict, key: str) -> str | None:
    """Look ``key`` up in ``context``, following dots into nested mappings.

    Returns ``None`` when any step is missing, so an unresolved placeholder is
    reported as unresolved rather than rendered as the string ``"None"``.
    """
    current: Any = context
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return "" if current is None else str(current)


def fill_template(
    template: str | Path,
    context: dict,
    output: Path,
    *,
    strict: bool = True,
) -> FillResult:
    """Substitute ``{{ key }}`` placeholders throughout a template.

    ``strict=True`` raises :class:`~rp_docx.errors.PlaceholderError` listing
    every placeholder the context did not supply — a half-filled contract with
    ``{{ client.name }}`` still in it is worse than no document at all.
    ``strict=False`` leaves them in place and reports them in
    :attr:`~rp_docx.models.FillResult.unresolved`.

    Resolution goes through :func:`rp_docx.templates.resolve_template`, so a
    bare template name works here exactly as it does everywhere else.
    """
    from rp_docx import templates

    source = templates.resolve_template(template)
    keys = find_placeholders(source)

    filled: dict[str, str] = {}
    unresolved: list[str] = []
    for key in keys:
        value = resolve(context, key)
        if value is None:
            unresolved.append(key)
        else:
            filled[key] = value

    if unresolved and strict:
        raise PlaceholderError(
            f"{len(unresolved)} placeholder(s) had no value in the context: "
            f"{', '.join(unresolved)}. Supply them, or pass --no-strict to leave "
            "them in place and have them reported instead."
        )

    # Every spelling of a key maps to the same value, because "{{name}}" and
    # "{{ name }}" are the same placeholder to everyone except a literal string
    # match.
    replacements: dict[str, str] = {}
    for key, spellings in _spellings(source, filled).items():
        for spelling in spellings:
            replacements[spelling] = filled[key]

    result = write.replace_text(source, replacements, output=Path(output))
    written = _retype_for_extension(result.output)
    return FillResult(output=written, filled=filled, unresolved=unresolved)


def _retype_for_extension(path: Path) -> Path:
    """Make the package's content type agree with the name it was written under.

    Filling a `.dotx` produces a `.docx` by copying the package, content type
    included — which would leave a document Word opens as a template, silently
    creating an untitled copy instead of the file the user asked for.
    """
    template_wanted = path.suffix.lower() == ".dotx"
    if ooxml.is_template(path) == template_wanted:
        return path
    return ooxml.retype_as_template(path) if template_wanted else ooxml.retype_as_document(path)


def _spellings(path: Path, filled: dict[str, str]) -> dict[str, list[str]]:
    """Key → every literal placeholder spelling of it found in the document."""
    found: dict[str, list[str]] = {key: [] for key in filled}
    for name, _ in write.revisable_parts(path):
        root = ooxml.parse_part(path, name)
        if root is None:
            continue
        for _, paragraph in _paragraphs(root):
            for match in PLACEHOLDER.finditer(_text(paragraph)):
                key = match.group(1)
                if key in found and match.group(0) not in found[key]:
                    found[key].append(match.group(0))
    return found


__all__ = ["PLACEHOLDER", "fill_template", "find_placeholders", "resolve"]
