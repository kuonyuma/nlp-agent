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

在 `.env` 中至少配置 `DEEPSEEK_API_KEY`。可在
`configs/agent_config.yaml` 中修改 Coordinator、Worker 模型和按智能体名称的覆盖规则。

## 常用命令

```powershell
uv run python -m compileall .
uv run pytest
uv run python main.py chat
```

