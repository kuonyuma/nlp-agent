from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Coordinator 主图状态，任务和结果统一通过消息流转。"""

    messages: Annotated[list[Any], add_messages]
    session_id: str
    user_query: str
    runtime_turn_id: str
    runtime_started_at: float
    runtime_iterations: int
    runtime_tokens: int
    runtime_tool_calls: int
    runtime_injections: int
    runtime_continue: bool
    runtime_stop_reason: str | None
