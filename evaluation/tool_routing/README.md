# 第一项：工具路由评测

对应正式套件 ID：`nlp-tool-routing-v1`。

- 测试数据：[.jbeval/suites/nlp-tool-routing-v1/dataset.yaml](../../.jbeval/suites/nlp-tool-routing-v1/dataset.yaml)
- 真实运行结果：`.jbeval/runs/nlp-tool-routing-v1/`
- Markdown 报告：`evaluation/result/nlp-tool-routing-v1/`

本套件验证单工具、多工具、禁止调用与无需工具等路由行为。共享加载、运行、判定和报告实现位于 `evaluation/core/`。
