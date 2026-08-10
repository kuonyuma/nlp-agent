"""Keep model-facing tool calls and results structurally valid."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def remove_orphaned_tool_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Drop tool-call fragments whose matching half crossed a compression boundary."""
    completed = {
        message.tool_call_id
        for message in messages
        if isinstance(message, ToolMessage)
    }
    declared: set[str] = set()
    output: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            call_ids = {
                str(call["id"])
                for call in message.tool_calls
                if call.get("id")
            }
            if not call_ids.issubset(completed):
                continue
            declared.update(call_ids)
        if isinstance(message, ToolMessage) and message.tool_call_id not in declared:
            continue
        output.append(message)
    return output
