"""Prompt specifications and version-aware Markdown template registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.prompt_runtime.cache import PromptTemplateCache
from core.prompt_runtime.validator import PromptValidationError, validate_template


@dataclass(frozen=True, slots=True)
class PromptSpec:
    id: str
    version: str
    template: str
    variables: frozenset[str] = frozenset()
    description: str = ""


DEFAULT_SPECS: tuple[PromptSpec, ...] = (
    PromptSpec("coordinator", "1.0", "coordinator.md", frozenset({"worker_profiles"})),
    PromptSpec("worker", "1.0", "worker.md", frozenset({"today"})),
    PromptSpec("runtime.exhaustion", "1.0", "runtime/exhaustion.md", frozenset({"reason"})),
    PromptSpec("retry.empty_response", "1.0", "retry/empty_response.md"),
    PromptSpec("retry.continue_after_truncation", "1.0", "retry/continue_after_truncation.md"),
    PromptSpec("memory.inject", "1.0", "memory/inject.md", frozenset({"memory"})),
    PromptSpec("memory.curator", "1.0", "memory/curator.md"),
    PromptSpec("memory.curate_request", "1.0", "memory/curate_request.md", frozenset({"memory", "archives"})),
    PromptSpec("compression.auto_summary", "1.0", "compression/auto_summary.md", frozenset({"conversation"})),
    PromptSpec("compression.collapse_summary", "1.0", "compression/collapse_summary.md", frozenset({"conversation"})),
    PromptSpec("tool.contract", "1.0", "tool/tool_contract.md"),
)


class PromptRegistry:
    """Loads registered Markdown prompts; a version may be overridden per id."""

    def __init__(self, templates_dir: str | Path | None = None, *, versions: dict[str, str] | None = None) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir else Path(__file__).parent / "templates"
        self.versions = dict(versions or {})
        self.cache = PromptTemplateCache()
        self._specs: dict[str, PromptSpec] = {}
        for spec in DEFAULT_SPECS:
            self.register(spec)

    def register(self, spec: PromptSpec) -> None:
        if spec.id in self._specs:
            raise PromptValidationError(f"duplicate Prompt id: {spec.id}")
        self._specs[spec.id] = spec

    def get(self, prompt_id: str) -> PromptSpec:
        try:
            spec = self._specs[prompt_id]
        except KeyError as error:
            raise PromptValidationError(f"unknown Prompt id: {prompt_id}") from error
        selected_version = self.versions.get(prompt_id, spec.version)
        if selected_version == spec.version:
            return spec
        suffix = Path(spec.template).suffix
        versioned = Path(spec.template).with_suffix("").as_posix() + f".v{selected_version}{suffix}"
        return PromptSpec(spec.id, selected_version, versioned, spec.variables, spec.description)

    def load(self, prompt_id: str) -> tuple[PromptSpec, str]:
        spec = self.get(prompt_id)
        path = self.templates_dir / spec.template
        if not path.is_file():
            raise PromptValidationError(f"Prompt {prompt_id!r} template not found: {path}")
        template = self.cache.read(path)
        validate_template(prompt_id=prompt_id, template=template, variables=spec.variables)
        return spec, template

    def reload(self) -> None:
        self.cache.clear()
