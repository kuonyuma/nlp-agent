"""Fail-fast checks used by the MVP maintenance-window cutover."""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.migrate_sqlite_to_mysql import target_schema_revision, validate_mysql_integrity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    revision = __import__("asyncio").run(target_schema_revision(args.database_url))
    if revision != "20260801_06":
        raise SystemExit(f"schema revision is {revision!r}; expected 20260801_06")
    result = validate_mysql_integrity(args.database_url)
    if not result["valid"]:
        raise SystemExit(f"foreign-key checks failed: {result['checks']}")
    config = (args.project_root / "configs" / "agent_config.yaml").read_text(encoding="utf-8")
    if "persistence: mysql" not in config:
        raise SystemExit("cutover gate requires gateway.persistence=mysql")
    print("MySQL MVP cutover gates passed")


if __name__ == "__main__":
    main()
