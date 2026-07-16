"""Compatibility adapter for scoped memory system messages."""

from langchain_core.messages import SystemMessage

from core.session_context import SessionContext
from server.memory.runtime import global_memory_runtime


def get_memory_system_message(
    context: SessionContext | None = None,
) -> SystemMessage | None:
    return global_memory_runtime.context_message(
        context or SessionContext(session_id="default_session")
    )
