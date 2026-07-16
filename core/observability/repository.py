"""SQLite WAL repository for traces, spans, events, and daily aggregates."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from core.observability.models import SpanRecord, TelemetryEnvelope, TelemetryEvent, TraceRecord


class TelemetryRepository:
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
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    channel TEXT NOT NULL, source TEXT NOT NULL,
                    started_at TEXT NOT NULL, completed_at TEXT,
                    duration_ms INTEGER, ttft_ms INTEGER, status TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_source TEXT NOT NULL DEFAULT 'none',
                    error_kind TEXT, error_message TEXT, attributes_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status, started_at DESC);
                CREATE TABLE IF NOT EXISTS spans (
                    span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
                    parent_span_id TEXT, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    worker_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
                    started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER,
                    status TEXT NOT NULL, attempt INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_source TEXT NOT NULL DEFAULT 'none',
                    error_kind TEXT, error_message TEXT, attributes_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_spans_kind ON spans(kind, started_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, level TEXT NOT NULL,
                    name TEXT NOT NULL, trace_id TEXT, span_id TEXT, session_id TEXT,
                    turn_id TEXT, worker_id TEXT, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp DESC);
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    day TEXT NOT NULL, component TEXT NOT NULL, name TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0, duration_sum_ms INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(day, component, name)
                );
                """
            )

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def write_batch(self, envelopes: Iterable[TelemetryEnvelope]) -> None:
        with self._lock, self._conn:
            for envelope in envelopes:
                if envelope.kind == "trace":
                    self._write_trace(envelope.payload)  # type: ignore[arg-type]
                elif envelope.kind == "span":
                    self._write_span(envelope.payload)  # type: ignore[arg-type]
                else:
                    self._write_event(envelope.payload)  # type: ignore[arg-type]

    def _write_trace(self, item: TraceRecord) -> None:
        u = item.usage
        self._conn.execute(
            """INSERT OR REPLACE INTO traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.trace_id, item.request_id, item.session_id, item.turn_id,
             item.workspace_id, item.user_id, item.channel, item.source,
             item.started_at.isoformat(), item.completed_at.isoformat() if item.completed_at else None,
             item.duration_ms, item.ttft_ms, item.status.value, u.input_tokens,
             u.output_tokens, u.cached_tokens, u.total_tokens, u.source,
             item.error_kind, item.error_message, self._json(item.attributes)),
        )

    def _write_span(self, item: SpanRecord) -> None:
        u = item.usage
        self._conn.execute(
            """INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.span_id, item.trace_id, item.parent_span_id, item.session_id,
             item.turn_id, item.worker_id, item.kind.value, item.name,
             item.started_at.isoformat(), item.completed_at.isoformat() if item.completed_at else None,
             item.duration_ms, item.status.value, item.attempt, u.input_tokens,
             u.output_tokens, u.cached_tokens, u.total_tokens, u.source,
             item.error_kind, item.error_message, self._json(item.attributes)),
        )
        if item.completed_at is not None:
            day = item.completed_at.date().isoformat()
            metric_name = item.name
            if item.kind.value == "model" and item.attributes.get("model"):
                metric_name = f"{item.name}:{item.attributes['model']}"
            error = 1 if item.status.value in {"error", "timeout"} else 0
            success = 1 if item.status.value == "ok" else 0
            self._conn.execute(
                """INSERT INTO daily_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(day,component,name) DO UPDATE SET
                   requests=requests+1, successes=successes+excluded.successes,
                   errors=errors+excluded.errors, duration_sum_ms=duration_sum_ms+excluded.duration_sum_ms,
                   input_tokens=input_tokens+excluded.input_tokens,
                   output_tokens=output_tokens+excluded.output_tokens,
                   cached_tokens=cached_tokens+excluded.cached_tokens,
                   total_tokens=total_tokens+excluded.total_tokens""",
                (day, item.kind.value, metric_name, 1, success, error, item.duration_ms or 0,
                 u.input_tokens, u.output_tokens, u.cached_tokens, u.total_tokens),
            )

    def _write_event(self, item: TelemetryEvent) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (item.event_id, item.timestamp.isoformat(), item.level, item.name,
             item.trace_id, item.span_id, item.session_id, item.turn_id,
             item.worker_id, self._json(item.payload)),
        )

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, args).fetchall()]

    @staticmethod
    def _decode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            for key in ("attributes_json", "payload_json"):
                if key in row:
                    row[key.removesuffix("_json")] = json.loads(row.pop(key) or "{}")
        return rows

    def overview(self, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        rows = self._rows(
            "SELECT status,duration_ms,ttft_ms,input_tokens,output_tokens,cached_tokens,total_tokens "
            "FROM traces WHERE started_at>=? AND completed_at IS NOT NULL", (since,)
        )
        durations = sorted(r["duration_ms"] for r in rows if r["duration_ms"] is not None)
        ttfts = sorted(r["ttft_ms"] for r in rows if r["ttft_ms"] is not None)
        percentile = lambda values, p: values[min(len(values)-1, int((len(values)-1)*p))] if values else None
        failures = sum(r["status"] in {"error", "timeout"} for r in rows)
        return {
            "period_days": days, "requests": len(rows),
            "successes": sum(r["status"] == "ok" for r in rows),
            "errors": failures, "error_rate": failures / len(rows) if rows else 0.0,
            "latency_ms": {"p50": percentile(durations, .50), "p95": percentile(durations, .95)},
            "ttft_ms": {"p50": percentile(ttfts, .50), "p95": percentile(ttfts, .95)},
            "tokens": {key: sum(r[key] for r in rows) for key in
                       ("input_tokens", "output_tokens", "cached_tokens", "total_tokens")},
        }

    def list_traces(self, *, limit: int = 100, session_id: str | None = None,
                    status: str | None = None) -> list[dict[str, Any]]:
        clauses, args = [], []
        if session_id:
            clauses.append("session_id=?"); args.append(session_id)
        if status:
            clauses.append("status=?"); args.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self._decode(self._rows(
            f"SELECT * FROM traces{where} ORDER BY started_at DESC LIMIT ?",
            (*args, min(max(1, limit), 500)),
        ))

    def trace_detail(self, trace_id: str) -> dict[str, Any] | None:
        traces = self._decode(self._rows("SELECT * FROM traces WHERE trace_id=?", (trace_id,)))
        if not traces:
            return None
        return {
            "trace": traces[0],
            "spans": self._decode(self._rows(
                "SELECT * FROM spans WHERE trace_id=? ORDER BY started_at", (trace_id,))),
            "events": self._decode(self._rows(
                "SELECT * FROM events WHERE trace_id=? ORDER BY timestamp", (trace_id,))),
        }

    def usage(self, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc).date() - timedelta(days=max(1, days))).isoformat()
        return self._rows(
            "SELECT * FROM daily_metrics WHERE day>=? ORDER BY day,component,name", (since,)
        )

    def sessions(self, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        return self._rows(
            """SELECT session_id,workspace_id,user_id,channel,COUNT(*) turns,
                      SUM(CASE WHEN status IN ('error','timeout') THEN 1 ELSE 0 END) errors,
                      CAST(AVG(duration_ms) AS INTEGER) avg_duration_ms,
                      SUM(total_tokens) total_tokens,MAX(started_at) last_seen
               FROM traces WHERE started_at>=? AND completed_at IS NOT NULL
               GROUP BY session_id,workspace_id,user_id,channel
               ORDER BY last_seen DESC LIMIT ?""",
            (since, min(max(1, limit), 500)),
        )

    def recent_events(self, *, limit: int = 200, level: str | None = None,
                      trace_id: str | None = None) -> list[dict[str, Any]]:
        clauses, args = [], []
        if level:
            clauses.append("level=?"); args.append(level)
        if trace_id:
            clauses.append("trace_id=?"); args.append(trace_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self._decode(self._rows(
            f"SELECT * FROM events{where} ORDER BY timestamp DESC LIMIT ?",
            (*args, min(max(1, limit), 1000)),
        ))

    def errors(self, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        return self._rows(
            """SELECT COALESCE(error_kind,'unknown') error_kind,kind,name,
                      COUNT(*) count,MAX(started_at) last_seen,MAX(trace_id) sample_trace_id
               FROM spans WHERE started_at>=? AND status IN ('error','timeout')
               GROUP BY error_kind,kind,name ORDER BY count DESC,last_seen DESC LIMIT ?""",
            (since, min(max(1, limit), 500)),
        )

    def prune(self, trace_days: int = 30, event_days: int = 30) -> None:
        trace_before = (datetime.now(timezone.utc) - timedelta(days=trace_days)).isoformat()
        event_before = (datetime.now(timezone.utc) - timedelta(days=event_days)).isoformat()
        with self._lock, self._conn:
            old = [r[0] for r in self._conn.execute(
                "SELECT trace_id FROM traces WHERE started_at<?", (trace_before,)).fetchall()]
            if old:
                marks = ",".join("?" for _ in old)
                self._conn.execute(f"DELETE FROM spans WHERE trace_id IN ({marks})", old)
                self._conn.execute(f"DELETE FROM traces WHERE trace_id IN ({marks})", old)
            self._conn.execute("DELETE FROM events WHERE timestamp<?", (event_before,))

    def health(self) -> dict[str, Any]:
        counts = {}
        with self._lock:
            for table in ("traces", "spans", "events"):
                counts[table] = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return {"database": str(self.path), "database_bytes": self.path.stat().st_size, **counts}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
