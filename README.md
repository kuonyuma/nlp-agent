# nlp-agent

本项目完整复刻自 `liunor/Agentic-Travel`，并改造成通用 NLP 多智能体框架。

保留的核心能力：

- LangGraph Coordinator/Worker 主从编排
- Worker 并发、续接、停止和消息通知
- SQLite Checkpointer 与 JSONL 会话记录
- 长期记忆的提取、索引和按需注入
- Context Trim、Snip、Micro-Compact、Context Collapse、Auto-Compact
- Markdown Skill 加载和最小权限工具分配
- 文件读取、时间和网页搜索通用工具
- 单实例 Backend Gateway Core，统一管理 Agent、Turn、Worker 和关闭生命周期
- SQLite Turn/Event/Outbox、幂等提交、断线事件重放与流式订阅
- Session/Memory/Trace/Worker 控制的认证主体与所有权隔离

## Backend Gateway

CLI 已经通过 `BackendGateway` 进入 Agent，未来 FastAPI 也应只适配该入口，
不要在 Web 进程中另外构建 LangGraph 或 Worker Runtime。当前本地运行时要求
单 Gateway 进程；详细生命周期、流式恢复和安全边界见
[`docs/backend-gateway.md`](docs/backend-gateway.md)。

已经移除：

- RAG、向量库、知识库入库与检索
- 地图、路线、周边搜索等文旅工具
- 天气、旅行建议、天文和预报工具
- 图像生成工具
- 文旅行程规划 Skill
- 所有旅行领域专用提示词和记忆分类

## 使用 uv 运行

```powershell
uv sync
Copy-Item .env-example .env
uv run python main.py chat
```

## FastAPI Web backend

```powershell
uv run python main.py serve
```

This starts one FastAPI process on `127.0.0.1:8765`. Its lifespan owns exactly
one `BackendGateway`; HTTP is the control plane and `/ws/v1` is the multiplexed
realtime plane. See [`docs/web-api.md`](docs/web-api.md) for authentication,
routes, event contracts, reconnect recovery, and the nanobot WebUI adaptation
map.

## Developer and observability platform

The administrator control plane stays on the main WebUI at `/developer`. The
read-mostly Trace, Token, latency, error, session, event, and storage monitor is
isolated on `127.0.0.1:8766` and does not own an Agent runtime:

```powershell
uv run python main.py monitor
```

Build its frontend with `cd webui; npm run build:monitor`. Architecture,
security boundaries, ports, and development commands are documented in
[`docs/developer-platform.md`](docs/developer-platform.md).

在 `.env` 中至少配置 `DEEPSEEK_API_KEY`。可在
`configs/agent_config.yaml` 中修改 Coordinator、Worker 模型和按智能体名称的覆盖规则。

## 常用命令

```powershell
uv run python -m compileall .
uv run pytest
uv run python main.py chat
```
