from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from server.quota.contracts import AdmitTurn, FinishTurn
from server.quota.errors import QuotaErrorCode, QuotaRejectedError
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
NOW = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)


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
    daily: int | None = 100,
    monthly: int | None = 1_000,
    request: int | None = 100,
    concurrency: int | None = 2,
    overdraft: int = 0,
):
    policy_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            insert(QuotaPolicyModel).values(
                id=policy_id,
                code="student-default",
                version="2026-08-29.1",
                name="Student default",
                status="active",
                request_limit_micro=request,
                daily_limit_micro=daily,
                monthly_limit_micro=monthly,
                concurrency_limit=concurrency,
                max_overdraft_micro=overdraft,
                allowed_model_profiles=["economy"],
                unlimited=False,
                effective_from=NOW,
                effective_until=None,
                created_by="developer-1",
            )
        )
        connection.execute(
            insert(PolicyBindingModel).values(
                id=str(uuid4()),
                subject_type="role",
                subject_id="student",
                policy_id=policy_id,
                priority=10,
                status="active",
                effective_from=NOW,
                effective_until=None,
            )
        )
    return policy_id


def _command(
    *,
    turn_id: str,
    idempotency_key: str | None = None,
    estimated_micro: int = 60,
    profile: str = "economy",
) -> AdmitTurn:
    return AdmitTurn(
        request_id=f"request-{turn_id}",
        user_id="user-1",
        workspace_id="workspace-1",
        turn_id=turn_id,
        model_profile=profile,
        model_role="coordinator",
        estimated_input_tokens=20,
        estimated_output_tokens=40,
        estimated_micro=estimated_micro,
        idempotency_key=idempotency_key or f"idempotency-{turn_id}",
    )


def test_concurrent_admission_cannot_both_reserve_the_last_balance(quota_engine):
    _policy(quota_engine, daily=100, monthly=1_000, request=100)
    service = QuotaService(quota_engine, lease_seconds=60)
    commands = [_command(turn_id=f"turn-{index}") for index in range(2)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda command: _admit(service, command),
                commands,
            )
        )

    assert sum(bool(getattr(outcome, "allowed", False)) for outcome in outcomes) == 1
    error = next(outcome for outcome in outcomes if isinstance(outcome, QuotaRejectedError))
    assert error.problem.code is QuotaErrorCode.DAILY_EXHAUSTED
    with quota_engine.connect() as connection:
        bucket = connection.execute(
            select(QuotaBucketModel.__table__).where(
                QuotaBucketModel.bucket_type == "daily"
            )
        ).mappings().one()
    assert bucket["reserved_micro"] == 60


def _admit(service: QuotaService, command: AdmitTurn):
    try:
        return service.admit_turn(command, role_codes=("student",), now=NOW)
    except QuotaRejectedError as error:
        return error


def test_turn_idempotency_replays_one_reservation_and_one_reserve_ledger(quota_engine):
    _policy(quota_engine)
    service = QuotaService(quota_engine)
    command = _command(turn_id="turn-1", idempotency_key="same-request")

    first = service.admit_turn(command, role_codes=("student",), now=NOW)
    second = service.admit_turn(command, role_codes=("student",), now=NOW)

    assert first.allowed is True
    assert second.duplicate is True
    assert second.reservation_id == first.reservation_id
    with quota_engine.connect() as connection:
        assert connection.execute(select(QuotaReservationModel.__table__)).fetchall().__len__() == 1
        ledger = connection.execute(select(QuotaLedgerEntryModel.__table__)).mappings().all()
    assert len(ledger) == 2  # daily and monthly bucket entries


def test_turn_creation_rollback_removes_reservation_bucket_and_ledger(quota_engine):
    _policy(quota_engine)
    service = QuotaService(quota_engine)
    command = _command(turn_id="turn-rollback")

    with pytest.raises(RuntimeError, match="create turn failed"):
        with quota_engine.begin() as connection:
            service.admit_in_transaction(
                connection,
                command,
                role_codes=("student",),
                now=NOW,
            )
            raise RuntimeError("create turn failed")

    with quota_engine.connect() as connection:
        for model in (QuotaBucketModel, QuotaReservationModel, QuotaLedgerEntryModel):
            assert connection.execute(select(model.__table__)).fetchall() == []


def test_profile_request_and_concurrency_limits_are_rejected_with_stable_codes(quota_engine):
    _policy(quota_engine, request=50, concurrency=1)
    service = QuotaService(quota_engine, lease_seconds=60)

    with pytest.raises(QuotaRejectedError) as profile_error:
        service.admit_turn(
            _command(turn_id="turn-profile", profile="premium"),
            role_codes=("student",),
            now=NOW,
        )
    assert profile_error.value.problem.code is QuotaErrorCode.MODEL_NOT_ALLOWED

    first = service.admit_turn(
        _command(turn_id="turn-concurrency", estimated_micro=40),
        role_codes=("student",),
        now=NOW,
    )
    with pytest.raises(QuotaRejectedError) as concurrency_error:
        service.admit_turn(
            _command(turn_id="turn-concurrency-2", estimated_micro=1),
            role_codes=("student",),
            now=NOW,
        )
    assert first.allowed is True
    assert concurrency_error.value.problem.code is QuotaErrorCode.CONCURRENCY_LIMIT

    with pytest.raises(QuotaRejectedError) as request_error:
        service.admit_turn(
            _command(turn_id="turn-request", estimated_micro=51),
            role_codes=("student",),
            now=NOW,
        )
    assert request_error.value.problem.code is QuotaErrorCode.REQUEST_LIMIT


def test_admission_persists_a_database_concurrency_counter(quota_engine):
    _policy(quota_engine, concurrency=1)
    service = QuotaService(quota_engine)

    first = service.admit_turn(
        _command(turn_id="turn-concurrency-counter"),
        role_codes=("student",),
        now=NOW,
    )

    assert first.allowed is True
    with quota_engine.connect() as connection:
        lock = connection.execute(
            select(QuotaConcurrencyLockModel.__table__).where(
                QuotaConcurrencyLockModel.user_id == "user-1"
            )
        ).mappings().one()
    assert lock["active_units"] == 1

    service.finish_turn(
        FinishTurn(
            reservation_id=first.reservation_id,
            turn_id="turn-concurrency-counter",
            idempotency_key="finish-concurrency-counter",
        ),
        now=NOW + timedelta(seconds=1),
    )
    with quota_engine.connect() as connection:
        lock = connection.execute(
            select(QuotaConcurrencyLockModel.__table__).where(
                QuotaConcurrencyLockModel.user_id == "user-1"
            )
        ).mappings().one()
    assert lock["active_units"] == 0


def test_zero_override_uses_versioned_pricing_for_conservative_admission(quota_engine):
    _policy(quota_engine, daily=1_000, monthly=10_000, request=1_000)
    with quota_engine.begin() as connection:
        connection.execute(
            insert(PricingRuleModel).values(
                id=str(uuid4()),
                pricing_key="provider-a/model-a",
                version="2026-08-29.1",
                effective_from=NOW,
                effective_until=None,
                ordinary_input_credits_micro_per_million_tokens=1_000_000,
                cached_input_credits_micro_per_million_tokens=1_000_000,
                cache_write_credits_micro_per_million_tokens=1_000_000,
                output_credits_micro_per_million_tokens=2_000_000,
                reasoning_output_credits_micro_per_million_tokens=4_000_000,
                status="active",
                created_by="developer-1",
            )
        )
    service = QuotaService(quota_engine)
    admitted = service.admit_turn(
        _command(turn_id="turn-priced").model_copy(
            update={
                "estimated_micro": 0,
                "estimated_input_tokens": 1,
                "estimated_output_tokens": 2,
                "pricing_key": "provider-a/model-a",
            }
        ),
        role_codes=("student",),
        now=NOW,
    )

    assert admitted.reserved_micro == 9


def test_settlement_is_idempotent_records_actual_over_limit_and_blocks_next_admission(quota_engine):
    _policy(quota_engine, daily=100, monthly=1_000, request=100, overdraft=0)
    service = QuotaService(quota_engine)
    admitted = service.admit_turn(
        _command(turn_id="turn-settle", estimated_micro=60),
        role_codes=("student",),
        now=NOW,
    )

    first = service.settle_usage(
        reservation_id=admitted.reservation_id,
        operation_id="operation-1",
        credits_micro=120,
        usage_status="exact",
        now=NOW + timedelta(seconds=2),
    )
    replay = service.settle_usage(
        reservation_id=admitted.reservation_id,
        operation_id="operation-1",
        credits_micro=120,
        usage_status="exact",
        now=NOW + timedelta(seconds=3),
    )

    assert first.credits_micro == 120
    assert first.over_limit is True
    assert replay == first
    with quota_engine.connect() as connection:
        bucket = connection.execute(select(QuotaBucketModel.__table__)).mappings().first()
    assert bucket["consumed_micro"] == 120
    assert bucket["reserved_micro"] == 0

    with pytest.raises(QuotaRejectedError) as exhausted:
        service.admit_turn(
            _command(turn_id="turn-after-over-limit", estimated_micro=1),
            role_codes=("student",),
            now=NOW + timedelta(seconds=4),
        )
    assert exhausted.value.problem.code is QuotaErrorCode.DAILY_EXHAUSTED


def test_finish_turn_releases_remaining_reservation_and_is_idempotent(quota_engine):
    _policy(quota_engine)
    service = QuotaService(quota_engine)
    admitted = service.admit_turn(
        _command(turn_id="turn-finish", estimated_micro=60),
        role_codes=("student",),
        now=NOW,
    )
    service.settle_usage(
        reservation_id=admitted.reservation_id,
        operation_id="operation-finish",
        credits_micro=20,
        usage_status="exact",
        now=NOW + timedelta(seconds=1),
    )

    command = FinishTurn(
        reservation_id=admitted.reservation_id,
        turn_id="turn-finish",
        idempotency_key="finish-once",
    )
    first = service.finish_turn(command, now=NOW + timedelta(seconds=2))
    second = service.finish_turn(command, now=NOW + timedelta(seconds=3))

    assert first.status == "settled"
    assert first.released_micro == 40
    assert second == first
    with quota_engine.connect() as connection:
        reservation = connection.execute(select(QuotaReservationModel.__table__)).mappings().one()
        buckets = connection.execute(select(QuotaBucketModel.__table__)).mappings().all()
    assert reservation["status"] == "settled"
    assert all(row["reserved_micro"] == 0 for row in buckets)


def test_expired_reservation_releases_credit_and_concurrency_lease(quota_engine):
    _policy(quota_engine, concurrency=1)
    service = QuotaService(quota_engine, lease_seconds=10)
    admitted = service.admit_turn(
        _command(turn_id="turn-expire"),
        role_codes=("student",),
        now=NOW,
    )

    expired = service.expire_reservations(now=NOW + timedelta(seconds=11))

    assert expired == 1
    with quota_engine.connect() as connection:
        reservation = connection.execute(select(QuotaReservationModel.__table__)).mappings().one()
        buckets = connection.execute(select(QuotaBucketModel.__table__)).mappings().all()
    assert reservation["status"] == "expired"
    assert all(row["reserved_micro"] == 0 for row in buckets)


def test_replaying_a_dispatch_failed_turn_rearms_the_same_reservation(quota_engine):
    _policy(quota_engine)
    service = QuotaService(quota_engine)
    command = _command(turn_id="turn-dispatch-retry", idempotency_key="retry-key")
    first = service.admit_turn(command, role_codes=("student",), now=NOW)
    service.release_reservation(
        first.reservation_id,
        turn_id=command.turn_id,
        idempotency_key="dispatch-failed:turn-dispatch-retry",
        now=NOW + timedelta(seconds=1),
    )

    retried = service.admit_turn(command, role_codes=("student",), now=NOW + timedelta(seconds=2))
    service.settle_usage(
        reservation_id=retried.reservation_id,
        operation_id="operation-after-dispatch-retry",
        credits_micro=20,
        usage_status="exact",
        now=NOW + timedelta(seconds=3),
    )

    assert retried.reservation_id == first.reservation_id
    assert retried.reserved_micro == command.estimated_micro
    with quota_engine.connect() as connection:
        reservations = connection.execute(select(QuotaReservationModel.__table__)).mappings().all()
        reserve_entries = connection.execute(
            select(QuotaLedgerEntryModel.__table__).where(
                QuotaLedgerEntryModel.entry_type == "reserve"
            )
        ).fetchall()
        settle_entries = connection.execute(
            select(QuotaLedgerEntryModel.__table__).where(
                QuotaLedgerEntryModel.entry_type == "settle"
            )
        ).fetchall()
        buckets = connection.execute(select(QuotaBucketModel.__table__)).mappings().all()
    assert len(reservations) == 1
    assert len(reserve_entries) == 4
    assert len(settle_entries) == 2
    assert all(row["consumed_micro"] == 20 for row in buckets)
