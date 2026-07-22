# 第四项：出题蓝图多轮稳定性测评

在隔离的 `evaluation-*` 工作区中运行真实 Gateway。每例仅两轮：学生请求练习 → Agent 基于固定蓝图出一题 → Flash 学生模型作答 → Agent 按同一蓝图 rubric 评分并结束。

断言：聊天/Exercise Session/蓝图快照连续；恰好一题；题目和 rubric 已持久化；评分后 Exercise Session 为 `completed` 且只产生一次作答；每个 Turn 终态完成；Trace、Token、TTFT 与延迟完整回填。

```powershell
uv run python -m evaluation.exercise_blueprint .jbeval/suites/exercise-blueprint-multiturn-v1/dataset.yaml --live --workspace evaluation-exercise --provision-fixture
```
