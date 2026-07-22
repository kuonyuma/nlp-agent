# 第二项：Coordinator → Worker 编排评测

对应正式套件 ID：`nlp-tool-orchestration-v1`。

- 测试数据：[.jbeval/suites/nlp-tool-orchestration-v1/dataset.yaml](../../.jbeval/suites/nlp-tool-orchestration-v1/dataset.yaml)
- 真实运行结果：`.jbeval/runs/nlp-tool-orchestration-v1/`
- Markdown 报告：`evaluation/result/nlp-tool-orchestration-v1/`

本套件验证 Coordinator 是否在独立、并行与依赖任务中正确选择自行调用或分派 Worker，并核验工具归属、等待策略与任务顺序。共享评测引擎位于 `evaluation/core/`。
