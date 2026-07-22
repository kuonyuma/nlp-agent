# 第三项：引导模式多轮测评

本模块测试同一份 `GuidedBlueprint` 下的真实多轮 `socratic` 对话。被测 Agent
只通过已经运行的 Web Gateway 访问；评测器绝不构造第二个 Agent Runtime。

`FlashStudentSimulator` 使用项目既有 `utility-flash` preset，因此复用同一 API
Key，但不访问 Gateway、SQLite、Teacher Catalogue 或主程序会话。实际 Gateway
适配器必须为每个 case 创建带 evaluation 标记的独立 session，并在 `finally`
中清理该 session；不得修改或删除非评测 session。

本阶段已提供：数据契约、蓝图 fixture、Flash 学生模拟器接口、多轮 runner 骨架，
以及确定性的架构判定器。后续接入实现需在每轮 Turn 完成并持久化后采集
`GuidedRunSnapshot`，供判定器检查 session 复用、蓝图一致性、Turn 终态、progress
单调递增和 Trace 覆盖率。

`HttpGuidedGatewayExecutor` 已接入已有 Web Gateway：它只接受 `evaluation-*`
workspace，先验证评测蓝图已经在该 workspace 启用，随后真实提交每一轮学生回复。
它不会自动写入教师目录；case 完成后只删除自己创建并带评测标签的 chat session。
