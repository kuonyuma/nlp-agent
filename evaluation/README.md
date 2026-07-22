# 评测目录说明

`evaluation/` 是评测运行器、判定器和报告工具；测试数据与真实运行产物不混放在这里。

## 目录约定

```text
.jbeval/
  suites/
    <suite-id>/dataset.yaml     # 版本管理的测试集
  runs/
    <suite-id>/                 # 本地真实运行 JSON 与日志
evaluation/
  core/                             # 所有套件共用的加载、运行、判定、报告引擎
  tool_routing/                     # 第一项：工具路由评测说明与未来专属扩展
  tool_orchestration/               # 第二项：Coordinator → Worker 编排说明与未来专属扩展
  guided/                           # 第三项：多轮苏格拉底式引导学习评测
  exercise_blueprint/               # 第四项：出题蓝图的单题—作答—评分闭环评测
  review_blueprint/                 # 第五项：复习蓝图的回顾—单题—作答—评分闭环评测
  result/
    <suite-id>/                 # 由报告生成器输出的 Markdown
  generate_result_report.py     # PyCharm 可直接运行的交互入口
```

## 新增评测项目

1. 新建 `.jbeval/suites/<suite-id>/dataset.yaml`，其中 `suite.id` 必须与目录名一致，例如 `nlp-tool-routing-v1`。
2. 运行 `uv run python -m evaluation validate .jbeval/suites/<suite-id>/dataset.yaml`。
3. 启动 Web 与 Monitor 后运行 `uv run python -m evaluation run <suite-id> --live`。
4. 在 PyCharm 直接运行 `evaluation/generate_result_report.py`；它自动发现套件、默认选取该套件最新 JSON，也可手工输入任意 JSON 路径。

报告会写入 `evaluation/result/<suite-id>/`，不会与其他评测项目混在一起。

## 蓝图多轮测评

第四、五项都使用真实 Gateway 和 Flash 学生模型，但只允许操作 `evaluation-*` 隔离工作区；测试蓝图和数据集版本化保存在 `.jbeval/suites/`，真实运行产物保存在 `.jbeval/runs/`。

```powershell
# 第四项：出题蓝图
uv run python -m evaluation.exercise_blueprint .jbeval/suites/exercise-blueprint-multiturn-v1/dataset.yaml --live --workspace evaluation-exercise --provision-fixture

# 第五项：复习蓝图
uv run python -m evaluation.review_blueprint .jbeval/suites/review-blueprint-multiturn-v1/dataset.yaml --live --workspace evaluation-review --provision-fixture
```

两者都验证：单题限制、蓝图快照与 Exercise Session 连续性、题目持久化、评分完成、Trace 回填、Token、TTFT 和延迟。复习评测另行保证使用的是 `review_blueprint`，不混用练习蓝图。

## 兼容性

`python -m evaluation run` 仍接受旧式 YAML 路径，但新运行默认按 suite id 写入分目录。不要再向 `.jbeval/datasets/` 添加新数据集。
