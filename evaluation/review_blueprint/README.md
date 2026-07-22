# 第五项：复习蓝图多轮稳定性测评

在隔离的 `evaluation-*` 工作区中运行真实 Gateway。每例仅两轮：学生请求复习 → Agent 根据固定复习蓝图简短回顾并发布一道题 → Flash 学生模型作答 → Agent 按同一 rubric 评分并结束。

断言：只使用 `review_blueprint`；聊天/Exercise Session/蓝图快照连续；仅一道复习题；题目和 rubric 已持久化；评分后状态为 `completed` 且只有一次作答；每个 Turn 完成；Trace、Token、TTFT 与延迟完整回填。

```powershell
uv run python -m evaluation.review_blueprint .jbeval/suites/review-blueprint-multiturn-v1/dataset.yaml --live --workspace evaluation-review --provision-fixture
```
