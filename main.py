"""nlp-agent 交互式运行入口。"""

import asyncio
import json
import sys
import time
import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def check_config() -> bool:
    from configs.settings import settings

    config = settings.planner_llm
    print(f"Coordinator: {config['model_id']} ({config['base_url']})")
    print(f"Worker:      {settings.tool_llm['model_id']}")
    if not config.get("api_key"):
        print("缺少 DEEPSEEK_API_KEY，请在项目根目录创建 .env。")
        return False
    return True


async def _stream_coordinator(app, text: str, session_id: str) -> bool:
    """流式执行一轮 Coordinator，并返回是否启动了 Worker。"""

    from server.agent.compression.snip_compact import derive_short_id

    message_id = str(uuid.uuid4())
    short_id = derive_short_id(message_id)
    message = HumanMessage(content=f"{text} [id:{short_id}]", id=message_id)
    config = {"configurable": {"thread_id": session_id}}
    started_worker = False
    printed = False

    async for event in app.astream_events(
        {"messages": [message]}, config=config, version="v2"
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            if event.get("metadata", {}).get("langgraph_node") != "coordinator":
                continue
            chunk = event["data"].get("chunk")
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                if not printed:
                    print("\nAgent: ", end="", flush=True)
                    printed = True
                print(chunk.content, end="", flush=True)
        elif kind == "on_chain_end" and event.get("name") == "coordinator":
            output = event["data"].get("output", {})
            messages = output.get("messages", []) if isinstance(output, dict) else []
            if not messages or not isinstance(messages[-1], AIMessage):
                continue
            for tool_call in messages[-1].tool_calls:
                if printed:
                    print()
                    printed = False
                print(f"  → {tool_call['name']}: {tool_call['args']}")
                if tool_call["name"] in {"spawn_worker", "send_message"}:
                    started_worker = True
    if printed:
        print()
    return started_worker


async def _apply_pending_snips(app, session_id: str) -> None:
    from server.agent.compression.snip_compact import snip_by_id_range

    config = {"configurable": {"thread_id": session_id}}
    state = await app.aget_state(config)
    messages = state.values.get("messages", [])
    for message in reversed(messages):
        if not getattr(message, "tool_calls", None):
            continue
        if message.additional_kwargs.get("_snip_applied"):
            continue
        for tool_call in message.tool_calls:
            if tool_call.get("name") != "SnipTool":
                continue
            args = tool_call.get("args", {})
            if not args.get("to_id"):
                continue
            result = snip_by_id_range(
                messages,
                to_id=args["to_id"],
                from_id=args.get("from_id"),
            )
            if result.tokens_freed:
                await app.aupdate_state(config, {"messages": result.messages})
                print(f"[系统] Snip 已释放约 {result.tokens_freed:,} tokens")
            message.additional_kwargs["_snip_applied"] = True
            return


async def _wait_for_workers(app, session_id: str, timeout: int = 90) -> None:
    from core.message_queue import global_message_queue
    from core.task_manager import global_task_manager

    deadline = time.time() + timeout
    while time.time() < deadline:
        running = [
            task
            for task in global_task_manager.active_tasks.values()
            if task.status == "running"
        ]
        if not running and global_message_queue.queue.qsize() == 0:
            return
        try:
            item = await asyncio.wait_for(global_message_queue.dequeue(), timeout=3)
        except asyncio.TimeoutError:
            continue

        notification = item["value"]
        await _stream_coordinator(
            app,
            "[WORKER_NOTIFICATION]\n"
            f"```json\n{notification}\n```\n"
            "[/WORKER_NOTIFICATION]\n请综合结果并继续完成用户目标。",
            item.get("session_id") or session_id,
        )
        await _apply_pending_snips(app, item.get("session_id") or session_id)
        try:
            task_id = json.loads(notification).get("task_id")
            task = global_task_manager.get_task(task_id)
            if task:
                task.status = "completed"
        except (TypeError, ValueError):
            pass

    for task_id, task in global_task_manager.active_tasks.items():
        if task.status == "running":
            task.future.cancel()
            print(f"[系统] Worker 超时，已停止：{task_id}")


def _cleanup_workers() -> None:
    from core.task_manager import global_task_manager

    for task in global_task_manager.active_tasks.values():
        if task.status == "running":
            task.future.cancel()


async def _input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def main() -> None:
    from server.agent.grapy import build_agent
    from server.agent.node.coordinator import init_snip_tool
    from server.agent.session_storage import (
        create_new_session,
        get_active_session_id,
        global_session_storage,
        list_sessions,
        load_session,
        record_transcript,
        save_session_on_exit,
        switch_to_new_session,
    )
    from server.memory.extractor import extract_memories
    from server.memory.injection import get_memory_context_message

    if not check_config():
        raise SystemExit(1)

    app, connection = await build_agent()
    session_id = get_active_session_id() or create_new_session()
    init_snip_tool(app, lambda: session_id)
    memory_tasks: set[asyncio.Task] = set()

    print("输入问题开始对话；命令：/new、/sessions、/load <id>、/exit")
    try:
        while True:
            query = (await _input("\n你: ")).strip()
            if not query:
                continue
            if query == "/exit":
                break
            if query == "/new":
                _cleanup_workers()
                await global_session_storage.flush()
                session_id = switch_to_new_session()
                print(f"[系统] 新会话：{session_id}")
                continue
            if query == "/sessions":
                for session in list_sessions():
                    print(
                        f"- {session['session_id']} | {session['message_count']} messages"
                    )
                continue
            if query.startswith("/load "):
                target = query.split(maxsplit=1)[1]
                if load_session(target):
                    session_id = target
                    print(f"[系统] 已加载：{session_id}")
                else:
                    print("[系统] 未找到该会话")
                continue

            config = {"configurable": {"thread_id": session_id}}
            state = await app.aget_state(config)
            previous_messages = state.values.get("messages", [])
            previous_count = len(previous_messages)

            memory_context = await get_memory_context_message(
                [*previous_messages, HumanMessage(content=query)]
            )
            input_text = query
            if memory_context:
                input_text = f"{memory_context.content}\n\n用户当前问题：{query}"

            has_workers = await _stream_coordinator(app, input_text, session_id)
            await _apply_pending_snips(app, session_id)
            if has_workers:
                await _wait_for_workers(app, session_id)

            final_state = await app.aget_state(config)
            await record_transcript(session_id, final_state.values.get("messages", []))
            task = asyncio.create_task(extract_memories(app, session_id, previous_count))
            memory_tasks.add(task)
            task.add_done_callback(memory_tasks.discard)
    finally:
        _cleanup_workers()
        if memory_tasks:
            await asyncio.gather(*memory_tasks, return_exceptions=True)
        await global_session_storage.flush()
        save_session_on_exit()
        await connection.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] not in {"chat", "--chat", "-c"}:
        print("仅支持 chat 模式；RAG/ingest 已移除。")
        raise SystemExit(2)
    asyncio.run(main())
