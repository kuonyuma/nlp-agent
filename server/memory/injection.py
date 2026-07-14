import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from server.agent.llm_factory import get_tool_llm
from server.memory.manager import MemoryManager, STALE_WARN_DAYS
from utils.logger import get_logger


logger = get_logger("nlp_agent.memory.injection")


class MemorySelectionResult(BaseModel):
    selected_files: list[str] = Field(default_factory=list)


async def get_memory_context_message(messages: list[Any]) -> SystemMessage | None:
    query = next(
        (
            message.content.strip()
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and message.content.strip()
        ),
        "",
    )
    if not query:
        return None

    manager = MemoryManager()
    headers = manager.scan_memory_headers()
    if not headers:
        return None

    now = time.time()
    listing = "\n".join(
        f"- [{item['type']}] {item['filename']} "
        f"({int((now - item['mtime']) / 86400)} 天前): {item['description']}"
        for item in headers
    )
    selector = SystemMessage(
        content="从给定清单中选择与当前问题真正相关的记忆文件，最多 5 个；无相关项时返回空列表。"
    )
    try:
        result = await get_tool_llm().with_structured_output(MemorySelectionResult).ainvoke(
            [selector, HumanMessage(content=f"当前问题：{query}\n\n记忆清单：\n{listing}")]
        )
    except Exception as error:
        logger.warning("记忆选择失败", error=str(error))
        return None

    header_map = {item["filename"]: item for item in headers}
    recalled = []
    for filename in (result.selected_files if result else [])[:5]:
        if filename not in header_map:
            continue
        try:
            recalled.append(
                {
                    "filename": filename,
                    "type": header_map[filename]["type"],
                    "content": manager.read_memory_topic(filename),
                }
            )
        except OSError:
            continue
    if not recalled:
        return None

    stale = [item["filename"] for item in manager.check_stale_memories(STALE_WARN_DAYS)]
    payload = {
        "recalled_memories": recalled,
        "possibly_stale": stale,
        "instruction": "仅在与当前问题相关时使用这些记忆；陈旧信息需向用户确认。",
    }
    return SystemMessage(
        content=f"Long-term Memory Context:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )

