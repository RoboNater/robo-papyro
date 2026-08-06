from pathlib import Path

from rp_pptx.models import FillResult
from rp_pptx.pptx.write import replace_text


def fill_template(
    template: str | Path, context: dict, output: Path, *, strict: bool = True
) -> FillResult:
    replacements = {"{{ " + key + " }}": str(value) for key, value in context.items()}
    result = replace_text(Path(template), replacements, output=output)
    unresolved = [key for key, count in result.replacements.items() if count == 0]
    if strict and unresolved:
        from rp_core.errors import InputError

        raise InputError(f"Unresolved placeholders: {', '.join(unresolved)}")
    return FillResult(
        output=output, filled={k: str(v) for k, v in context.items()}, unresolved=unresolved
    )
