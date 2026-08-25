from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest


def _config(*, user_id: str = "local", session_id: str = "model-session") -> dict:
    return {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id,
            "workspace_id": "default",
        }
    }


@pytest.mark.asyncio
async def test_database_scratch_does_not_require_interactive_lease() -> None:
    from server.infrastructure.mysql.models import SandboxExecutionModel, SessionModel, UserModel
    from server.sandbox.model_tools import SandboxModelToolService

    now = datetime.now(UTC).replace(tzinfo=None)

    class FakeSession:
        def __init__(self) -> None:
            self.execution: object | None = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, model, identifier, **_kwargs):
            if model is SessionModel:
                return SimpleNamespace(
                    id=identifier,
                    user_id="local",
                    workspace_id="default",
                    revoked_at=None,
                    expires_at=now + timedelta(minutes=5),
                    authorization_version=1,
                )
            if model is UserModel:
                return SimpleNamespace(
                    id="local",
                    authorization_version=1,
                    status="active",
                    deleted_at=None,
                )
            if model is SandboxExecutionModel:
                return self.execution
            return None

        async def scalar(self, _statement):
            return None

        def add(self, item):
            if isinstance(item, SandboxExecutionModel):
                self.execution = item

        async def flush(self):
            return None

    session = FakeSession()

    class Factory:
        def __call__(self):
            return session

        def begin(self):
            return session

    service = SandboxModelToolService(mode="inmemory", session_factory=Factory())
    result = await service.run_scratch(source="print(2 + 2)", config=_config())

    assert result["ok"] is True
    assert result["execution_id"]
    assert session.execution is not None
    assert session.execution.lease_id is None


@pytest.mark.asyncio
async def test_model_scratch_does_not_share_interactive_kernel() -> None:
    from server.sandbox.model_tools import SandboxModelToolService

    service = SandboxModelToolService(mode="inmemory")
    context = _config()
    from server.sandbox.confirmation import SandboxConfirmationSigner

    token = SandboxConfirmationSigner("phase4-local-sandbox-secret").issue(
        user_id="local",
        session_id="model-session",
        tool_name="sandbox_run_active_kernel",
        code_hash=hashlib.sha256(
            "answer = 41\nprint(answer + 1)".encode("utf-8")
        ).hexdigest(),
    )

    active = await service.run_active(
        source="answer = 41\nprint(answer + 1)",
        config=context,
        confirmed=True,
        confirmation_token=token,
    )
    scratch = await service.run_scratch(source="print('answer' in globals())", config=context)

    assert active["ok"] is True
    assert "42" in active["stdout"]
    replayed = await service.run_active(
        source="answer = 41\nprint(answer + 1)",
        config=context,
        confirmed=True,
        confirmation_token=token,
    )
    assert replayed["code"] == "confirmation_required"
    assert scratch["ok"] is True
    assert scratch["stdout"].strip() == "False"
    assert scratch["execution_id"]
    explanation = await service.explain_execution(
        execution_id=str(scratch["execution_id"]), config=context
    )
    assert explanation["ok"] is True
    assert explanation["execution"]["status"] == "completed"
    assert any(event["type"] == "execution.completed" for event in explanation["events"])


@pytest.mark.asyncio
async def test_active_kernel_requires_explicit_confirmation() -> None:
    from server.sandbox.model_tools import SandboxModelToolService

    service = SandboxModelToolService(mode="inmemory")

    result = await service.run_active(source="print(1)", config=_config(), confirmed=False)

    assert result == {
        "ok": False,
        "code": "confirmation_required",
        "error": "sandbox_run_active_kernel requires explicit user confirmation",
    }


def test_confirmation_token_is_bound_to_user_session_tool_and_code() -> None:
    from server.sandbox.confirmation import SandboxConfirmationSigner

    signer = SandboxConfirmationSigner("test-secret")
    token = signer.issue(
        user_id="local", session_id="model-session", tool_name="sandbox_reset", code_hash=""
    )
    signer.verify(
        token,
        user_id="local",
        session_id="model-session",
        tool_name="sandbox_reset",
        code_hash="",
    )
    with pytest.raises(PermissionError):
        signer.verify(
            token,
            user_id="local",
            session_id="model-session",
            tool_name="sandbox_run_active_kernel",
            code_hash="deadbeef",
        )


@pytest.mark.asyncio
async def test_active_kernel_rejects_boolean_without_server_confirmation_token() -> None:
    from server.sandbox.model_tools import SandboxModelToolService

    service = SandboxModelToolService(mode="inmemory")
    result = await service.run_active(
        source="print(1)", config=_config(), confirmed=True, confirmation_token=None
    )
    assert result["code"] == "confirmation_required"


def test_model_tool_contracts_are_registered_and_hide_runtime_config() -> None:
    from core.tool_registry import physical_tool_manager

    expected = {
        "sandbox_status",
        "sandbox_run_scratch",
        "sandbox_explain_execution",
        "sandbox_interrupt_own",
        "sandbox_run_active_kernel",
        "sandbox_reset",
    }

    assert expected.issubset({item.name for item in physical_tool_manager.runtime.catalog.descriptors()})
    for name in expected:
        descriptor = physical_tool_manager.runtime.catalog.get(name)
        assert descriptor is not None
        assert "config" not in descriptor.instantiate().args_schema.model_json_schema()["properties"]


def test_model_sandbox_helpers_are_event_loop_safe() -> None:
    from server.sandbox.model_tools import SandboxModelToolService

    service = SandboxModelToolService(mode="inmemory")
    result = asyncio.run(service.run_scratch(source="print(2 + 2)", config=_config()))

    assert result["stdout"].strip() == "4"
