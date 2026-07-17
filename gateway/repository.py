"""SQLite WAL persistence for Gateway turns, replayable events, and outbox."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway.contracts import GatewayEvent, GatewayEventType, TurnRecord, TurnStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GatewayRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA busy_timeout=5000;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS gateway_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    final_text TEXT,
                    error_kind TEXT,
                    error_message TEXT,
                    idempotency_key TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(user_id, session_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_turns_session
                    ON gateway_turns(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_gateway_turns_status
                    ON gateway_turns(status, created_at);
                CREATE TABLE IF NOT EXISTS gateway_events (
                    event_id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(turn_id, sequence),
                    FOREIGN KEY(turn_id) REFERENCES gateway_turns(turn_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_events_session
                    ON gateway_events(session_id, created_at);
                CREATE TABLE IF NOT EXISTS gateway_outbox (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(event_id) REFERENCES gateway_events(event_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS gateway_user_settings (
                    user_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        workspace_id: str,
        user_id: str,
        input_text: str,
        idempotency_key: str | None,
    ) -> tuple[TurnRecord, bool]:
        with self._lock, self._conn:
            if idempotency_key:
                existing = self._conn.execute(
                    "SELECT * FROM gateway_turns WHERE user_id=? AND session_id=? "
                    "AND idempotency_key=?",
                    (user_id, session_id, idempotency_key),
                ).fetchone()
                if existing:
                    return self._turn(existing), True
            created_at = _now()
            self._conn.execute(
                """INSERT INTO gateway_turns (
                   turn_id,session_id,workspace_id,user_id,status,input_text,
                   idempotency_key,created_at
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    turn_id,
                    session_id,
                    workspace_id,
                    user_id,
                    TurnStatus.ACCEPTED.value,
                    input_text,
                    idempotency_key,
                    created_at,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM gateway_turns WHERE turn_id=?", (turn_id,)
            ).fetchone()
            return self._turn(row), False

    def update_turn(
        self,
        turn_id: str,
        status: TurnStatus,
        *,
        final_text: str | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> TurnRecord:
        fields: dict[str, Any] = {
            "status": status.value,
            "final_text": final_text,
            "error_kind": error_kind,
            "error_message": error_message[:1000] if error_message else None,
        }
        if status == TurnStatus.RUNNING:
            fields["started_at"] = _now()
        if status in {
            TurnStatus.COMPLETED,
            TurnStatus.FAILED,
            TurnStatus.CANCELLED,
            TurnStatus.INTERRUPTED,
        }:
            fields["completed_at"] = _now()
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE gateway_turns SET {assignments} WHERE turn_id=?",
                (*fields.values(), turn_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(turn_id)
            row = self._conn.execute(
                "SELECT * FROM gateway_turns WHERE turn_id=?", (turn_id,)
            ).fetchone()
            return self._turn(row)

    def get_turn(self, turn_id: str) -> TurnRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gateway_turns WHERE turn_id=?", (turn_id,)
            ).fetchone()
        return self._turn(row) if row else None

    def active_turn_for_session(
        self, session_id: str, *, exclude_turn_id: str | None = None
    ) -> TurnRecord | None:
        exclusion = " AND turn_id<>?" if exclude_turn_id else ""
        args: tuple[Any, ...] = (
            session_id,
            TurnStatus.ACCEPTED.value,
            TurnStatus.RUNNING.value,
            *((exclude_turn_id,) if exclude_turn_id else ()),
        )
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gateway_turns WHERE session_id=? AND status IN (?,?) "
                + exclusion + " ORDER BY created_at DESC LIMIT 1",
                args,
            ).fetchone()
        return self._turn(row) if row else None

    def append_event(
        self,
        *,
        turn_id: str,
        session_id: str,
        event_type: GatewayEventType,
        payload: dict[str, Any] | None = None,
    ) -> GatewayEvent:
        with self._lock, self._conn:
            sequence = int(
                self._conn.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM gateway_events WHERE turn_id=?",
                    (turn_id,),
                ).fetchone()[0]
            )
            event = GatewayEvent(
                event_id=uuid.uuid4().hex,
                turn_id=turn_id,
                session_id=session_id,
                sequence=sequence,
                type=event_type,
                payload=payload or {},
            )
            self._conn.execute(
                "INSERT INTO gateway_events VALUES (?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.turn_id,
                    event.session_id,
                    event.sequence,
                    event.type.value,
                    event.created_at.isoformat(),
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                ),
            )
            self._conn.execute(
                "INSERT INTO gateway_outbox(event_id,created_at) VALUES (?,?)",
                (event.event_id, event.created_at.isoformat()),
            )
            return event

    def mark_delivered(self, event_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE gateway_outbox SET delivered_at=?,attempts=attempts+1 WHERE event_id=?",
                (_now(), event_id),
            )

    def events_after(
        self, turn_id: str, *, after_sequence: int = 0, limit: int = 500
    ) -> list[GatewayEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gateway_events WHERE turn_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (turn_id, max(0, after_sequence), min(max(1, limit), 2000)),
            ).fetchall()
        return [self._event(row) for row in rows]

    def list_turns(self, session_id: str, *, limit: int = 100) -> list[TurnRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gateway_turns WHERE session_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, min(max(1, limit), 500)),
            ).fetchall()
        return [self._turn(row) for row in rows]

    def latest_event_sequence(self, turn_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM gateway_events WHERE turn_id=?",
                (turn_id,),
            ).fetchone()
        return int(row[0])

    def get_user_settings(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT revision,settings_json,updated_at FROM gateway_user_settings "
                "WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return {"revision": 0, "settings": {}, "updated_at": None}
        return {
            "revision": int(row["revision"]),
            "settings": json.loads(row["settings_json"] or "{}"),
            "updated_at": row["updated_at"],
        }

    def update_user_settings(
        self,
        user_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock, self._conn:
            current = self.get_user_settings(user_id)
            merged = {**current["settings"], **changes}
            revision = int(current["revision"]) + 1
            updated_at = _now()
            self._conn.execute(
                """INSERT INTO gateway_user_settings(user_id,revision,settings_json,updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     revision=excluded.revision,
                     settings_json=excluded.settings_json,
                     updated_at=excluded.updated_at""",
                (
                    user_id,
                    revision,
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                    updated_at,
                ),
            )
        return {"revision": revision, "settings": merged, "updated_at": updated_at}

    def pending_outbox(self, limit: int = 1000) -> list[GatewayEvent]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT e.* FROM gateway_outbox o JOIN gateway_events e USING(event_id)
                   WHERE o.delivered_at IS NULL ORDER BY o.created_at LIMIT ?""",
                (min(max(1, limit), 5000),),
            ).fetchall()
        return [self._event(row) for row in rows]

    def recover_interrupted(self) -> list[TurnRecord]:
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT turn_id FROM gateway_turns WHERE status IN (?,?)",
                (TurnStatus.ACCEPTED.value, TurnStatus.RUNNING.value),
            ).fetchall()
            recovered = []
            for row in rows:
                recovered.append(
                    self.update_turn(
                        row["turn_id"],
                        TurnStatus.INTERRUPTED,
                        error_kind="gateway_restart",
                        error_message="Gateway restarted before the turn completed.",
                    )
                )
            return recovered

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM gateway_turns WHERE session_id=?", (session_id,))

    def health(self) -> dict[str, Any]:
        with self._lock:
            pending = self._conn.execute(
                "SELECT COUNT(*) FROM gateway_outbox WHERE delivered_at IS NULL"
            ).fetchone()[0]
        return {"database": str(self.path), "pending_outbox": int(pending)}

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _turn(row: sqlite3.Row) -> TurnRecord:
        return TurnRecord(
            turn_id=row["turn_id"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            status=row["status"],
            input_text=row["input_text"],
            final_text=row["final_text"],
            error_kind=row["error_kind"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> GatewayEvent:
        return GatewayEvent(
            event_id=row["event_id"],
            turn_id=row["turn_id"],
            session_id=row["session_id"],
            sequence=row["sequence"],
            type=row["event_type"],
            created_at=row["created_at"],
            payload=json.loads(row["payload_json"] or "{}"),
        )
