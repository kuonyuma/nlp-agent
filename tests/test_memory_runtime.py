import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.session_context import LocalContextStateRepository
from core.session_context import SessionContext
from server.agent.compression.context_collapse import CollapseCommit
from server.agent.compression.context_manager import ContextManager
from server.memory.curator import MemoryCurator
from server.memory.manager import MemoryManager
from server.memory.mysql_manager import MySQLMemoryManager
from server.memory.runtime import MemoryRuntime
from server.memory.types import (
    MemoryCurationResult,
    MemoryCuratorOperation,
    MemoryRuntimeConfig,
    MemoryArchiveRecord,
    MemoryScopeKind,
)
from utils.tokens import ContextBudget


def context(
    session_id: str,
    *,
    user_id: str = "alice",
    workspace_id: str = "nlp",
    agent_id: str = "coordinator",
) -> SessionContext:
    return SessionContext(
        session_id=session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )


def test_user_memory_is_private_and_workspace_memory_is_shared(tmp_path):
    alice = MemoryManager(context("a", user_id="alice"), tmp_path)
    bob = MemoryManager(context("b", user_id="bob"), tmp_path)
    other = MemoryManager(context("c", user_id="alice", workspace_id="other"), tmp_path)

    alice.save_memory_topic(
        "language.md",
        "The user prefers Chinese responses.",
        "preference",
        "Response language",
    )
    alice.save_memory_topic(
        "architecture.md",
        "The project uses Coordinator and Worker agents.",
        "project",
        "Agent architecture",
    )

    assert "Chinese" in alice.read_memory_topic("language.md")
    with pytest.raises(FileNotFoundError):
        bob.read_memory_topic("language.md")
    assert "Coordinator" in bob.read_memory_topic("architecture.md")
    with pytest.raises(FileNotFoundError):
        other.read_memory_topic("architecture.md")


def test_memory_is_injected_directly_without_a_selector_model(tmp_path):
    ctx = context("session-one")
    runtime = MemoryRuntime(
        root=tmp_path,
        config=MemoryRuntimeConfig(max_injection_tokens=2_000, recent_archive_tokens=500),
    )
    runtime.manager(ctx).save_memory_topic(
        "commits.md",
        "Use one independently understandable change per commit.",
        "preference",
        "Commit style",
    )

    message = runtime.context_message(ctx)
    assert message is not None
    assert "independently understandable" in message.content
    assert message.additional_kwargs["transient"] is True
    assert runtime.context_message(ctx.model_copy(update={"agent_id": "worker-1"})) is None


def test_archives_are_session_filtered_and_source_idempotent(tmp_path):
    first = MemoryManager(context("one"), tmp_path)
    second = MemoryManager(context("two"), tmp_path)
    row = first.append_archive(source_id="collapse:1", summary="First session summary")
    duplicate = first.append_archive(source_id="collapse:1", summary="Different text")
    second.append_archive(source_id="collapse:2", summary="Second session summary")

    assert duplicate.archive_id == row.archive_id
    assert [item.summary for item in first.read_archives(session_id="one")] == [
        "First session summary"
    ]
    assert [item.cursor for item in second.read_archives()] == [1, 2]


def test_mysql_memory_injection_includes_only_current_session_archives(monkeypatch):
    manager = MySQLMemoryManager.__new__(MySQLMemoryManager)
    manager.context = context("current")
    archives = [
        MemoryArchiveRecord(
            cursor=1,
            source_id="current-summary",
            workspace_id="nlp",
            user_id="alice",
            session_id="current",
            summary="Current session compressed decision.",
        )
    ]
    monkeypatch.setattr(manager, "load_memory_index", lambda: "# Memory Index")
    monkeypatch.setattr(manager, "scan_memory_headers", lambda: [])
    monkeypatch.setattr(manager, "get_curator_cursor", lambda: 0)

    def read_archives(*, since_cursor=0, session_id=None):
        assert since_cursor == 0
        assert session_id == "current"
        return archives

    monkeypatch.setattr(manager, "read_archives", read_archives)

    injected = manager.build_injection_text(
        max_tokens=500,
        max_topics=0,
        recent_archive_tokens=200,
    )

    assert "Current session compressed decision." in injected


@pytest.mark.asyncio
async def test_runtime_schedules_low_frequency_curator(tmp_path):
    called = asyncio.Event()

    class FakeCurator:
        async def curate(self, _context, _manager):
            called.set()
            return 0

    runtime = MemoryRuntime(
        root=tmp_path,
        config=MemoryRuntimeConfig(curate_after_archives=2),
        curator=FakeCurator(),
    )
    ctx = context("one")
    runtime.archive_summary(ctx, source_id="one", summary="one")
    assert not called.is_set()
    runtime.archive_summary(ctx, source_id="two", summary="two")
    await asyncio.wait_for(called.wait(), 1)
    await runtime.close()


@pytest.mark.asyncio
async def test_curator_requires_evidence_confidence_and_never_auto_deletes(
    tmp_path, monkeypatch
):
    ctx = context("one")
    manager = MemoryManager(ctx, tmp_path)
    evidence = manager.append_archive(
        source_id="collapse:1",
        summary="The user explicitly prefers Chinese responses.",
    )
    result = MemoryCurationResult(
        operations=[
            MemoryCuratorOperation(
                operation="add",
                scope=MemoryScopeKind.USER,
                filename="language.md",
                memory_type="preference",
                description="Response language",
                content="The user prefers Chinese responses.",
                evidence_archive_ids=[evidence.archive_id],
                confidence=0.95,
            ),
            MemoryCuratorOperation(
                operation="add",
                scope=MemoryScopeKind.USER,
                filename="unsupported.md",
                memory_type="preference",
                description="Unsupported",
                content="Unsupported inference.",
                evidence_archive_ids=[],
                confidence=1,
            ),
            MemoryCuratorOperation(
                operation="delete",
                scope=MemoryScopeKind.USER,
                filename="language.md",
                memory_type="preference",
                description="Delete",
                evidence_archive_ids=[evidence.archive_id],
                confidence=1,
            ),
        ]
    )

    class FakeLLM:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return result

    monkeypatch.setattr("server.memory.curator.get_tool_llm", lambda: FakeLLM())
    applied = await MemoryCurator().curate(ctx, manager)

    assert applied == 1
    assert "Chinese" in manager.read_memory_topic("language.md")
    with pytest.raises(FileNotFoundError):
        manager.read_memory_topic("unsupported.md")
    assert manager.get_curator_cursor() == evidence.cursor


@pytest.mark.asyncio
async def test_curator_advances_only_the_processed_batch(tmp_path, monkeypatch):
    ctx = context("one")
    manager = MemoryManager(ctx, tmp_path)
    for index in range(51):
        manager.append_archive(source_id=f"source:{index}", summary=f"summary {index}")

    class EmptyLLM:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _messages):
            return MemoryCurationResult()

    monkeypatch.setattr("server.memory.curator.get_tool_llm", lambda: EmptyLLM())
    curator = MemoryCurator()
    await curator.curate(ctx, manager)
    assert manager.get_curator_cursor() == 50
    await curator.curate(ctx, manager)
    assert manager.get_curator_cursor() == 51


def test_secret_like_content_is_rejected(tmp_path):
    manager = MemoryManager(context("one"), tmp_path)
    with pytest.raises(ValueError, match="secret"):
        manager.save_memory_topic(
            "secret.md",
            "api_key=do-not-store-this",
            "preference",
            "secret",
        )


def test_legacy_root_topics_are_copied_into_default_workspace(tmp_path):
    legacy = tmp_path / "legacy-project.md"
    legacy.write_text(
        "---\nname: legacy-project\ndescription: Legacy project\ntype: project\n---\n\nKeep me.\n",
        encoding="utf-8",
    )
    (tmp_path / "MEMORY.md").write_text("# Legacy index\n", encoding="utf-8")
    legacy_user = tmp_path / "legacy-preference.md"
    legacy_user.write_text(
        "---\nname: legacy-preference\ndescription: Legacy preference\n"
        "type: preference\n---\n\nPrivate preference.\n",
        encoding="utf-8",
    )

    manager = MemoryManager(
        SessionContext(session_id="one", user_id="local", workspace_id="default"),
        tmp_path,
    )

    assert "Keep me" in manager.read_memory_topic(
        "legacy-project.md", MemoryScopeKind.WORKSPACE
    )
    assert legacy.exists()  # Migration is copy-only so rollback stays possible.
    assert "Private preference" in manager.read_memory_topic(
        "legacy-preference.md", MemoryScopeKind.USER
    )
    other_user = MemoryManager(
        SessionContext(session_id="two", user_id="bob", workspace_id="default"),
        tmp_path,
    )
    with pytest.raises(FileNotFoundError):
        other_user.read_memory_topic("legacy-preference.md")
    assert (tmp_path / ".scoped-memory-migrated").exists()


@pytest.mark.asyncio
async def test_context_collapse_archives_summary_with_session_scope(tmp_path, monkeypatch):
    archived = []

    class FakeRuntime:
        def archive_summary(self, context, **payload):
            archived.append((context, payload))

    async def fake_collapse(messages, store, *, input_limit):
        del input_limit
        store.add_commit(
            CollapseCommit(
                collapse_id="collapse-one",
                summary_uuid="summary-one",
                summary_content="The user made a durable project decision.",
                first_msg_uuid=messages[0].id,
                last_msg_uuid=messages[-1].id,
            )
        )
        return messages

    monkeypatch.setattr(
        "server.agent.compression.context_manager.apply_collapses_if_needed",
        fake_collapse,
    )
    monkeypatch.setattr("server.memory.runtime.global_memory_runtime", FakeRuntime())
    manager = ContextManager(LocalContextStateRepository(tmp_path / "contexts"))
    ctx = context("session-one")
    messages = [
        HumanMessage(content="decision", id="human-one"),
        AIMessage(content="acknowledged", id="assistant-one"),
    ]

    await manager.prepare(
        ctx,
        messages,
        ContextBudget(context_window=10_000, output_reserve=1_000),
    )

    assert archived[0][0] == ctx
    assert archived[0][1]["source_id"] == "collapse:collapse-one"
    assert archived[0][1]["source_message_ids"] == ("human-one", "assistant-one")
