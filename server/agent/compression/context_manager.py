"""Per-session five-layer context governance for model-facing message views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from core.session_context import (
    LocalContextStateRepository,
    PersistedContextState,
    SessionContext,
    local_context_repository,
)
from server.agent.compression.auto_compact import autocompact_if_needed
from server.agent.compression.context_collapse import CollapseStore, apply_collapses_if_needed
from server.agent.compression.micro_compact import micro_compact_if_needed
from utils.logger import get_logger
from utils.tokens import ContextBudget, rough_estimation_for_messages


logger = get_logger("nlp_agent.context_manager")


@dataclass
class ContextTransform:
    session: SessionContext
    messages: list[BaseMessage]
    tokens_before: int
    tokens_after: int
    actions: list[str] = field(default_factory=list)
    removed_message_ids: list[str] = field(default_factory=list)


class ContextManager:
    def __init__(self, repository: LocalContextStateRepository = local_context_repository) -> None:
        self.repository = repository
        self._stores: dict[str, CollapseStore] = {}

    def _store(self, context: SessionContext, state: PersistedContextState) -> CollapseStore:
        store = self._stores.get(context.storage_key)
        if store is None:
            store = CollapseStore()
            store.load_commits(state.collapse_commits)
            self._stores[context.storage_key] = store
        return store

    async def prepare(
        self,
        context: SessionContext,
        messages: list[BaseMessage],
        budget: ContextBudget,
    ) -> ContextTransform:
        async with self.repository.lock_for(context):
            state = self.repository.load(context)
            store = self._store(context, state)
            before = rough_estimation_for_messages(messages)
            view = list(messages)
            actions: list[str] = []

            micro = micro_compact_if_needed(
                view,
                force=before >= budget.threshold(0.60),
            )
            if micro.tools_cleared:
                view = micro.messages
                actions.append(f"micro_compact:{micro.tools_cleared}")

            commit_count = len(store.commits)
            view = await apply_collapses_if_needed(
                view,
                store,
                input_limit=budget.input_limit,
            )
            if len(store.commits) > commit_count:
                new_commits = store.commits[commit_count:]
                actions.append(f"collapse:{len(new_commits)}")
                state = state.model_copy(
                    update={
                        "collapse_commits": [
                            {
                                "collapse_id": item.collapse_id,
                                "summary_uuid": item.summary_uuid,
                                "summary_content": item.summary_content,
                                "first_msg_uuid": item.first_msg_uuid,
                                "last_msg_uuid": item.last_msg_uuid,
                            }
                            for item in store.commits
                        ]
                    }
                )
                self.repository.save(context, state)
                from server.memory.runtime import global_memory_runtime

                for item in new_commits:
                    global_memory_runtime.archive_summary(
                        context,
                        source_id=f"collapse:{item.collapse_id}",
                        summary=item.summary_content,
                        source_message_ids=(item.first_msg_uuid, item.last_msg_uuid),
                    )

            compact = await autocompact_if_needed(
                view,
                threshold=budget.threshold(0.93),
                session_id=context.storage_key,
            )
            removed: list[str] = []
            if compact.was_compacted:
                removed = [
                    message.id
                    for message in view
                    if message.id and message not in compact.messages
                ]
                view = compact.messages
                actions.append("auto_compact")
                if compact.summary:
                    from server.memory.runtime import global_memory_runtime

                    global_memory_runtime.archive_summary(
                        context,
                        source_id=f"auto_compact:{removed[0] if removed else context.session_id}",
                        summary=compact.summary,
                        source_message_ids=tuple(removed),
                    )

            if rough_estimation_for_messages(view) > budget.input_limit:
                view = trim_legal_history(view, budget.input_limit)
                actions.append("hard_trim")

            return ContextTransform(
                session=context,
                messages=view,
                tokens_before=before,
                tokens_after=rough_estimation_for_messages(view),
                actions=actions,
                removed_message_ids=removed,
            )

    async def inspect(self, context: SessionContext) -> PersistedContextState:
        async with self.repository.lock_for(context):
            return self.repository.load(context)

    async def clear(self, context: SessionContext) -> None:
        async with self.repository.lock_for(context):
            self._stores.pop(context.storage_key, None)
            self.repository.delete(context)


def trim_legal_history(messages: list[BaseMessage], token_limit: int) -> list[BaseMessage]:
    """Keep system messages and newest complete user turns within a hard budget."""
    if rough_estimation_for_messages(messages) <= token_limit:
        return messages
    systems = [message for message in messages if isinstance(message, SystemMessage)]
    conversation = [message for message in messages if not isinstance(message, SystemMessage)]
    turns: list[list[BaseMessage]] = []
    current: list[BaseMessage] = []
    for message in conversation:
        if isinstance(message, HumanMessage) and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)

    fixed = rough_estimation_for_messages(systems)
    kept: list[list[BaseMessage]] = []
    used = fixed
    for turn in reversed(turns):
        legal = _legalize_turn(turn)
        cost = rough_estimation_for_messages(legal)
        if kept and used + cost > token_limit:
            break
        if not kept or used + cost <= token_limit:
            kept.append(legal)
            used += cost
    kept.reverse()
    result = systems + [message for turn in kept for message in turn]
    logger.info(
        "Hard context trim completed",
        original=len(messages),
        kept=len(result),
        estimated_tokens=rough_estimation_for_messages(result),
    )
    return result


def _legalize_turn(turn: list[BaseMessage]) -> list[BaseMessage]:
    declared: set[str] = set()
    completed: set[str] = {
        message.tool_call_id for message in turn if isinstance(message, ToolMessage)
    }
    output: list[BaseMessage] = []
    for message in turn:
        if isinstance(message, AIMessage) and message.tool_calls:
            ids = {str(call.get("id")) for call in message.tool_calls if call.get("id")}
            if not ids.issubset(completed):
                continue
            declared.update(ids)
        if isinstance(message, ToolMessage) and message.tool_call_id not in declared:
            continue
        output.append(message)
    while output and isinstance(output[0], (AIMessage, ToolMessage)):
        output.pop(0)
    return output


global_context_manager = ContextManager()
