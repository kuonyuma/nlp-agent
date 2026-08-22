"""Session title summarization tests (DB-free; LLM mocked).

The summarizer runs as a fire-and-forget background task, so its correctness
rests on three properties exercised here: it only writes when due (>=3 new
turns since the last basis), it never raises on model failure, and every write
is a single-row conditional UPDATE scoped to the exact conversation id (the id
itself already arrived from an authorized turn context, so there is no
cross-tenant write path).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from server.session.summary import (
    _clean_input,
    _clean_title,
    _decide,
    _render_turns,
    _select_turns,
    build_conversation_text,
    generate_and_store_summary,
)


def _turn(turn_id: str, input_text: str, result_text: str | None, completed_at: datetime):
    return SimpleNamespace(
        id=turn_id,
        input_text=input_text,
        result_text=result_text,
        completed_at=completed_at,
        created_at=completed_at,
    )


def _make_turns(n: int, start: datetime) -> list:
    return [
        _turn(
            f"turn-{i}",
            f"问题 {i}",
            f"答案 {i}",
            start + timedelta(seconds=i * 10),
        )
        for i in range(n)
    ]


# --- pure helpers ----------------------------------------------------------


def test_clean_input_strips_learning_context_preamble():
    raw = (
        '<!-- nlp-learning-context:{"topic_name":"Transformer"} -->\n'
        "[学习设置：主题=Transformer；难度=入门；教学方式=讲解]\n"
        "什么是注意力机制？"
    )
    assert _clean_input(raw) == "什么是注意力机制？"


def test_clean_title_strips_quotes_and_markdown():
    assert _clean_title('"## 注意力机制入门"') == "注意力机制入门"
    assert _clean_title("**Transformer 编码器**") == "Transformer 编码器"


def test_select_turns_keeps_first_and_recent():
    turns = _make_turns(6, datetime(2026, 1, 1))
    assert [t.id for t in _select_turns(turns)] == [
        "turn-0",
        "turn-3",
        "turn-4",
        "turn-5",
    ]


def test_render_turns_formats_user_assistant_and_skips_empty():
    turns = [
        _turn("t1", "什么是 BERT？", "BERT 是预训练模型", datetime(2026, 1, 1)),
        _turn("t2", "", None, datetime(2026, 1, 1, 0, 0, 10)),
    ]
    assert _render_turns(turns) == (
        "[user]: 什么是 BERT？\n[assistant]: BERT 是预训练模型"
    )


@pytest.mark.asyncio
async def test_build_conversation_text_uses_first_and_recent(monkeypatch):
    turns = _make_turns(6, datetime(2026, 1, 1))
    factory = _SessionFactory()

    async def fake_load_state(session, session_id):
        return None, turns

    monkeypatch.setattr("server.session.summary._load_state", fake_load_state)

    text = await build_conversation_text("session-1", factory)
    assert "[user]: 问题 0" in text
    assert "[user]: 问题 5" in text
    assert "[user]: 问题 1" not in text


# --- dedup / recompute threshold -------------------------------------------


def test_decide_generates_on_first_turn():
    turns = _make_turns(1, datetime(2026, 1, 1))
    assert _decide(turns, None) == turns[-1].completed_at


def test_decide_skips_below_delta():
    turns = _make_turns(3, datetime(2026, 1, 1))
    assert _decide(turns, turns[0].completed_at) is None


def test_decide_recomputes_at_delta():
    turns = _make_turns(4, datetime(2026, 1, 1))
    assert _decide(turns, turns[0].completed_at) == turns[-1].completed_at


# --- orchestration with mocked LLM + DB ------------------------------------


class _FakeLLM:
    def __init__(self, title: str = "注意力机制入门"):
        self.title = title
        self.invocations: list = []

    async def ainvoke(self, messages, **kwargs):
        self.invocations.append((messages, kwargs))
        return SimpleNamespace(content=self.title)


class _RecordingSession:
    def __init__(self, rowcount: int = 1):
        self.rowcount = rowcount
        self.writes: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, params=None):
        self.writes.append((statement, params))
        result = MagicMock()
        result.rowcount = self.rowcount
        return result


class _SessionFactory:
    def __init__(self, rowcount: int = 1):
        self.session = _RecordingSession(rowcount)

    def __call__(self):
        return self.session

    def begin(self):
        return self.session


def _patch_env(monkeypatch, turns, title_updated_at, llm):
    factory = _SessionFactory()

    async def fake_load_state(session, session_id):
        return title_updated_at, turns

    monkeypatch.setattr("server.session.summary._load_state", fake_load_state)
    monkeypatch.setattr("server.session.summary.get_utility_llm", lambda: llm)
    return factory


@pytest.mark.asyncio
async def test_generate_and_store_writes_title(monkeypatch):
    turns = _make_turns(1, datetime(2026, 1, 1))
    llm = _FakeLLM("注意力机制入门")
    factory = _patch_env(monkeypatch, turns, None, llm)

    assert await generate_and_store_summary("session-1", factory) is True
    assert len(factory.session.writes) == 1

    _statement, params = factory.session.writes[0]
    assert params["id"] == "session-1"
    assert params["title"] == "注意力机制入门"
    assert params["basis"] == turns[0].completed_at


@pytest.mark.asyncio
async def test_generate_skips_below_delta(monkeypatch):
    turns = _make_turns(3, datetime(2026, 1, 1))
    llm = _FakeLLM()
    factory = _patch_env(monkeypatch, turns, turns[0].completed_at, llm)

    assert await generate_and_store_summary("session-1", factory) is False
    assert llm.invocations == []
    assert factory.session.writes == []


@pytest.mark.asyncio
async def test_generate_degrades_on_llm_failure(monkeypatch):
    turns = _make_turns(1, datetime(2026, 1, 1))
    llm = _FakeLLM()

    async def fail_ainvoke(messages, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(llm, "ainvoke", fail_ainvoke)
    factory = _patch_env(monkeypatch, turns, None, llm)

    assert await generate_and_store_summary("session-1", factory) is False
    assert factory.session.writes == []


@pytest.mark.asyncio
async def test_write_is_scoped_to_target_session(monkeypatch):
    turns = _make_turns(1, datetime(2026, 1, 1))
    factory = _patch_env(monkeypatch, turns, None, _FakeLLM("主题"))

    await generate_and_store_summary("session-A", factory)

    statement, params = factory.session.writes[0]
    assert params["id"] == "session-A"
    # Single-row conditional UPDATE keyed only by the conversation id; no
    # cross-session or tenant predicate is bypassed here.
    assert "WHERE id=:id" in str(statement)
    assert "title_updated_at IS NULL OR title_updated_at < :basis" in str(statement)


# --- read-path permission boundary ----------------------------------------


def test_session_list_requires_read_permission_and_exposes_title(monkeypatch):
    from core.rbac import Permission
    from server.agent.session_service import DatabaseSessionService

    requires: list = []
    monkeypatch.setattr(
        "server.agent.session_service.authorization_service.require",
        lambda principal, permission, **kwargs: requires.append((principal, permission)),
    )

    row = SimpleNamespace(
        id="s1",
        created_at=datetime(2026, 1, 1),
        last_message_at=datetime(2026, 1, 2),
        updated_at=datetime(2026, 1, 1),
        owner_user_id="u1",
        workspace_id="ws1",
        channel="web",
        title="注意力机制",
    )

    class _ScalarResult:
        def all(self):
            return [row]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalars(self, statement):
            return _ScalarResult()

    class _Factory:
        def __call__(self):
            return _Session()

    principal = SimpleNamespace(user_id="u1", workspace_ids={"ws1"})
    service = DatabaseSessionService(_Factory())

    items = asyncio.run(service.list(principal))

    assert requires and requires[0][1] == Permission.AGENT_SESSION_READ
    assert items[0]["title"] == "注意力机制"


# --- 15-char cap + first-question fallback --------------------------------


def test_clean_title_truncates_to_fifteen_chars():
    long = "这是一个非常长的对话标题超过了十五个字的限制"
    assert _clean_title(long) == "这是一个非常长的对话标题超过了"


def test_first_question_title_strips_preamble_and_truncates():
    from server.agent.session_service import _first_question_title

    assert _first_question_title("什么是注意力机制？") == "什么是注意力机制？"
    assert _first_question_title("") == ""
    raw = (
        '<!-- nlp-learning-context:{"topic_name":"Transformer"} -->\n'
        "[学习设置：主题=Transformer；难度=入门]\n"
        "什么是注意力机制？"
    )
    assert _first_question_title(raw) == "什么是注意力机制？"
    with_attachment = (
        "什么是注意力机制？\n\n---附件---\n[图片] photo.png\n路径: photo.png\n---附件结束---"
    )
    assert _first_question_title(with_attachment) == "什么是注意力机制？"
    assert _first_question_title("这是一个非常长的用户提问需要被截断到十五个字符以内作为标题") == "这是一个非常长的用户提问需要被…"


def test_session_list_falls_back_to_first_question(monkeypatch):
    from server.agent.session_service import DatabaseSessionService

    monkeypatch.setattr(
        "server.agent.session_service.authorization_service.require",
        lambda principal, permission, **kwargs: None,
    )

    row = SimpleNamespace(
        id="s1",
        created_at=datetime(2026, 1, 1),
        last_message_at=datetime(2026, 1, 2),
        updated_at=datetime(2026, 1, 1),
        owner_user_id="u1",
        workspace_id="ws1",
        channel="web",
        title="",
    )

    class _ScalarResult:
        def all(self):
            return [row]

    class _TurnResult:
        def all(self):
            return [("s1", "什么是注意力机制？")]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalars(self, statement):
            return _ScalarResult()

        async def execute(self, statement):
            return _TurnResult()

    class _Factory:
        def __call__(self):
            return _Session()

    principal = SimpleNamespace(user_id="u1", workspace_ids={"ws1"})
    service = DatabaseSessionService(_Factory())

    items = asyncio.run(service.list(principal))

    assert items[0]["title"] == "什么是注意力机制？"


def _rename_service(monkeypatch):
    from core.session_context import SessionContext
    from server.agent.session_service import DatabaseSessionService

    monkeypatch.setattr(
        "server.agent.session_service.authorization_service.require",
        lambda principal, permission, **kwargs: None,
    )

    async def fake_resolve(self, principal, session_id):
        return SessionContext(
            session_id=session_id,
            user_id=principal.user_id,
            workspace_id="ws1",
            channel="web",
        )

    monkeypatch.setattr(DatabaseSessionService, "resolve", fake_resolve)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, statement):
            return MagicMock()

    class _Factory:
        def begin(self):
            return _Session()

    return DatabaseSessionService(_Factory())


def test_session_rename_updates_title(monkeypatch):
    service = _rename_service(monkeypatch)
    principal = SimpleNamespace(user_id="u1", workspace_ids={"ws1"})

    result = asyncio.run(service.rename(principal, "s1", "  注意力机制入门  "))

    assert result == {"session_id": "s1", "title": "注意力机制入门"}


def test_session_rename_rejects_empty_title(monkeypatch):
    service = _rename_service(monkeypatch)
    principal = SimpleNamespace(user_id="u1", workspace_ids={"ws1"})

    with pytest.raises(ValueError):
        asyncio.run(service.rename(principal, "s1", "   "))
