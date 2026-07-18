"""Prompt composition entry point used by Agent, Memory, and Tool runtimes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langchain_core.messages import SystemMessage

from core.prompt_runtime.registry import PromptRegistry
from core.prompt_runtime.renderer import PromptRenderer


class PromptComposer:
    """Compose independently versioned prompt sections without string appends."""

    def __init__(self, renderer: PromptRenderer) -> None:
        self.renderer = renderer

    def compose(self, sections: Iterable[tuple[str, dict[str, Any] | None] | str]) -> str:
        """Combine registered rule templates with explicitly supplied non-prompt sections.

        Plain strings are deliberately for runtime data such as a resolved Skill SOP;
        they are not registered as prompts and retain their own lifecycle.
        """
        rendered = [
            section.strip()
            if isinstance(section, str)
            else self.renderer.render(section[0], **(section[1] or {}))
            for section in sections
        ]
        return "\n\n---\n\n".join(part for part in rendered if part)

    def system_message(
        self, sections: Iterable[tuple[str, dict[str, Any] | None] | str], **kwargs: Any
    ) -> SystemMessage:
        return SystemMessage(content=self.compose(sections), **kwargs)


class PromptRuntime:
    def __init__(self, registry: PromptRegistry | None = None) -> None:
        if registry is None:
            from configs.settings import settings

            registry = PromptRegistry(versions=settings.prompt_runtime.get("versions", {}))
        self.registry = registry
        self.renderer = PromptRenderer(self.registry)
        self.composer = PromptComposer(self.renderer)

    def render(self, prompt_id: str, /, **values: Any) -> str:
        return self.renderer.render(prompt_id, **values)


global_prompt_runtime = PromptRuntime()
