"""Opt-in MySQL integration coverage for the Phase 2 accounting seam."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, insert, select, text

from core.model_runtime.usage import (
    CanonicalTokenUsage,
    InvocationOutcome,
    ModelIdentity,
    ModelInvocation,
    UsageAttributionContext,
)
from server.quota.contracts import AdmitTurn
from server.quota.errors import QuotaRejectedError
from server.quota.models import (
    PolicyBindingModel,
    PricingRuleModel,
    QuotaBucketModel,
    QuotaConcurrencyLockModel,
    QuotaCreditOperationModel,
    QuotaCreditScopeLockModel,
    QuotaDailyRollupModel,
    QuotaLedgerEntryModel,
    QuotaPolicyModel,
    QuotaProviderBillingModel,
    QuotaReservationModel,
    QuotaUsageArchiveBatchModel,
    QuotaAlertModel,
    UsageEventModel,
)
from server.quota.operations import QuotaOperationsService
from server.quota.reporting import DurableModelUsageReporter
from server.quota.service import QuotaService


NOW = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def _mysql_dsn() -> str:
    value = os.getenv("NLP_AGENT_DATABASE_URL", "").strip()
    if not value.startswith("mysql+aiomysql://"):
        pytest.skip("NLP_AGENT_DATABASE_URL must point to the integration MySQL")
    return value


def _process_admission(args: tuple[str, dict]) -> bool:
    dsn, payload = args
    service = QuotaService(dsn, lease_seconds=60)
    try:
        command = AdmitTurn.model_validate(payload)
        service.admit_turn(command, role_codes=("student",), now=NOW)
        return True
    except QuotaRejectedError:
        return False
    finally:
        service.close()


def test_mysql_phase2_schema_contains_counter_and_accounting_constraints():
    dsn = _mysql_dsn()
    engine = create_engine(dsn.replace("mysql+aiomysql://", "mysql+pymysql://"))
    try:
        QuotaService(engine).verify_schema()
        with engine.connect() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'nlp_quota_concurrency_locks'"
                    )
                )
            }
            unique_constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'nlp_quota_ledger_entries' "
                        "AND constraint_type = 'UNIQUE'"
                    )
                )
            }
        assert {"user_id", "active_units", "version"} <= columns
        assert "uq_nlp_quota_ledger_entries_idempotency_key" in unique_constraints
    finally:
        engine.dispose()


def test_mysql_phase4_schema_contains_operations_tables_and_archive_columns():
    dsn = _mysql_dsn()
    engine = create_engine(dsn.replace("mysql+aiomysql://", "mysql+pymysql://"))
    try:
        QuotaService(engine).verify_schema()
        operations_tables = {
            QuotaCreditOperationModel.__tablename__,
            QuotaCreditScopeLockModel.__tablename__,
            QuotaDailyRollupModel.__tablename__,
            QuotaProviderBillingModel.__tablename__,
            QuotaUsageArchiveBatchModel.__tablename__,
            QuotaAlertModel.__tablename__,
        }
        with engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = DATABASE()"
                    )
                )
            }
            usage_columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'nlp_usage_events'"
                    )
                )
            }
            credit_columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'nlp_quota_credit_operations'"
                    )
                )
            }
            entry_type_length = connection.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'nlp_quota_ledger_entries' "
                    "AND column_name = 'entry_type'"
                )
            ).scalar_one()
        assert operations_tables <= tables
        assert {"archived_at", "archive_batch_id"} <= usage_columns
        assert {"effective_from", "expires_at"} <= credit_columns
        assert entry_type_length >= 32
        assert QuotaOperationsService(engine).partition_strategy(
            start_year=2026, start_month=8, months=2
        )["partitions"] == [
            {"name": "p202608", "from": "2026-08-01", "to": "2026-09-01"},
            {"name": "p202609", "from": "2026-09-01", "to": "2026-10-01"},
        ]
    finally:
        engine.dispose()


def test_mysql_twenty_processes_cannot_breach_one_user_concurrency_slot():
    dsn = _mysql_dsn()
    engine = create_engine(dsn.replace("mysql+aiomysql://", "mysql+pymysql://"))
    policy_id = str(uuid4())
    user_id = f"phase2-mysql-{uuid4()}"
    try:
        QuotaService(engine).verify_schema()
        with engine.begin() as connection:
            connection.execute(
                insert(QuotaPolicyModel).values(
                    id=policy_id,
                    code=f"phase2-mysql-{uuid4()}",
                    version="1",
                    name="Phase 2 MySQL concurrency test",
                    status="active",
                    request_limit_micro=10_000,
                    daily_limit_micro=10_000,
                    monthly_limit_micro=10_000,
                    concurrency_limit=1,
                    max_overdraft_micro=0,
                    allowed_model_profiles=["economy"],
                    unlimited=False,
                    effective_from=NOW,
                    effective_until=None,
                    created_by="phase2-integration",
                )
            )
            connection.execute(
                insert(PolicyBindingModel).values(
                    id=str(uuid4()),
                    subject_type="role",
                    subject_id="student",
                    policy_id=policy_id,
                    priority=100,
                    status="active",
                    effective_from=NOW,
                    effective_until=None,
                )
            )
        payloads = [
            {
                "request_id": f"phase2-request-{index}-{uuid4()}",
                "user_id": user_id,
                "workspace_id": "phase2-integration",
                "turn_id": f"phase2-turn-{index}-{uuid4()}",
                "model_profile": "economy",
                "model_role": "coordinator",
                "estimated_input_tokens": 1,
                "estimated_output_tokens": 1,
                "estimated_micro": 1,
                "idempotency_key": f"phase2-idempotency-{index}-{uuid4()}",
            }
            for index in range(20)
        ]
        with ProcessPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(_process_admission, [(dsn, payload) for payload in payloads]))

        assert sum(outcomes) == 1
        with engine.connect() as connection:
            lock = connection.execute(
                select(QuotaConcurrencyLockModel.__table__).where(
                    QuotaConcurrencyLockModel.user_id == user_id
                )
            ).mappings().one()
        assert lock["active_units"] == 1
    finally:
        with engine.begin() as connection:
            reservation_ids = select(QuotaReservationModel.id).where(
                QuotaReservationModel.user_id == user_id
            )
            connection.execute(
                delete(QuotaLedgerEntryModel).where(
                    QuotaLedgerEntryModel.reservation_id.in_(reservation_ids)
                )
            )
            connection.execute(
                delete(QuotaReservationModel).where(
                    QuotaReservationModel.user_id == user_id
                )
            )
            connection.execute(
                delete(QuotaBucketModel).where(QuotaBucketModel.owner_id == user_id)
            )
            connection.execute(
                delete(QuotaConcurrencyLockModel).where(
                    QuotaConcurrencyLockModel.user_id == user_id
                )
            )
            connection.execute(
                delete(PolicyBindingModel).where(PolicyBindingModel.policy_id == policy_id)
            )
            connection.execute(delete(QuotaPolicyModel).where(QuotaPolicyModel.id == policy_id))
        engine.dispose()


def test_mysql_late_provider_usage_reconciles_a_closed_reservation():
    dsn = _mysql_dsn()
    engine = create_engine(dsn.replace("mysql+aiomysql://", "mysql+pymysql://"))
    policy_id = str(uuid4())
    reservation_id = None
    user_id = f"phase2-mysql-reconcile-{uuid4()}"
    pricing_key = f"phase2-mysql/model-{uuid4()}"
    operation_id = str(uuid4())
    try:
        service = QuotaService(engine, lease_seconds=60)
        service.verify_schema()
        with engine.begin() as connection:
            connection.execute(
                insert(QuotaPolicyModel).values(
                    id=policy_id,
                    code=f"phase2-mysql-reconcile-{uuid4()}",
                    version="1",
                    name="Phase 2 MySQL late settlement test",
                    status="active",
                    request_limit_micro=100,
                    daily_limit_micro=10_000,
                    monthly_limit_micro=10_000,
                    concurrency_limit=1,
                    max_overdraft_micro=0,
                    allowed_model_profiles=["economy"],
                    unlimited=False,
                    effective_from=NOW,
                    effective_until=None,
                    created_by="phase2-integration",
                )
            )
            connection.execute(
                insert(PolicyBindingModel).values(
                    id=str(uuid4()),
                    subject_type="role",
                    subject_id="student",
                    policy_id=policy_id,
                    priority=100,
                    status="active",
                    effective_from=NOW,
                    effective_until=None,
                )
            )
        admitted = service.admit_turn(
            AdmitTurn(
                request_id=f"phase2-reconcile-request-{uuid4()}",
                user_id=user_id,
                workspace_id="phase2-integration",
                turn_id=f"phase2-reconcile-turn-{uuid4()}",
                model_profile="economy",
                model_role="coordinator",
                estimated_input_tokens=2,
                estimated_output_tokens=3,
                estimated_micro=5,
                idempotency_key=f"phase2-reconcile-idempotency-{uuid4()}",
            ),
            role_codes=("student",),
            now=NOW,
        )
        reservation_id = admitted.reservation_id
        # The actual turn id is carried by the reservation; finish it through a
        # direct read so the test exercises delayed settlement after closure.
        with engine.connect() as connection:
            turn_id = connection.execute(
                select(QuotaReservationModel.turn_id).where(
                    QuotaReservationModel.id == reservation_id
                )
            ).scalar_one()
        service.release_reservation(
            reservation_id,
            turn_id=turn_id,
            idempotency_key=f"phase2-reconcile-finish-{uuid4()}",
            now=NOW,
        )

        invocation = ModelInvocation(
            operation_id=operation_id,
            identity=ModelIdentity(
                provider="phase2-mysql",
                provider_model="phase2-model",
                model_profile="economy",
                preset="economy",
                route="coordinator",
                pricing_key=pricing_key,
            ),
            attribution=UsageAttributionContext(
                request_id="phase2-reconcile-request",
                user_id=user_id,
                workspace_id="phase2-integration",
                turn_id=turn_id,
                reservation_id=reservation_id,
                purpose="coordinator",
            ),
            attempt=1,
            fallback_index=0,
            started_at=NOW,
        )
        partial = CanonicalTokenUsage(
            input_tokens=2,
            output_tokens=3,
            total_tokens=5,
            source="provider",
            semantics="partial",
        )
        exact = partial.model_copy(update={"semantics": "final"})
        partial_outcome = InvocationOutcome(
            status="interrupted",
            completed_at=NOW,
        )
        exact_outcome = InvocationOutcome(
            status="succeeded",
            finish_reason="stop",
            completed_at=NOW,
        )
        reporter = DurableModelUsageReporter(engine, quota_service=service)
        asyncio.run(reporter.report(invocation, partial, partial_outcome))
        with engine.begin() as connection:
            connection.execute(
                insert(PricingRuleModel).values(
                    id=str(uuid4()),
                    pricing_key=pricing_key,
                    version="1",
                    effective_from=NOW,
                    effective_until=None,
                    ordinary_input_credits_micro_per_million_tokens=1_000_000,
                    cached_input_credits_micro_per_million_tokens=0,
                    cache_write_credits_micro_per_million_tokens=0,
                    output_credits_micro_per_million_tokens=2_000_000,
                    reasoning_output_credits_micro_per_million_tokens=None,
                    status="active",
                    created_by="phase2-integration",
                    created_at=NOW,
                )
            )
        asyncio.run(reporter.report(invocation, exact, exact_outcome))

        with engine.connect() as connection:
            event = connection.execute(
                select(UsageEventModel.__table__).where(
                    UsageEventModel.operation_id == operation_id
                )
            ).mappings().one()
            bucket = connection.execute(
                select(QuotaBucketModel.__table__).where(
                    QuotaBucketModel.owner_id == user_id,
                    QuotaBucketModel.bucket_type == "daily",
                )
            ).mappings().one()
            reconcile_count = connection.execute(
                select(QuotaLedgerEntryModel.id).where(
                    QuotaLedgerEntryModel.reservation_id == reservation_id,
                    QuotaLedgerEntryModel.entry_type == "reconcile",
                )
            ).fetchall()
        assert event["usage_status"] == "exact"
        assert event["credits_micro"] == 8
        assert bucket["consumed_micro"] == 8
        assert len(reconcile_count) == 2
    finally:
        with engine.begin() as connection:
            if reservation_id is not None:
                connection.execute(
                    delete(QuotaLedgerEntryModel).where(
                        QuotaLedgerEntryModel.reservation_id == reservation_id
                    )
                )
                connection.execute(
                    delete(UsageEventModel).where(
                        UsageEventModel.operation_id == operation_id
                    )
                )
                connection.execute(
                    delete(QuotaReservationModel).where(
                        QuotaReservationModel.id == reservation_id
                    )
                )
            connection.execute(
                delete(QuotaBucketModel).where(QuotaBucketModel.owner_id == user_id)
            )
            connection.execute(
                delete(QuotaConcurrencyLockModel).where(
                    QuotaConcurrencyLockModel.user_id == user_id
                )
            )
            connection.execute(
                delete(PolicyBindingModel).where(PolicyBindingModel.policy_id == policy_id)
            )
            connection.execute(delete(QuotaPolicyModel).where(QuotaPolicyModel.id == policy_id))
            connection.execute(
                delete(PricingRuleModel).where(PricingRuleModel.pricing_key == pricing_key)
            )
        engine.dispose()
