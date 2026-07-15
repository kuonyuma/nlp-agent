"""Interactive entry point for the session-serialized Coordinator runtime."""

import asyncio
import sys
import uuid

from langchain_core.messages import AIMessageChunk, HumanMessage


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
        print("Missing DEEPSEEK_API_KEY; create .env in the project root.")
        return False
    return True


async def _apply_pending_snips(app, session_id: str) -> None:
    """Keep the existing SnipTool post-processing at each Coordinator boundary."""
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
            result = snip_by_id_range(messages, to_id=args["to_id"], from_id=args.get("from_id"))
            if result.tokens_freed:
                await app.aupdate_state(config, {"messages": result.messages})
                print(f"[system] Snip freed about {result.tokens_freed:,} tokens")
            message.additional_kwargs["_snip_applied"] = True
            return


def _cleanup_workers() -> None:
    from core.task_manager import global_task_manager

    for task in global_task_manager.active_tasks.values():
        if task.status == "running":
            task.future.cancel()


async def _input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def main() -> None:
    from core.coordinator_runtime import CoordinatorRuntime
    from core.worker_events import global_worker_event_bus
    from server.agent.grapy import build_agent
    from server.agent.node.coordinator import init_snip_tool
    from server.agent.session_storage import (
        create_new_session,
        get_active_session_id,
        global_session_storage,
        list_sessions,
        record_transcript,
        save_session_on_exit,
        switch_to_new_session,
        load_session,
    )
    from server.memory.extractor import extract_memories
    from server.memory.injection import get_memory_context_message
    from server.agent.compression.snip_compact import derive_short_id

    if not check_config():
        raise SystemExit(1)

    app, connection = await build_agent()
    active_session = {"id": get_active_session_id() or create_new_session()}
    init_snip_tool(app, lambda: active_session["id"])

    async def invoke(messages, session_id: str, background: bool, turn_id: str) -> None:
        """The only Coordinator invocation path used by this process."""
        active_session["id"] = session_id
        config = {"configurable": {"thread_id": session_id, "turn_id": turn_id}}
        printed = False
        prefix = "\nAgent: " if not background else "\nAgent (worker update): "
        async for event in app.astream_events({"messages": messages}, config=config, version="v2"):
            if event["event"] != "on_chat_model_stream":
                continue
            if event.get("metadata", {}).get("langgraph_node") != "coordinator":
                continue
            chunk = event["data"].get("chunk")
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                if not printed:
                    print(prefix, end="", flush=True)
                    printed = True
                print(chunk.content, end="", flush=True)
        if printed:
            print()
        await _apply_pending_snips(app, session_id)

    runtime = CoordinatorRuntime(global_worker_event_bus, invoke)
    memory_tasks: set[asyncio.Task] = set()

    print("Enter a question. Commands: /new, /sessions, /load <id>, /exit")
    try:
        while True:
            query = (await _input("\nYou: ")).strip()
            if not query:
                continue
            if query == "/exit":
                break
            if query == "/new":
                _cleanup_workers()
                await global_session_storage.flush()
                active_session["id"] = switch_to_new_session()
                print(f"[system] New session: {active_session['id']}")
                continue
            if query == "/sessions":
                for session in list_sessions():
                    print(f"- {session['session_id']} | {session['message_count']} messages")
                continue
            if query.startswith("/load "):
                target = query.split(maxsplit=1)[1]
                if load_session(target):
                    active_session["id"] = target
                    print(f"[system] Loaded: {target}")
                else:
                    print("[system] Session not found")
                continue

            session_id = active_session["id"]
            config = {"configurable": {"thread_id": session_id}}
            state = await app.aget_state(config)
            previous_messages = state.values.get("messages", [])
            previous_count = len(previous_messages)
            memory_context = await get_memory_context_message(
                [*previous_messages, HumanMessage(content=query)]
            )
            content = query
            if memory_context:
                content = f"{memory_context.content}\n\nCurrent user request: {query}"

            message_id = str(uuid.uuid4())
            message = HumanMessage(
                content=f"{content} [id:{derive_short_id(message_id)}]", id=message_id
            )
            await runtime.submit_user_turn(session_id, message)

            final_state = await app.aget_state(config)
            await record_transcript(session_id, final_state.values.get("messages", []))
            task = asyncio.create_task(extract_memories(app, session_id, previous_count))
            memory_tasks.add(task)
            task.add_done_callback(memory_tasks.discard)
    finally:
        _cleanup_workers()
        await runtime.close()
        if memory_tasks:
            await asyncio.gather(*memory_tasks, return_exceptions=True)
        await global_session_storage.flush()
        save_session_on_exit()
        await connection.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] not in {"chat", "--chat", "-c"}:
        print("Only chat mode is supported.")
        raise SystemExit(2)
    asyncio.run(main())
