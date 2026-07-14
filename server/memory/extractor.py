from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from server.agent.llm_factory import get_tool_llm
from server.memory.manager import MemoryManager
from utils.logger import get_logger


logger = get_logger("nlp_agent.memory.extractor")


class MemoryOperation(BaseModel):
    filename: str = Field(description="以 .md 结尾的英文文件名")
    content: str
    memory_type: str = Field(description="profile、preference、project 或 feedback")
    description: str


class MemoryExtractionResult(BaseModel):
    operations: list[MemoryOperation] = Field(default_factory=list)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return ""


def _dialog(messages: list[BaseMessage]) -> str:
    lines = []
    for message in messages:
        if isinstance(message, HumanMessage) and _text(message.content):
            lines.append(f"用户：{_text(message.content)}")
        elif isinstance(message, AIMessage) and _text(message.content):
            lines.append(f"智能体：{_text(message.content)}")
    return "\n".join(lines)


async def extract_memories(app, session_id: str, last_processed_len: int = 0) -> None:
    try:
        state = await app.aget_state({"configurable": {"thread_id": session_id}})
        messages = state.values.get("messages", [])
    except Exception as error:
        logger.warning("读取会话状态失败", error=str(error))
        return

    recent = messages[last_processed_len:] if last_processed_len < len(messages) else messages[-6:]
    dialog = _dialog(recent)
    if not dialog:
        return

    manager = MemoryManager()
    existing = manager.load_memory_index()
    system = SystemMessage(
        content=(
            "你负责从对话中提取真正具有跨会话价值的长期记忆。只保存稳定的用户信息、"
            "明确偏好、持续项目上下文以及用户对智能体的反馈与修正。不要保存寒暄、"
            "一次性问题、密钥、密码、令牌或工具调用参数。没有值得保存的信息时返回空列表。"
        )
    )
    prompt = HumanMessage(content=f"现有索引：\n{existing}\n\n待分析对话：\n{dialog}")
    try:
        result = await get_tool_llm().with_structured_output(MemoryExtractionResult).ainvoke(
            [system, prompt]
        )
    except Exception as error:
        logger.warning("记忆提取失败", error=str(error))
        return

    for operation in result.operations if result else []:
        try:
            manager.save_memory_topic(
                operation.filename,
                operation.content,
                operation.memory_type,
                operation.description,
            )
        except Exception as error:
            logger.warning("保存记忆失败", filename=operation.filename, error=str(error))


