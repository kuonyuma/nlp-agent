"""Compatibility adapter for direct, model-free scoped memory injection."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

from core.session_context import SessionContext
from server.memory.runtime import global_memory_runtime


async def get_memory_context_message(
    messages: list[Any],
    context: SessionContext | None = None,
) -> SystemMessage | None:
    del messages
    return global_memory_runtime.context_message(
        context or SessionContext(session_id="default_session")
    )
