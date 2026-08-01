from __future__ import annotations

import sqlite3

from scripts.migrate_sqlite_to_mysql import snapshot_sqlite


def test_snapshot_is_stable_and_reads_legacy_sqlite_without_mutating_it(tmp_path) -> None:
    path = tmp_path / "gateway.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE gateway_turns (turn_id TEXT, status TEXT)")
        connection.execute("INSERT INTO gateway_turns VALUES ('turn-1', 'completed')")

    first = snapshot_sqlite(path)
    second = snapshot_sqlite(path)

    assert first == second
    assert first.counts["gateway_turns"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT status FROM gateway_turns").fetchone()[0] == "completed"
