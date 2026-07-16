"""Explicit provider adapter registry; no URL or model-name guessing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.model_runtime.contracts import ModelDefinition, ModelPresetConfig, ProviderConfig


class ProviderAdapter(Protocol):
    def build(
        self,
        *,
        provider_name: str,
        provider: ProviderConfig,
        model_name: str,
        model: ModelDefinition,
        preset_name: str,
        preset: ModelPresetConfig,
        api_key: str,
    ) -> Any: ...


AdapterFactory = Callable[[], ProviderAdapter]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    adapter_factory: AdapterFactory


class ProviderRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ProviderSpec] = {}

    def register(self, name: str, adapter_factory: AdapterFactory, *, replace: bool = False) -> None:
        if name in self._specs and not replace:
            raise ValueError(f"Provider adapter {name!r} is already registered")
        self._specs[name] = ProviderSpec(name=name, adapter_factory=adapter_factory)

    def build(self, adapter_name: str, **kwargs: Any) -> Any:
        try:
            spec = self._specs[adapter_name]
        except KeyError as error:
            raise KeyError(
                f"Unknown provider adapter {adapter_name!r}; available={sorted(self._specs)}"
            ) from error
        return spec.adapter_factory().build(**kwargs)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))


global_provider_registry = ProviderRegistry()
