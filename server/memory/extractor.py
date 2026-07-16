"""Compatibility entry point for explicit memory curation.

Per-turn extraction was intentionally removed. Callers should archive summaries
through ``MemoryRuntime`` and let its threshold schedule the curator.
"""

from core.session_context import SessionContext
from server.memory.runtime import global_memory_runtime


async def extract_memories(app, session_id: str, last_processed_len: int = 0) -> None:
    del app, last_processed_len
    await global_memory_runtime.curate_now(SessionContext(session_id=session_id))
