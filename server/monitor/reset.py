"""Destructive but scoped reset of local learner runtime data."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from configs.settings import settings
from core.identity import AuthenticatedPrincipal
from core.observability.runtime import TelemetryRuntime
from core.session_context import local_context_repository
from gateway.repository import GatewayRepository
from server.agent.node.session_storage import DATA_DIR as WORKER_SESSIONS_DIR
from server.agent.session_service import local_session_service
from server.agent.session_storage import CHAT_HISTORY_DIR, _save_sessions_index
from server.memory.manager import MEMORY_DIR


def _gateway_database_path() -> Path:
    path = Path(str(settings.gateway_runtime.get("database", ".data/gateway/gateway.sqlite3")))
    return path if path.is_absolute() else settings.BASE_DIR / path


def _clear_directory(path: str | Path, *, preserve_names: set[str] | frozenset[str] = frozenset()) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.name in preserve_names:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed


def _clear_checkpoints() -> int:
    path = Path(WORKER_SESSIONS_DIR) / "coordinator_memory.sqlite3"
    if not path.exists():
        return 0
    with sqlite3.connect(path, timeout=5) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        targets = tables & {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "blobs", "writes"}
        count = sum(int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in targets)
        for table in targets:
            connection.execute(f"DELETE FROM {table}")
    return count


class LocalRuntimeResetter:
    """Coordinates reset across the otherwise separate monitor and chat processes."""

    def __init__(self, runtime: TelemetryRuntime, gateway_repository: GatewayRepository | None = None) -> None:
        self.runtime = runtime
        self.gateway_repository = gateway_repository or GatewayRepository(_gateway_database_path())

    async def reset(self) -> dict[str, Any]:
        principal = AuthenticatedPrincipal.system_admin()
        sessions = await local_session_service.list(principal)
        for session in sessions:
            await local_session_service.delete(principal, str(session["session_id"]))

        gateway = await asyncio.to_thread(self.gateway_repository.clear_learning_sessions)
        await self.runtime.flush()
        telemetry = await asyncio.to_thread(self.runtime.repository.clear)
        files = await asyncio.to_thread(self._clear_orphaned_runtime_files)
        return {"sessions": len(sessions), "gateway": gateway, "telemetry": telemetry, "files": files}

    @staticmethod
    def _clear_orphaned_runtime_files() -> dict[str, int]:
        checkpoint_names = {
            "coordinator_memory.sqlite3",
            "coordinator_memory.sqlite3-shm",
            "coordinator_memory.sqlite3-wal",
        }
        files = {
            "chat_history": _clear_directory(CHAT_HISTORY_DIR),
            # The chat process owns this SQLite database and can keep its file
            # handle open on Windows. Clear its checkpoint rows instead of
            # unlinking the database or its WAL companions.
            "worker_sessions": _clear_directory(WORKER_SESSIONS_DIR, preserve_names=checkpoint_names),
            "session_contexts": _clear_directory(local_context_repository.root),
            "memory": _clear_directory(MEMORY_DIR),
            "tool_audit": _clear_directory(settings.BASE_DIR / ".data" / "tool-audit"),
        }
        _save_sessions_index({"active_session": None, "sessions": {}})
        files["checkpoints"] = _clear_checkpoints()
        return files
