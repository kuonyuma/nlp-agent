"""Low-frequency memory curation from trusted session archive summaries."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from core.session_context import SessionContext
from server.agent.llm_factory import get_tool_llm
from server.memory.manager import MemoryManager
from server.memory.types import MemoryCurationResult, MemoryScopeKind
from utils.logger import get_logger


logger = get_logger("nlp_agent.memory.curator")


class MemoryCurator:
    """Turn append-only archives into small, durable Markdown topics."""

    async def curate(self, context: SessionContext, manager: MemoryManager) -> int:
        cursor = manager.get_curator_cursor()
        archives = manager.read_archives(since_cursor=cursor)
        if not archives:
            return 0

        batch = archives[:50]
        allowed_evidence = {row.archive_id for row in batch}
        archive_text = "\n\n".join(
            f"ARCHIVE {row.archive_id} session={row.session_id}\n{row.summary}"
            for row in batch
        )
        system = SystemMessage(
            content=(
                "You are a conservative long-term memory curator. Keep only information "
                "that will change future agent behavior across sessions: explicit stable "
                "user profile facts, preferences, corrections, durable project decisions, "
                "constraints, or ongoing goals. Ignore transient tasks, logs, tool output, "
                "web facts that can be searched again, secrets, credentials, and model "
                "inferences. Never repeat recalled memory as new evidence. User/profile/"
                "preference/feedback belongs to user scope; project/decision/goal belongs "
                "to workspace scope. Prefer update over duplicate add. Do not delete memory "
                "automatically. Every non-ignore operation needs archive evidence and at "
                "least 0.8 confidence. Return an empty operation list when nothing qualifies."
            )
        )
        prompt = HumanMessage(
            content=(
                "Current scoped durable memory:\n"
                f"{manager.build_injection_text(max_tokens=12_000, max_topics=30, recent_archive_tokens=0)}\n\n"
                f"New archive summaries:\n{archive_text}"
            )
        )
        result = await get_tool_llm().with_structured_output(MemoryCurationResult).ainvoke(
            [system, prompt]
        )

        applied = 0
        for operation in result.operations if result else []:
            evidence = set(operation.evidence_archive_ids)
            if operation.operation in {"ignore", "delete"}:
                continue
            if (
                operation.confidence < 0.8
                or not evidence
                or not evidence.issubset(allowed_evidence)
            ):
                continue
            expected_scope = (
                MemoryScopeKind.WORKSPACE
                if operation.memory_type in {"project", "decision", "goal"}
                else MemoryScopeKind.USER
            )
            if operation.scope != expected_scope:
                continue
            try:
                manager.apply_curator_operation(operation)
                applied += 1
            except Exception as error:
                logger.warning(
                    "Memory curator operation rejected",
                    filename=operation.filename,
                    error=str(error),
                )

        # A clean curator response consumes the batch even when it intentionally
        # produces no durable memory. Failed LLM calls never reach this point.
        manager.set_curator_cursor(batch[-1].cursor)
        return applied
