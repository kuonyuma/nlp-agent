# MySQL 阶段 0 基线

## 范围冻结

- 目标版本：MySQL 8.4 LTS、InnoDB、`utf8mb4`、UTC。
- 默认 Python 驱动：`aiomysql`；DSN 仅由 `NLP_AGENT_DATABASE_URL` 提供。
- 运行时 schema 仅由 Alembic 管理；应用不会调用 `create_all` 或执行运行时 DDL。

## 当前持久化入口

| 位置 | 当前状态 | 阶段 |
| --- | --- | --- |
| `gateway/repository.py` | Gateway SQLite | MVP 阶段 2–4 |
| `server/web/auth.py` | 进程内 session | MVP 阶段 1–2 |
| `server/agent/grapy.py` | LangGraph SQLite checkpoint | 第二波 |
| `server/agent/session_storage.py` | JSONL transcript | 第二波 |
| `server/memory/manager.py` | Markdown/JSON memory | 第二波 |
| `core/observability/repository.py` | telemetry SQLite | 第二波 |
| `gateway/redis_transport.py` | Redis Streams/PubSub | 保留为传输层 |

## 上线前运维基线

1. MySQL 使用 TLS；运行、迁移、只读账号分离。
2. 开启 binlog 和自动备份；在生产快照上完成一次 PITR 恢复演练。
3. 迁移前生成 SQLite 一致副本并运行 `PRAGMA integrity_check`。
4. 每次切换保留加密只读源快照 7–14 天；MySQL 接受新写入后不得直接回退 SQLite。
