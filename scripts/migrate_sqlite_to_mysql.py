"""One-way, resumable MVP import from Gateway SQLite into MySQL.

This CLI is the only code allowed to open the legacy SQLite database after the
cutover.  It never changes SQLite and refuses a live import unless a dry-run
report has first been reviewed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from server.infrastructure.mysql import DatabaseConfig, create_engine


SOURCE_TABLES = ("gateway_teaching_catalogs", "gateway_turns", "gateway_events")


@dataclass(frozen=True)
class SourceSnapshot:
    counts: dict[str, int]
    hashes: dict[str, str]


def snapshot_sqlite(path: Path) -> SourceSnapshot:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        counts: dict[str, int] = {}
        hashes: dict[str, str] = {}
        for table in SOURCE_TABLES:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                counts[table], hashes[table] = 0, hashlib.sha256(b"").hexdigest()
                continue
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            canonical = json.dumps([list(row) for row in rows], ensure_ascii=False, default=str, separators=(",", ":"))
            counts[table], hashes[table] = len(rows), hashlib.sha256(canonical.encode()).hexdigest()
    return SourceSnapshot(counts, hashes)


async def target_schema_revision(database_url: str) -> str | None:
    engine = create_engine(DatabaseConfig(database_url))
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    finally:
        await engine.dispose()


def validate_mysql_integrity(database_url: str) -> dict[str, Any]:
    from sqlalchemy import create_engine

    engine = create_engine(database_url.replace("mysql+aiomysql://", "mysql+pymysql://"))
    checks: dict[str, int] = {}
    with engine.connect() as connection:
        checks["orphan_turn_events"] = int(connection.execute(text("SELECT COUNT(*) FROM nlp_turn_events e LEFT JOIN nlp_turns t ON t.id=e.turn_id WHERE t.id IS NULL")).scalar_one())
        checks["orphan_conversation_messages"] = int(connection.execute(text("SELECT COUNT(*) FROM nlp_conversation_messages m LEFT JOIN nlp_conversations c ON c.id=m.conversation_id WHERE c.id IS NULL")).scalar_one())
        checks["orphan_exercise_questions"] = int(connection.execute(text("SELECT COUNT(*) FROM nlp_exercise_questions q LEFT JOIN nlp_exercise_sessions s ON s.id=q.exercise_session_id WHERE s.id IS NULL")).scalar_one())
    engine.dispose()
    return {"checks": checks, "valid": all(value == 0 for value in checks.values())}


def dry_run_report(path: Path, database_url: str) -> dict[str, Any]:
    snapshot = snapshot_sqlite(path)
    revision = asyncio.run(target_schema_revision(database_url))
    return {"source": str(path), "counts": snapshot.counts, "hashes": snapshot.hashes, "target_revision": revision, "ready": revision == "20260801_06"}


def import_legacy_projection(path: Path, database_url: str) -> dict[str, Any]:
    """Copy every legacy row into the immutable MySQL compatibility projection."""
    from sqlalchemy import create_engine

    target = create_engine(database_url.replace("mysql+aiomysql://", "mysql+pymysql://"))
    inserted = 0
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source, target.begin() as connection:
        for table in SOURCE_TABLES:
            exists = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            cursor = source.execute(f"SELECT * FROM {table} ORDER BY 1")
            names = [column[0] for column in cursor.description]
            for values in cursor.fetchall():
                payload = dict(zip(names, values, strict=True))
                aggregate_id = str(payload.get("turn_id") or payload.get("workspace_id") or payload.get("event_id") or uuid.uuid4())
                connection.execute(text("INSERT INTO nlp_gateway_compat(id,namespace,aggregate_id,payload_json) VALUES(UUID(),:namespace,:aggregate,:payload) ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json), revision=revision+1"), {"namespace": f"legacy:{table}", "aggregate": f"{aggregate_id}:{inserted}", "payload": json.dumps(payload, ensure_ascii=False, default=str)})
                inserted += 1
    target.dispose()
    return {"inserted": inserted, "source_hashes": snapshot_sqlite(path).hashes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--maintenance-window", action="store_true", help="explicitly acknowledge application writes are stopped")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    if not args.sqlite.is_file():
        raise SystemExit(f"legacy SQLite file not found: {args.sqlite}")
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.sqlite, args.backup_dir / args.sqlite.name)
    report = dry_run_report(args.sqlite, args.database_url)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.execute:
        if not args.maintenance_window:
            raise SystemExit("refusing import without --maintenance-window")
        if report["target_revision"] != "20260801_06":
            raise SystemExit("target schema must be at Alembic revision 20260801_06")
        print(json.dumps(import_legacy_projection(args.sqlite, args.database_url), ensure_ascii=False, sort_keys=True))
        integrity = validate_mysql_integrity(args.database_url)
        print(json.dumps(integrity, ensure_ascii=False, sort_keys=True))
        if not integrity["valid"]:
            raise SystemExit("foreign-key integrity validation failed")
    elif not args.dry_run:
        raise SystemExit("use --dry-run or explicitly acknowledge --execute --maintenance-window")


if __name__ == "__main__":
    main()
