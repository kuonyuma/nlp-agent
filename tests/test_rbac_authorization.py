from __future__ import annotations

import pytest

from core.identity import AccessDeniedError, AuthenticatedPrincipal
from core.rbac import AuthorizationService, Permission
from server.rbac.catalog import (
    ROLE_NAMES,
    permission_id,
    permission_row,
    role_id,
    role_permission_rows,
    role_permission_scope_rows,
)


def principal(*roles: str, workspaces: tuple[str, ...] = ("class-a",)) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="learner-1",
        workspace_ids=frozenset(workspaces),
        roles=frozenset(roles),
    )


def test_guest_can_only_use_public_capabilities() -> None:
    authorization = AuthorizationService()

    assert authorization.allowed(
        principal("guest"), Permission.LEARNING_CONTENT_READ_PUBLIC
    )
    assert not authorization.allowed(principal("guest"), Permission.AGENT_TURN_SUBMIT)


def test_student_capabilities_include_guest_baseline_but_not_teacher_actions() -> None:
    authorization = AuthorizationService()

    assert authorization.allowed(principal("student"), Permission.AGENT_TURN_SUBMIT)
    assert authorization.allowed(
        principal("student"), Permission.LEARNING_CONTENT_READ_PUBLIC
    )
    assert not authorization.allowed(
        principal("student"), Permission.LEARNING_CONTENT_MANAGE
    )


def test_multiple_roles_combine_capabilities() -> None:
    authorization = AuthorizationService()

    assert authorization.allowed(
        principal("student", "teacher"), Permission.LEARNING_CONTENT_MANAGE
    )
    assert authorization.allowed(
        principal("student", "teacher"), Permission.AGENT_TURN_SUBMIT
    )


def test_developer_has_system_capabilities_without_implicit_sensitive_data_access() -> None:
    authorization = AuthorizationService()

    assert authorization.allowed(principal("developer"), Permission.SYSTEM_ROLE_MANAGE)
    assert authorization.allowed(principal("developer"), Permission.SYSTEM_RUNTIME_INSPECT)
    assert not authorization.allowed(
        principal("developer"), Permission.SYSTEM_SENSITIVE_DATA_READ
    )


def test_require_reports_a_stable_access_denied_error() -> None:
    authorization = AuthorizationService()

    with pytest.raises(AccessDeniedError, match="learning:content:manage"):
        authorization.require(principal("student"), Permission.LEARNING_CONTENT_MANAGE)


def test_workspace_scope_is_checked_after_capability() -> None:
    authorization = AuthorizationService()

    authorization.require(
        principal("teacher"),
        Permission.LEARNING_CONTENT_MANAGE,
        workspace_id="class-a",
    )
    with pytest.raises(AccessDeniedError, match="workspace"):
        authorization.require(
            principal("teacher"),
            Permission.LEARNING_CONTENT_MANAGE,
            workspace_id="class-b",
        )


def test_builtin_catalog_has_stable_ids_and_complete_role_permission_rows() -> None:
    assert set(ROLE_NAMES) == {"guest", "student", "teacher", "developer"}
    assert role_id("student") == role_id("student")
    assert permission_id(Permission.AGENT_TURN_SUBMIT) == permission_id(
        Permission.AGENT_TURN_SUBMIT
    )
    assert permission_row(Permission.AGENT_TURN_SUBMIT)["code"] == "agent:turn:submit"
    assert len(role_permission_rows()) == len(role_permission_scope_rows())
