"""Strict, dependency-free rendering for registered prompt templates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from core.prompt_runtime.registry import PromptRegistry
from core.prompt_runtime.validator import validate_render_inputs


_VARIABLE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptRenderer:
    def __init__(self, registry: PromptRegistry) -> None:
        self.registry = registry

    def render(self, prompt_id: str, /, **values: Any) -> str:
        spec, template = self.registry.load(prompt_id)
        validate_render_inputs(prompt_id=prompt_id, variables=spec.variables, values=values)
        rendered = _VARIABLE.sub(lambda match: str(values[match.group(1)]), template)
        # Keep this guard even though input validation should make it unreachable.
        if _VARIABLE.search(rendered):
            raise RuntimeError(f"Prompt {prompt_id!r} rendered with unresolved variables")
        return rendered.strip()
