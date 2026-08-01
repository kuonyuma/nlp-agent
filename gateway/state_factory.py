"""Composition seam for replacing the Worker state backend."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from gateway.repository import GatewayRepository
from gateway.state import TurnExecutionState


StateFactory = Callable[[dict[str, Any]], TurnExecutionState]


def build_turn_execution_state(config: dict[str, Any]) -> TurnExecutionState:
    """Build Worker persistence without coupling its runtime to SQLite."""
    factory_ref = str(config.get("state_factory") or "").strip()
    if factory_ref:
        module_name, separator, attribute = factory_ref.partition(":")
        if not separator or not module_name or not attribute:
            raise ValueError("gateway.state_factory must use package.module:function")
        factory = cast(
            StateFactory, getattr(importlib.import_module(module_name), attribute)
        )
        return factory(config)

    database = Path(str(config.get("database", ".data/gateway/gateway.sqlite3")))
    if not database.is_absolute():
        database = Path(__file__).resolve().parent.parent / database
    return GatewayRepository(
        database,
        knowledge_point_prompt_budget=max(
            1, int(config.get("knowledge_point_prompt_budget", 12_000))
        ),
    )
