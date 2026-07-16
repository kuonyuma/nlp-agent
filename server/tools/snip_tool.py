"""
SnipTool — 让 Coordinator 能主动按消息 ID 范围执行 Snip 压缩。

调用方式：模型输出 tool_call，指定要压缩的消息范围（from_id ~ to_id），
SnipTool 校验参数合法性并返回操作结果。

注意：SnipTool 只做参数校验，不直接修改 LangGraph 状态。实际的 snip 状态写入
由 main.py 中的 _apply_pending_snips() 在 ToolNode 返回后统一执行，
避免与 add_messages reducer 产生竞态条件。
"""
import json
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from schemas.snip import SnipToolInputSpec, SnipToolOutputSpec
from utils.logger import get_logger

logger = get_logger("shiliu.tools.snip")

DESCRIPTION = """
通过消息 ID 范围将上下文历史中的旧消息压缩移除，释放上下文空间。

当你意识到上下文窗口快满、或者早期的对话内容已经无关紧要时，调用此工具。
每条用户消息末尾都带有 [id:XXXXXX] 标签，你可以通过该标签指定压缩范围。

参数说明：
- to_id: 必填，压缩范围的结束消息 ID（含），该 ID 及其之前的旧消息会被移除。
- from_id: 可选，压缩范围的起始消息 ID（含）。不填则从最早的非系统消息开始。

行为：
- 被移除的消息会替换为极小的占位符，不会影响后续消息的连贯性。
- 在压缩位置自动插入边界标记，告知你「此前内容已被压缩」。
- 最近的 10 条消息受保护，不会被压缩。

返回结果包含释放的 token 数量和移除的消息数量。
"""


def make_snip_tool(app):
    """
    工厂函数：创建绑定了 app 实例的 SnipTool。

    Args:
        app: 已编译的 LangGraph app，用于调用 aget_state() 校验参数。
    Returns:
        LangChain tool 实例。
    """
    from server.agent.compression.snip_compact import snip_by_id_range

    @tool("SnipTool", args_schema=SnipToolInputSpec, description=DESCRIPTION)
    async def snip_tool(
        to_id: str,
        config: RunnableConfig,
        from_id: str = None,
    ) -> str:
        """按消息 ID 范围执行 Snip 压缩。"""
        session_id = config.get("configurable", {}).get("thread_id", "")
        if not session_id:
            return SnipToolOutputSpec(
                success=False,
                message="无法获取当前 session_id，Snip 操作中止。",
                error_code=1,
            ).model_dump_json(exclude_none=True)

        config = {"configurable": {"thread_id": session_id}}

        try:
            state = await app.aget_state(config)
            messages = state.values.get("messages", [])
        except Exception as e:
            logger.exception("SnipTool: 获取 state 失败")
            return SnipToolOutputSpec(
                success=False,
                message=f"获取状态失败: {e}",
                error_code=2,
            ).model_dump_json(exclude_none=True)

        result = snip_by_id_range(messages, to_id=to_id, from_id=from_id)

        # 状态写入由 main.py 在 ToolNode 返回后统一执行，避免与 add_messages reducer 竞态。
        if result.tokens_freed == 0:
            return SnipToolOutputSpec(
                success=False,
                message="未找到指定范围的消息，或目标消息在受保护区域内，Snip 操作未执行。",
                error_code=3,
            ).model_dump_json(exclude_none=True)

        messages_removed = 0
        if result.boundary_message:
            messages_removed = result.boundary_message.additional_kwargs.get("messages_removed", 0)

        logger.info(
            "SnipTool 验证通过，等待 main.py 执行状态写入",
            tokens_freed=result.tokens_freed,
            messages_removed=messages_removed,
        )

        return SnipToolOutputSpec(
            success=True,
            tokens_freed=result.tokens_freed,
            messages_removed=messages_removed,
            message=f"Snip 压缩完成，已移除 {messages_removed} 条旧消息，释放约 {result.tokens_freed:,} tokens。",
        ).model_dump_json(exclude_none=True)

    return snip_tool
