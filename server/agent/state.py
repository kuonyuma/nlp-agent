from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Coordinator 主图状态，任务和结果统一通过消息流转。"""

    messages: Annotated[list[Any], add_messages]
    session_id: str
    user_query: str

