from __future__ import annotations

import asyncio

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
async def test_model_scratch_does_not_share_interactive_kernel() -> None:
    from server.sandbox.model_tools import SandboxModelToolService

    service = SandboxModelToolService(mode="inmemory")
    context = _config()

    active = await service.run_active(source="answer = 41\nprint(answer + 1)", config=context, confirmed=True)
    scratch = await service.run_scratch(source="print('answer' in globals())", config=context)

    assert active["ok"] is True
    assert "42" in active["stdout"]
    assert scratch["ok"] is True
    assert scratch["stdout"].strip() == "False"


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
