"""Coordinator 节点：负责任务拆解、Worker 编排和结果综合。"""

from contextlib import asynccontextmanager

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from core.session_context import SessionContext
from core.observability.context import TelemetryContext, current_telemetry_context
from core.observability.models import SpanKind
from core.observability.runtime import global_telemetry
from core.skill_loader import skill_loader
from core.tool_registry import physical_tool_manager
from server.agent.llm_factory import get_planner_llm
from server.agent.state import AgentState
from server.memory import global_memory_runtime
from server.tools.task_stop_tool import task_stop_tool
from server.tools.worker_tool import send_message, spawn_worker
from utils.logger import get_logger


logger = get_logger("nlp_agent.coordinator")
_CACHED_SYSTEM_MESSAGE = None
_CACHED_LLM_WITH_TOOLS = None
_CACHED_TOOLSET_KEY = None
_CACHED_SNIP_TOOL = None
_SNIP_APP_REF = None


@asynccontextmanager
async def _observed_span(kind: SpanKind, name: str, config: RunnableConfig, **attributes):
    context = TelemetryContext.from_config(config) or current_telemetry_context()
    if context is None:
        yield None
        return
    async with global_telemetry.span(kind, name, context=context, attributes=attributes) as span:
        yield span


def _get_system_message() -> SystemMessage:
    global _CACHED_SYSTEM_MESSAGE
    if _CACHED_SYSTEM_MESSAGE is not None:
        return _CACHED_SYSTEM_MESSAGE

    available_capabilities = skill_loader.get_planner_listing()
    prompt = f"""你是 nlp-agent 的 Coordinator，负责理解用户目标、拆解任务、调度 Worker 并综合结果。

## 工作原则
- 简单问题直接回答；只有任务可以明确并行、需要独立上下文或耗时较长时才启动 Worker。
- Worker 看不到你与用户的完整对话，发送指令时必须包含完成任务所需的上下文、约束和期望输出。
- 独立子任务可在一条消息中并行启动；有上下文连续性的任务优先用 send_message 继续原 Worker。
- Worker 通知是内部信号。收到结果后直接为用户综合，不要向 Worker 道谢，也不要把未验证的中间结果当成事实。
- 不得虚构工具结果。工具失败时先基于错误信息修正一次，仍失败再向用户说明。
- 当上下文过长且早期内容已经无关时，可以使用 SnipTool 压缩历史。

## 编排工具
- spawn_worker：启动一个新 Worker。默认 join=true：当前会话等待它的结果并由系统批量恢复你；只有结果不影响当前答复的后台工作才设 join=false。
- join=true 时可选择 wait_mode：all 等待全部、any 等待任意一个、quorum 等待指定数量；为等待设置合理的 wait_timeout_s。
- 复杂或高成本任务应显式设置 max_turns、max_duration_s、max_tokens、max_tool_calls；max_attempts 只重试超时、限流、网络或模型瞬时错误。
- send_message：继续已有 Worker，必须传入其 task_id。
- TaskStop：停止仍在运行的 Worker。
- SnipTool：压缩早期无关上下文。

Worker 工具调用会先返回 started，最终结构化结果随后以 [INTERNAL_WORKER_RESULTS] 系统消息到达。started 不是完成结果；请根据 status、error、termination_reason 和 usage 判断是否降级或改派。

## 可分配能力
{available_capabilities}

你的每次对外回复都面向用户。完成信息收集后，由你负责最终判断、综合和表达。
"""
    _CACHED_SYSTEM_MESSAGE = SystemMessage(content=prompt)
    logger.info("Coordinator system prompt cached", chars=len(prompt))
    return _CACHED_SYSTEM_MESSAGE


def init_snip_tool(app) -> None:
    """绑定依赖当前 LangGraph 实例的 SnipTool。"""

    global _SNIP_APP_REF, _CACHED_SNIP_TOOL, _CACHED_LLM_WITH_TOOLS, _CACHED_TOOLSET_KEY
    _SNIP_APP_REF = app
    from server.tools.snip_tool import make_snip_tool

    _CACHED_SNIP_TOOL = make_snip_tool(app)
    physical_tool_manager.register_orchestration_tool(
        _CACHED_SNIP_TOOL, capability="context.manage", replace=True
    )
    _CACHED_LLM_WITH_TOOLS = None
    _CACHED_TOOLSET_KEY = None


def get_coordinator_toolset(config: RunnableConfig | None = None):
    tools = [spawn_worker, send_message, task_stop_tool]
    if _CACHED_SNIP_TOOL is not None:
        tools.append(_CACHED_SNIP_TOOL)
    session_id = (config or {}).get("configurable", {}).get("thread_id", "")
    return physical_tool_manager.get_coordinator_toolset(
        tools,
        session_id=session_id,
        allow_high_risk=True,
    )


def _get_llm_with_tools(config: RunnableConfig):
    global _CACHED_LLM_WITH_TOOLS, _CACHED_SNIP_TOOL, _CACHED_TOOLSET_KEY
    toolset = get_coordinator_toolset(config)
    cache_key = (physical_tool_manager.catalog_revision, toolset.names)
    if _CACHED_LLM_WITH_TOOLS is not None and _CACHED_TOOLSET_KEY == cache_key:
        return _CACHED_LLM_WITH_TOOLS
    _CACHED_LLM_WITH_TOOLS = get_planner_llm().bind_tools(toolset.tools)
    _CACHED_TOOLSET_KEY = cache_key
    return _CACHED_LLM_WITH_TOOLS


async def coordinator_node(state: AgentState, config: RunnableConfig) -> dict:
    system_message = _get_system_message()
    session = SessionContext.from_config(config, require=True)
    async with _observed_span(SpanKind.MEMORY, "memory.inject", config) as memory_span:
        memory_message = global_memory_runtime.context_message(session)
        if memory_span is not None:
            memory_span.annotate(injected=memory_message is not None)
    messages = [system_message]
    if memory_message is not None:
        messages.append(memory_message)
    messages.extend(state.get("messages", []))

    from server.agent.compression.context_manager import global_context_manager
    from utils.tokens import build_context_budget

    state_modifiers = []
    toolset = get_coordinator_toolset(config)
    active_model = _get_llm_with_tools(config)
    context_window = active_model.context_window_tokens
    output_reserve = active_model.max_output_tokens
    budget = build_context_budget(
        context_window=context_window,
        output_reserve=output_reserve,
        tools=toolset.tools,
    )
    async with _observed_span(SpanKind.COMPRESSION, "context.prepare", config) as compression_span:
        transform = await global_context_manager.prepare(session, messages, budget)
        if compression_span is not None:
            compression_span.annotate(
                tokens_before=transform.tokens_before,
                tokens_after=transform.tokens_after,
                tokens_saved=max(0, transform.tokens_before - transform.tokens_after),
                actions=transform.actions,
                removed_messages=len(transform.removed_message_ids),
            )
    if transform.removed_message_ids:
        from langchain_core.messages import RemoveMessage

        state_modifiers.extend(
            RemoveMessage(id=message_id) for message_id in transform.removed_message_ids
        )
        for message in transform.messages:
            if message not in messages:
                state_modifiers.append(message)
    messages = transform.messages

    response = await active_model.ainvoke(messages, config=config)
    return {"messages": [*state_modifiers, response]}
