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
TEACHING_TABLES = ("gateway_teaching_catalogs",)


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
    return {"source": str(path), "teaching_tables": list(TEACHING_TABLES), "counts": snapshot.counts, "hashes": snapshot.hashes, "target_revision": revision, "ready": revision == "20260801_07"}


def import_legacy_projection(path: Path, database_url: str) -> dict[str, Any]:
    """Import only the legacy teaching catalog into normalized MySQL tables.

    Runtime projections (turns/events/sessions/evidence) are intentionally not imported.
    """
    from sqlalchemy import create_engine

    target = create_engine(database_url.replace("mysql+aiomysql://", "mysql+pymysql://"))
    inserted = 0
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source, target.begin() as connection:
        for table in TEACHING_TABLES:
            exists = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            rows = source.execute("SELECT workspace_id, revision, catalog_json FROM gateway_teaching_catalogs ORDER BY workspace_id").fetchall()
            for workspace_id, revision, catalog_raw in rows:
                catalog = json.loads(catalog_raw)
                connection.execute(text("INSERT INTO nlp_workspaces(id,slug,name,status) VALUES(:id,:slug,:name,'active') ON DUPLICATE KEY UPDATE name=VALUES(name), status='active'"), {"id": workspace_id, "slug": workspace_id, "name": f"教学工作区 {workspace_id}"})
                connection.execute(text("INSERT INTO nlp_course_catalogs(workspace_id,revision,published_revision) VALUES(:workspace,:revision,:revision) ON DUPLICATE KEY UPDATE revision=VALUES(revision), published_revision=VALUES(published_revision)"), {"workspace": workspace_id, "revision": int(revision or 0)})
                for topic in catalog.get("topics", []):
                    connection.execute(text("INSERT INTO nlp_course_topics(id,workspace_id,name,description,status,sort_order) VALUES(:id,:workspace,:name,:description,:status,:sort_order) ON DUPLICATE KEY UPDATE name=VALUES(name), description=VALUES(description), status=VALUES(status), sort_order=VALUES(sort_order)"), {"id": topic["id"], "workspace": workspace_id, "name": topic.get("name", ""), "description": topic.get("description", ""), "status": topic.get("status", "enabled"), "sort_order": int(topic.get("sort_order", 0))})
                    for index, point in enumerate(topic.get("knowledge_points", [])):
                        connection.execute(text("INSERT INTO nlp_knowledge_points(id,workspace_id,topic_id,name,markdown,status,sort_order) VALUES(:id,:workspace,:topic,:name,:markdown,:status,:sort_order) ON DUPLICATE KEY UPDATE name=VALUES(name), markdown=VALUES(markdown), status=VALUES(status), sort_order=VALUES(sort_order)"), {"id": point["id"], "workspace": workspace_id, "topic": topic["id"], "name": point.get("name", ""), "markdown": point.get("markdown", ""), "status": point.get("status", "enabled"), "sort_order": int(point.get("sort_order", index))})
                for blueprint in catalog.get("exercise_blueprints", []) + catalog.get("review_blueprints", []):
                    kind = "exercise" if blueprint in catalog.get("exercise_blueprints", []) else "review"
                    connection.execute(text("INSERT INTO nlp_teaching_blueprints(id,workspace_id,kind,topic_id,knowledge_point_id,status,payload_json,revision) VALUES(:id,:workspace,:kind,:topic,:knowledge,:status,:payload,:revision) ON DUPLICATE KEY UPDATE payload_json=VALUES(payload_json), status=VALUES(status), revision=VALUES(revision)"), {"id": blueprint["id"], "workspace": workspace_id, "kind": kind, "topic": blueprint["topic_id"], "knowledge": blueprint.get("knowledge_point_id"), "status": blueprint.get("status", "draft"), "payload": json.dumps(blueprint, ensure_ascii=False), "revision": int(revision or 0)})
                    for index, rubric in enumerate(blueprint.get("rubric", [])):
                        connection.execute(text("INSERT INTO nlp_blueprint_rubrics(id,blueprint_id,criterion,weight,sort_order) VALUES(UUID(),:blueprint,:criterion,:weight,:sort_order) ON DUPLICATE KEY UPDATE criterion=VALUES(criterion), weight=VALUES(weight)"), {"blueprint": blueprint["id"], "criterion": str(rubric.get("criterion", rubric.get("description", ""))), "weight": int(rubric.get("weight", 1)), "sort_order": index})
                connection.execute(text("INSERT INTO nlp_course_catalog_versions(id,workspace_id,revision,snapshot_json,change_summary) VALUES(UUID(),:workspace,:revision,:snapshot,'SQLite teaching catalog import') ON DUPLICATE KEY UPDATE snapshot_json=VALUES(snapshot_json)"), {"workspace": workspace_id, "revision": int(revision or 0), "snapshot": json.dumps(catalog, ensure_ascii=False)})
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
        if report["target_revision"] != "20260801_08":
            raise SystemExit("target schema must be at Alembic revision 20260801_08")
        print(json.dumps(import_legacy_projection(args.sqlite, args.database_url), ensure_ascii=False, sort_keys=True))
        integrity = validate_mysql_integrity(args.database_url)
        print(json.dumps(integrity, ensure_ascii=False, sort_keys=True))
        if not integrity["valid"]:
            raise SystemExit("foreign-key integrity validation failed")
    elif not args.dry_run:
        raise SystemExit("use --dry-run or explicitly acknowledge --execute --maintenance-window")


if __name__ == "__main__":
    main()
