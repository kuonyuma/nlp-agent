from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from server.quota.contracts import AdmitTurn, FinishTurn
from server.quota.errors import QuotaErrorCode, QuotaRejectedError
from server.quota.management import QuotaManagementService
from server.quota.models import (
    PolicyBindingModel,
    PricingRuleModel,
    QuotaAdjustmentModel,
    QuotaBucketModel,
    QuotaConcurrencyLockModel,
    QuotaGrantModel,
    QuotaLedgerEntryModel,
    QuotaPolicyModel,
    QuotaReservationModel,
    UsageEventModel,
)
from server.quota.service import QuotaService


UTC = timezone.utc
NOW = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)


@pytest.fixture
def quota_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        PricingRuleModel,
        UsageEventModel,
        QuotaPolicyModel,
        PolicyBindingModel,
        QuotaBucketModel,
        QuotaConcurrencyLockModel,
        QuotaReservationModel,
        QuotaLedgerEntryModel,
        QuotaGrantModel,
        QuotaAdjustmentModel,
    ):
        model.__table__.create(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _policy(
    engine,
    *,
    code: str,
    version: str,
    daily: int | None = 100,
    monthly: int | None = 1_000,
    request: int | None = 100,
    concurrency: int | None = 2,
    allowed_profiles: list[str] | None = None,
    max_overdraft: int = 0,
    status: str = "active",
) -> str:
    policy_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            insert(QuotaPolicyModel).values(
                id=policy_id,
                code=code,
                version=version,
                name=code,
                status=status,
                request_limit_micro=request,
                daily_limit_micro=daily,
                monthly_limit_micro=monthly,
                concurrency_limit=concurrency,
                max_overdraft_micro=max_overdraft,
                allowed_model_profiles=allowed_profiles or ["economy"],
                unlimited=False,
                effective_from=NOW,
                effective_until=None,
                created_by="developer-1",
            )
        )
    return policy_id


def _bind(engine, *, subject_type: str, subject_id: str, policy_id: str, priority: int = 10) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(PolicyBindingModel).values(
                id=str(uuid4()),
                subject_type=subject_type,
                subject_id=subject_id,
                policy_id=policy_id,
                priority=priority,
                status="active",
                effective_from=NOW,
                effective_until=None,
            )
        )


def _command(turn_id: str, *, estimated_micro: int = 20) -> AdmitTurn:
    return AdmitTurn(
        request_id=f"request-{turn_id}",
        user_id="user-1",
        workspace_id="workspace-1",
        turn_id=turn_id,
        model_profile="economy",
        model_role="coordinator",
        estimated_input_tokens=10,
        estimated_output_tokens=10,
        estimated_micro=estimated_micro,
        idempotency_key=f"idempotency-{turn_id}",
    )


def test_policy_resolution_returns_one_explainable_base_and_separate_workspace_policy(quota_engine):
    default_id = _policy(quota_engine, code="default", version="1")
    role_a_id = _policy(quota_engine, code="role-a", version="1", daily=200)
    role_b_id = _policy(quota_engine, code="role-b", version="1", daily=300)
    user_id = _policy(quota_engine, code="user-override", version="1", daily=400)
    workspace_id = _policy(quota_engine, code="workspace-budget", version="1", daily=500)
    _bind(quota_engine, subject_type="default", subject_id="*", policy_id=default_id)
    _bind(quota_engine, subject_type="role", subject_id="teacher", policy_id=role_a_id, priority=10)
    _bind(quota_engine, subject_type="role", subject_id="reviewer", policy_id=role_b_id, priority=5)
    _bind(quota_engine, subject_type="user", subject_id="user-1", policy_id=user_id)
    _bind(quota_engine, subject_type="workspace", subject_id="workspace-1", policy_id=workspace_id)

    explanation = QuotaManagementService(quota_engine).explain_policy(
        user_id="user-1",
        workspace_id="workspace-1",
        role_codes=("teacher", "reviewer"),
        at=NOW,
    )

    assert explanation["base"]["policy_id"] == user_id
    assert explanation["base"]["reason"]["subject_type"] == "user"
    assert explanation["workspace"]["policy_id"] == workspace_id
    assert explanation["workspace"]["reason"]["subject_type"] == "workspace"
    assert explanation["candidates"]["role"] == 2


def test_user_and_workspace_buckets_are_reserved_and_settled_together(quota_engine):
    user_policy = _policy(quota_engine, code="user", version="1", daily=100, monthly=None)
    workspace_policy = _policy(quota_engine, code="workspace", version="1", daily=50, monthly=None)
    _bind(quota_engine, subject_type="role", subject_id="student", policy_id=user_policy)
    _bind(quota_engine, subject_type="workspace", subject_id="workspace-1", policy_id=workspace_policy)
    service = QuotaService(quota_engine)

    admitted = service.admit_turn(_command("turn-1", estimated_micro=40), role_codes=("student",), now=NOW)
    assert admitted.allowed is True
    with quota_engine.connect() as connection:
        buckets = connection.execute(select(QuotaBucketModel.__table__)).mappings().all()
    assert {(row["owner_type"], row["owner_id"]) for row in buckets} == {
        ("user", "user-1"),
        ("workspace", "workspace-1"),
    }
    assert all(row["reserved_micro"] == 40 for row in buckets)

    service.finish_turn(
        FinishTurn(
            reservation_id=admitted.reservation_id,
            turn_id="turn-1",
            idempotency_key="finish-1",
        ),
        now=NOW + timedelta(seconds=1),
    )
    snapshot = service.snapshot(user_id="user-1", workspace_id="workspace-1", now=NOW)
    assert {row["owner_type"] for row in snapshot["buckets"]} == {"user", "workspace"}


def test_grant_revoke_expire_and_manual_adjustment_are_idempotent(quota_engine):
    management = QuotaManagementService(quota_engine)
    grant = management.create_grant(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=NOW.replace(hour=0),
        period_end=NOW.replace(hour=0) + timedelta(days=1),
        allocated_micro=100,
        source_type="purchase",
        created_by="developer-1",
        reason="purchase",
        idempotency_key="grant-1",
        effective_from=NOW,
    )
    replay = management.create_grant(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=NOW.replace(hour=0),
        period_end=NOW.replace(hour=0) + timedelta(days=1),
        allocated_micro=100,
        source_type="purchase",
        created_by="developer-1",
        reason="purchase",
        idempotency_key="grant-1",
        effective_from=NOW,
    )
    assert replay["grant_id"] == grant["grant_id"]

    adjustment_input = dict(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=NOW.replace(hour=0),
        period_end=NOW.replace(hour=0) + timedelta(days=1),
        amount_micro=25,
        actor_user_id="developer-1",
        reason="support compensation",
        idempotency_key="adjustment-1",
    )
    adjustment = management.create_adjustment(**adjustment_input)
    assert management.create_adjustment(**adjustment_input)["adjustment_id"] == adjustment["adjustment_id"]

    revoked = management.revoke_grant(grant["grant_id"], actor_user_id="developer-1", idempotency_key="revoke-1")
    assert revoked["status"] == "revoked"
    assert management.revoke_grant(grant["grant_id"], actor_user_id="developer-1", idempotency_key="revoke-1")["status"] == "revoked"

    expiring = management.create_grant(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=NOW.replace(hour=0),
        period_end=NOW.replace(hour=0) + timedelta(days=1),
        allocated_micro=10,
        source_type="grant",
        created_by="developer-1",
        reason="temporary",
        idempotency_key="grant-expiring",
        effective_from=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    assert management.expire_grants(now=NOW + timedelta(minutes=2)) == 1
    assert management.get_grant(expiring["grant_id"])["status"] == "expired"


def test_grant_idempotency_is_scoped_to_owner_without_ledger_collision(quota_engine):
    management = QuotaManagementService(quota_engine)
    period_start = NOW.replace(hour=0)
    period_end = period_start + timedelta(days=1)
    common = dict(
        bucket_type="daily",
        period_start=period_start,
        period_end=period_end,
        allocated_micro=10,
        source_type="grant",
        created_by="developer-1",
        reason="same operator request key on separate owners",
        idempotency_key="shared-grant-key",
        effective_from=NOW,
    )

    user_grant = management.create_grant(
        owner_type="user", owner_id="user-1", **common
    )
    workspace_grant = management.create_grant(
        owner_type="workspace", owner_id="workspace-1", **common
    )

    assert user_grant["grant_id"] != workspace_grant["grant_id"]


def test_snapshot_exposes_active_grant_before_first_admission(quota_engine):
    management = QuotaManagementService(quota_engine)
    period_start = NOW.replace(hour=0)
    management.create_grant(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=period_start,
        period_end=period_start + timedelta(days=1),
        allocated_micro=50,
        source_type="grant",
        created_by="developer-1",
        reason="show grant in account snapshot",
        idempotency_key="snapshot-grant",
        effective_from=NOW,
    )

    snapshot = QuotaService(quota_engine).snapshot(user_id="user-1", now=NOW)

    assert snapshot["buckets"] == [
        {
            "owner_type": "user",
            "owner_id": "user-1",
            "bucket_type": "daily",
            "limit_micro": 0,
            "grant_micro": 50,
            "adjustment_micro": 0,
            "consumed_micro": 0,
            "reserved_micro": 0,
            "remaining_micro": 50,
            "reset_at": (period_start + timedelta(days=1)).isoformat(),
            "over_limit": False,
        }
    ]


def test_policy_version_and_manual_adjustment_are_recorded_without_mutating_history(quota_engine):
    old_id = _policy(quota_engine, code="student", version="1", daily=100)
    _bind(quota_engine, subject_type="role", subject_id="student", policy_id=old_id)
    service = QuotaService(quota_engine)
    first = service.admit_turn(_command("turn-history", estimated_micro=20), role_codes=("student",), now=NOW)
    management = QuotaManagementService(quota_engine)
    new = management.create_policy(
        code="student",
        version="2",
        name="Student v2",
        daily_limit_micro=200,
        monthly_limit_micro=None,
        request_limit_micro=200,
        concurrency_limit=2,
        created_by="developer-1",
        effective_from=NOW + timedelta(hours=1),
        status="draft",
    )
    management.publish_policy(new["policy_id"], actor_user_id="developer-1")
    with quota_engine.connect() as connection:
        reservation = connection.execute(select(QuotaReservationModel.__table__)).mappings().one()
        assert reservation["policy_id"] == old_id
        assert reservation["policy_version"] == "1"
        assert connection.execute(select(QuotaLedgerEntryModel.__table__)).fetchall()
    assert new["version"] == "2"


def test_workspace_budget_rejects_after_user_budget_would_still_allow(quota_engine):
    user_policy = _policy(quota_engine, code="user", version="1", daily=100, monthly=None)
    workspace_policy = _policy(quota_engine, code="workspace", version="1", daily=30, monthly=None)
    _bind(quota_engine, subject_type="role", subject_id="student", policy_id=user_policy)
    _bind(quota_engine, subject_type="workspace", subject_id="workspace-1", policy_id=workspace_policy)
    service = QuotaService(quota_engine)
    service.admit_turn(_command("turn-budget", estimated_micro=20), role_codes=("student",), now=NOW)
    with pytest.raises(QuotaRejectedError) as error:
        service.admit_turn(_command("turn-budget-2", estimated_micro=20), role_codes=("student",), now=NOW)
    assert error.value.problem.code is QuotaErrorCode.WORKSPACE_EXHAUSTED


def test_active_grant_and_manual_adjustment_extend_the_atomic_bucket_balance(quota_engine):
    user_policy = _policy(quota_engine, code="user", version="1", daily=10, monthly=None)
    _bind(quota_engine, subject_type="role", subject_id="student", policy_id=user_policy)
    start = NOW.replace(hour=0)
    end = start + timedelta(days=1)
    management = QuotaManagementService(quota_engine)
    management.create_grant(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=start,
        period_end=end,
        allocated_micro=50,
        source_type="grant",
        created_by="developer-1",
        reason="exam week",
        idempotency_key="grant-admission",
        effective_from=NOW,
    )
    management.create_adjustment(
        owner_type="user",
        owner_id="user-1",
        bucket_type="daily",
        period_start=start,
        period_end=end,
        amount_micro=-5,
        actor_user_id="developer-1",
        reason="correction",
        idempotency_key="adjustment-admission",
    )
    service = QuotaService(quota_engine)
    admitted = service.admit_turn(_command("turn-grant", estimated_micro=55), role_codes=("student",), now=NOW)
    assert admitted.allowed is True
    snapshot = service.snapshot(user_id="user-1", now=NOW)
    daily = next(item for item in snapshot["buckets"] if item["bucket_type"] == "daily")
    assert daily["grant_micro"] == 50
    assert daily["adjustment_micro"] == -5
    assert daily["remaining_micro"] == 0


def test_settlement_uses_workspace_policy_overdraft_for_workspace_bucket(quota_engine):
    user_policy = _policy(quota_engine, code="user", version="1", daily=100, monthly=None)
    workspace_policy = _policy(
        quota_engine,
        code="workspace",
        version="1",
        daily=100,
        monthly=None,
        max_overdraft=20,
    )
    _bind(quota_engine, subject_type="role", subject_id="student", policy_id=user_policy)
    _bind(quota_engine, subject_type="workspace", subject_id="workspace-1", policy_id=workspace_policy)
    service = QuotaService(quota_engine)

    admitted = service.admit_turn(
        _command("turn-workspace-overdraft", estimated_micro=10),
        role_codes=("student",),
        now=NOW,
    )
    service.settle_usage(
        reservation_id=admitted.reservation_id,
        operation_id="operation-workspace-overdraft",
        credits_micro=110,
        usage_status="exact",
        now=NOW + timedelta(seconds=1),
    )

    with quota_engine.connect() as connection:
        rows = connection.execute(
            select(QuotaBucketModel.__table__).order_by(QuotaBucketModel.owner_type)
        ).mappings().all()
    assert rows[0]["owner_type"] == "user"
    assert rows[0]["over_limit"] is True
    assert rows[1]["owner_type"] == "workspace"
    assert rows[1]["over_limit"] is False
