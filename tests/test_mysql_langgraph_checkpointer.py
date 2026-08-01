import os
import uuid

import pytest
from sqlalchemy import text

from server.infrastructure.mysql.config import DatabaseConfig
from server.infrastructure.mysql.engine import create_engine
from server.infrastructure.mysql.langgraph_checkpointer import MySQLCheckpointSaver


@pytest.mark.asyncio
async def test_mysql_checkpoint_round_trip_and_idempotent_writes():
    url = os.environ.get("NLP_AGENT_DATABASE_URL")
    if not url:
        pytest.skip("requires NLP_AGENT_DATABASE_URL")
    engine = create_engine(DatabaseConfig(url=url))
    saver = MySQLCheckpointSaver(engine)
    thread_id = f"test-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1, "id": "00000000-0000-0000-0000-000000000001", "ts": "2026-08-01T00:00:00Z",
        "channel_values": {"messages": ["hello"]}, "channel_versions": {"messages": "1"},
        "versions_seen": {}, "updated_channels": ["messages"],
    }
    stored = await saver.aput(config, checkpoint, {"source": "input", "step": 1}, {"messages": "1"})
    await saver.aput_writes(stored, [("tasks", {"state": "pending"})], "task-1")
    await saver.aput_writes(stored, [("tasks", {"state": "duplicate"})], "task-1")
    restored = await saver.aget_tuple(stored)
    assert restored is not None
    assert restored.checkpoint["channel_values"] == {"messages": ["hello"]}
    assert restored.metadata["source"] == "input"
    assert restored.pending_writes == [("task-1", "tasks", {"state": "pending"})]
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM nlp_langgraph_checkpoint_writes WHERE thread_id = :thread_id"), {"thread_id": thread_id})
        await connection.execute(text("DELETE FROM nlp_langgraph_checkpoint_blobs WHERE thread_id = :thread_id"), {"thread_id": thread_id})
        await connection.execute(text("DELETE FROM nlp_langgraph_checkpoints WHERE thread_id = :thread_id"), {"thread_id": thread_id})
    await saver.aclose()
