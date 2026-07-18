"""Validation for prompt templates and render inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping


_VARIABLE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptValidationError(ValueError):
    """A prompt template or render request violates its declared contract."""


def template_variables(template: str) -> frozenset[str]:
    return frozenset(_VARIABLE.findall(template))


def validate_template(*, prompt_id: str, template: str, variables: frozenset[str]) -> None:
    discovered = template_variables(template)
    if discovered != variables:
        missing = sorted(variables - discovered)
        undeclared = sorted(discovered - variables)
        details = []
        if missing:
            details.append(f"declared but unused: {', '.join(missing)}")
        if undeclared:
            details.append(f"used but undeclared: {', '.join(undeclared)}")
        raise PromptValidationError(f"Prompt {prompt_id!r} variables mismatch ({'; '.join(details)})")


def validate_render_inputs(*, prompt_id: str, variables: frozenset[str], values: Mapping[str, object]) -> None:
    supplied = frozenset(values)
    missing = sorted(variables - supplied)
    unexpected = sorted(supplied - variables)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"Missing variable: {', '.join(missing)}")
        if unexpected:
            details.append(f"Unexpected variable: {', '.join(unexpected)}")
        raise PromptValidationError(f"Prompt {prompt_id!r}: {'; '.join(details)}")
