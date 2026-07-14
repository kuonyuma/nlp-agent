"""可嵌入其他服务的 Agent 运行辅助函数。"""

import asyncio

from langchain_core.messages import HumanMessage

from core.message_queue import global_message_queue
from server.agent.grapy import build_agent
from utils.logger import get_logger


logger = get_logger("nlp_agent.runner")


async def coordinator_listen_loop(app) -> None:
    """监听 Worker 通知并唤醒对应 Coordinator 会话。"""

    while True:
        item = await global_message_queue.dequeue()
        session_id = item["session_id"]
        notification = item["value"]
        message = HumanMessage(
            content=(
                "[WORKER_NOTIFICATION]\n"
                f"```json\n{notification}\n```\n"
                "[/WORKER_NOTIFICATION]\n请综合结果并继续完成用户目标。"
            )
        )
        config = {"configurable": {"thread_id": session_id}}
        try:
            await app.ainvoke({"messages": [message]}, config=config)
        except Exception as error:
            logger.exception("处理 Worker 通知失败", error=str(error))


async def main() -> None:
    app, connection = await build_agent()
    listener = asyncio.create_task(coordinator_listen_loop(app))
    try:
        result = await app.ainvoke(
            {"messages": [HumanMessage(content="请介绍你的多智能体协作方式。")]},
            config={"configurable": {"thread_id": "local-demo"}},
        )
        print(result["messages"][-1].content)
    finally:
        listener.cancel()
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

