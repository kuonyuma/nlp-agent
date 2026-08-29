"""Transactional quota admission, reservation, settlement, and expiry."""

from __future__ import annotations

import threading
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import Engine, and_, create_engine, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from server.quota.contracts import (
    AdmitTurn,
    FinishTurn,
    PolicyBinding,
    QuotaPolicy,
    QuotaProblem,
    TurnAdmissionResult,
    TurnFinishResult,
    UsageRecordResult,
    UsageStatus,
)
from server.quota.errors import QuotaDomainError, QuotaErrorCode, QuotaRejectedError
from server.quota.models import (
    PolicyBindingModel,
    PricingRuleModel,
    QuotaBucketModel,
    QuotaLedgerEntryModel,
    QuotaPolicyModel,
    QuotaReservationModel,
)
from server.quota.policy import resolve_effective_policy


UTC = timezone.utc
_GLOBAL_QUOTA_LOCK = threading.RLock()
_ACTIVE_RESERVATION_STATUSES = ("reserved", "running", "settling")


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_time(value: datetime) -> datetime:
    """MySQL DATETIME stores UTC without a timezone marker."""
    return _utc(value).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else _utc(value)


def _now_factory() -> datetime:
    return datetime.now(UTC)


class QuotaService:
    """The single write seam for Phase 2 quota state.

    Admission and settlement are each one database transaction.  The process
    lock keeps the SQLite test/embedded runtime deterministic; MySQL still
    takes row locks with ``FOR UPDATE`` so separate workers cannot reserve the
    same remaining balance.
    """

    def __init__(
        self,
        database: str | Engine,
        *,
        lease_seconds: int = 300,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if isinstance(database, str):
            if database.startswith("mysql+aiomysql://"):
                database = database.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
            self._engine = create_engine(database, pool_pre_ping=True)
            self._owns_engine = True
        else:
            self._engine = database
            self._owns_engine = False
        self.lease_seconds = lease_seconds

    @staticmethod
    def reservation_id_for_turn(turn_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pro-nlp:quota-reservation:{turn_id}"))

    def admit_turn(
        self,
        command: AdmitTurn,
        *,
        role_codes: Sequence[str] = (),
        classroom_ids: Sequence[str] = (),
        now: datetime | None = None,
    ) -> TurnAdmissionResult:
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                return self.admit_in_transaction(
                    connection,
                    command,
                    role_codes=role_codes,
                    classroom_ids=classroom_ids,
                    now=now,
                )

    def admit_in_transaction(
        self,
        connection: Connection,
        command: AdmitTurn,
        *,
        role_codes: Sequence[str] = (),
        classroom_ids: Sequence[str] = (),
        now: datetime | None = None,
    ) -> TurnAdmissionResult:
        at = _utc(now)
        existing = self._find_existing_reservation(connection, command)
        rearm_existing = False
        if existing is not None:
            if (
                existing["turn_id"] != command.turn_id
                or existing["user_id"] != command.user_id
                or existing["idempotency_key"] != command.idempotency_key
            ):
                raise self._rejection(
                    QuotaErrorCode.RESERVATION_CONFLICT,
                    "The idempotency key or Turn is already bound to another request",
                )
            lease_expires_at = _aware(existing["lease_expires_at"])
            if (
                existing["status"] in _ACTIVE_RESERVATION_STATUSES
                and lease_expires_at is not None
                and lease_expires_at > at
            ):
                return self._admission_result(existing, duplicate=True)
            if (
                existing["status"] in {"released", "expired"}
                and int(existing["settled_micro"]) == 0
            ) or (
                existing["status"] in _ACTIVE_RESERVATION_STATUSES
                and (lease_expires_at is None or lease_expires_at <= at)
            ):
                rearm_existing = True
            else:
                return self._admission_result(existing, duplicate=True)

        binding = self._effective_binding(
            connection,
            command,
            role_codes=role_codes,
            classroom_ids=classroom_ids,
            at=at,
        )
        policy = binding.policy
        if policy.allowed_model_profiles and command.model_profile not in policy.allowed_model_profiles:
            raise self._rejection(
                QuotaErrorCode.MODEL_NOT_ALLOWED,
                f"Model profile {command.model_profile!r} is not allowed by policy {policy.code}",
                allowed_model_profiles=policy.allowed_model_profiles,
            )

        reservation_micro = int(command.estimated_micro)
        if reservation_micro == 0:
            try:
                reservation_micro = self._estimate_micro(connection, command, at)
            except QuotaDomainError as error:
                raise self._rejection(error.code, str(error), retryable=True) from error
        if policy.request_limit_micro is not None and reservation_micro > policy.request_limit_micro:
            raise self._rejection(
                QuotaErrorCode.REQUEST_LIMIT,
                "The estimated cost exceeds the per-request quota",
                remaining_micro=policy.request_limit_micro,
            )

        self._expire_stale_in_transaction(connection, at)
        if policy.concurrency_limit is not None:
            active = connection.execute(
                select(QuotaReservationModel.concurrency_units).where(
                    QuotaReservationModel.user_id == command.user_id,
                    QuotaReservationModel.status.in_(_ACTIVE_RESERVATION_STATUSES),
                    QuotaReservationModel.lease_expires_at > _db_time(at),
                )
            ).scalars()
            active_units = sum(int(units) for units in active)
            if active_units + 1 > policy.concurrency_limit:
                raise self._rejection(
                    QuotaErrorCode.CONCURRENCY_LIMIT,
                    "The user has reached the concurrent Turn limit",
                    remaining_micro=0,
                    retryable=True,
                )

        buckets: list[dict[str, Any]] = []
        for bucket_type, start, end, limit in self._periods(policy, at):
            bucket = self._get_or_create_bucket(
                connection,
                owner_id=command.user_id,
                bucket_type=bucket_type,
                period_start=start,
                period_end=end,
                policy=policy,
                limit=limit,
                now=at,
            )
            available = self._available(bucket, policy.max_overdraft_micro)
            if reservation_micro > available:
                code = (
                    QuotaErrorCode.DAILY_EXHAUSTED
                    if bucket_type == "daily"
                    else QuotaErrorCode.MONTHLY_EXHAUSTED
                )
                raise self._rejection(
                    code,
                    f"The {bucket_type} quota is exhausted",
                    remaining_micro=available,
                    reset_at=end,
                    retryable=True,
                )
            buckets.append(bucket)

        reservation_id = self.reservation_id_for_turn(command.turn_id)
        db_now = _db_time(at)
        lease_expires = _db_time(at + timedelta(seconds=self.lease_seconds))
        snapshot = {
            "policy_id": policy.policy_id,
            "code": policy.code,
            "version": policy.version,
            "request_limit_micro": policy.request_limit_micro,
            "daily_limit_micro": policy.daily_limit_micro,
            "monthly_limit_micro": policy.monthly_limit_micro,
            "concurrency_limit": policy.concurrency_limit,
            "max_overdraft_micro": policy.max_overdraft_micro,
            "allowed_model_profiles": list(policy.allowed_model_profiles),
            "unlimited": policy.unlimited,
        }
        if rearm_existing:
            connection.execute(
                update(QuotaReservationModel)
                .where(QuotaReservationModel.id == reservation_id)
                .values(
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    policy_snapshot_json=snapshot,
                    reserved_micro=reservation_micro,
                    settled_micro=0,
                    status="reserved",
                    lease_expires_at=lease_expires,
                    last_heartbeat_at=db_now,
                    max_overdraft_micro=policy.max_overdraft_micro,
                    over_limit=False,
                    updated_at=db_now,
                )
            )
        else:
            connection.execute(
                insert(QuotaReservationModel).values(
                    id=reservation_id,
                    turn_id=command.turn_id,
                    user_id=command.user_id,
                    workspace_id=command.workspace_id,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    policy_snapshot_json=snapshot,
                    idempotency_key=command.idempotency_key,
                    reserved_micro=reservation_micro,
                    settled_micro=0,
                    status="reserved",
                    lease_expires_at=lease_expires,
                    last_heartbeat_at=db_now,
                    max_overdraft_micro=policy.max_overdraft_micro,
                    concurrency_units=1,
                    over_limit=False,
                    created_at=db_now,
                    updated_at=db_now,
                )
            )
        reserve_generation = 1
        if rearm_existing:
            reserve_generation = len(
                connection.execute(
                    select(QuotaLedgerEntryModel.id)
                    .where(
                        QuotaLedgerEntryModel.reservation_id == reservation_id,
                        QuotaLedgerEntryModel.entry_type == "reserve",
                    )
                ).scalars().all()
            ) + 1
        reserve_suffix = "" if reserve_generation == 1 else f":retry{reserve_generation}"
        if not buckets:
            self._insert_ledger(
                connection,
                reservation_id=reservation_id,
                bucket_id=None,
                entry_type="reserve",
                amount_micro=reservation_micro,
                reserved_delta_micro=reservation_micro,
                consumed_delta_micro=0,
                idempotency_key=f"reserve:{reservation_id}:none{reserve_suffix}",
                reason="turn_admission",
                metadata={"turn_id": command.turn_id},
                created_at=db_now,
            )
        for bucket in buckets:
            connection.execute(
                update(QuotaBucketModel)
                .where(QuotaBucketModel.id == bucket["id"])
                .values(
                    reserved_micro=int(bucket["reserved_micro"]) + reservation_micro,
                    version=int(bucket["version"]) + 1,
                    updated_at=db_now,
                )
            )
            self._insert_ledger(
                connection,
                reservation_id=reservation_id,
                bucket_id=bucket["id"],
                entry_type="reserve",
                amount_micro=reservation_micro,
                reserved_delta_micro=reservation_micro,
                consumed_delta_micro=0,
                idempotency_key=f"reserve:{reservation_id}:{bucket['id']}{reserve_suffix}",
                reason="turn_admission",
                metadata={"turn_id": command.turn_id, "bucket_type": bucket["bucket_type"]},
                created_at=db_now,
            )
        return TurnAdmissionResult(
            allowed=True,
            reservation_id=reservation_id,
            reserved_micro=reservation_micro,
            policy_id=policy.policy_id,
            policy_version=policy.version,
        )

    def settle_usage(
        self,
        *,
        reservation_id: str,
        operation_id: str,
        credits_micro: int,
        usage_status: UsageStatus,
        usage_source: str = "provider",
        pricing_key: str | None = None,
        pricing_version: str | None = None,
        now: datetime | None = None,
    ) -> UsageRecordResult:
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                return self.settle_usage_in_transaction(
                    connection,
                    reservation_id=reservation_id,
                    operation_id=operation_id,
                    credits_micro=credits_micro,
                    usage_status=usage_status,
                    usage_source=usage_source,
                    pricing_key=pricing_key,
                    pricing_version=pricing_version,
                    now=now,
                )

    def settle_usage_in_transaction(
        self,
        connection: Connection,
        *,
        reservation_id: str,
        operation_id: str,
        credits_micro: int,
        usage_status: UsageStatus,
        usage_source: str = "provider",
        pricing_key: str | None = None,
        pricing_version: str | None = None,
        now: datetime | None = None,
    ) -> UsageRecordResult:
        if isinstance(credits_micro, bool) or not isinstance(credits_micro, int) or credits_micro < 0:
            raise QuotaDomainError(
                QuotaErrorCode.INVALID_USAGE,
                "credits_micro must be a non-negative integer",
            )
        if usage_status not in {"exact", "estimated", "pending", "unavailable"}:
            raise QuotaDomainError(
                QuotaErrorCode.INVALID_USAGE,
                f"Unknown usage status {usage_status!r}",
            )
        db_now = _db_time(_utc(now))
        prefix = f"settle:{operation_id}:"
        reservation = connection.execute(
            select(QuotaReservationModel)
            .where(QuotaReservationModel.id == reservation_id)
            .with_for_update()
        ).mappings().first()
        if reservation is None:
            raise QuotaDomainError(
                QuotaErrorCode.RESERVATION_NOT_ACTIVE,
                f"Reservation {reservation_id!r} does not exist",
            )
        # Lock the reservation before reading the replay marker.  This turns
        # cross-process MySQL retries into a current read after the first
        # settlement commits, instead of relying on a stale REPEATABLE READ
        # snapshot and then surfacing a unique-key error.
        existing_rows = connection.execute(
            select(QuotaLedgerEntryModel)
            .where(
                QuotaLedgerEntryModel.reservation_id == reservation_id,
                QuotaLedgerEntryModel.entry_type == "settle",
                QuotaLedgerEntryModel.idempotency_key.like(f"{prefix}%"),
            )
        ).mappings().all()
        if existing_rows:
            metadata = existing_rows[0]["metadata_json"]
            if (
                int(metadata.get("credits_micro", -1)) != credits_micro
                or metadata.get("usage_status") != usage_status
            ):
                raise QuotaDomainError(
                    QuotaErrorCode.SETTLEMENT_CONFLICT,
                    "Settlement replay has different usage facts",
                )
            return UsageRecordResult(
                operation_id=operation_id,
                usage_source=metadata.get("usage_source", usage_source),
                credits_micro=credits_micro,
                usage_status=usage_status,
                over_limit=any(
                    bool(row["metadata_json"].get("over_limit", False))
                    for row in existing_rows
                ),
                pricing_key=metadata.get("pricing_key", pricing_key),
                pricing_version=metadata.get("pricing_version", pricing_version),
            )
        if reservation["status"] in {"released", "expired", "settled"}:
            raise QuotaDomainError(
                QuotaErrorCode.RESERVATION_NOT_ACTIVE,
                f"Reservation is already terminal: {reservation['status']}",
            )

        metadata_base = {
            "operation_id": operation_id,
            "credits_micro": credits_micro,
            "usage_status": usage_status,
            "usage_source": usage_source,
            "pricing_key": pricing_key,
            "pricing_version": pricing_version,
        }
        if usage_status in {"pending", "unavailable"}:
            self._insert_ledger(
                connection,
                reservation_id=reservation_id,
                bucket_id=None,
                entry_type="settle",
                amount_micro=0,
                reserved_delta_micro=0,
                consumed_delta_micro=0,
                idempotency_key=f"{prefix}none",
                reason="usage_pending" if usage_status == "pending" else "usage_unavailable",
                metadata={**metadata_base, "over_limit": False},
                created_at=db_now,
            )
            connection.execute(
                update(QuotaReservationModel)
                .where(QuotaReservationModel.id == reservation_id)
                .values(status="settling", updated_at=db_now)
            )
            return UsageRecordResult(
                operation_id=operation_id,
                usage_source=usage_source if usage_source in {"provider", "estimated", "none"} else "provider",
                credits_micro=credits_micro,
                usage_status=usage_status,
                over_limit=False,
                pricing_key=pricing_key,
                pricing_version=pricing_version,
            )

        bucket_rows = self._reservation_buckets(connection, reservation_id)
        release_amount = min(int(reservation["reserved_micro"]), credits_micro)
        over_limit = False
        if not bucket_rows:
            self._insert_ledger(
                connection,
                reservation_id=reservation_id,
                bucket_id=None,
                entry_type="settle",
                amount_micro=credits_micro,
                reserved_delta_micro=-release_amount,
                consumed_delta_micro=credits_micro,
                idempotency_key=f"{prefix}none",
                reason="provider_usage",
                metadata={**metadata_base, "over_limit": False},
                created_at=db_now,
            )
        for bucket in bucket_rows:
            bucket_release = min(int(bucket["reserved_micro"]), release_amount)
            new_consumed = int(bucket["consumed_micro"]) + credits_micro
            limit = bucket["limit_micro"]
            bucket_over_limit = limit is not None and new_consumed > int(limit)
            over_limit = over_limit or bucket_over_limit
            self._insert_ledger(
                connection,
                reservation_id=reservation_id,
                bucket_id=bucket["id"],
                entry_type="settle",
                amount_micro=credits_micro,
                reserved_delta_micro=-bucket_release,
                consumed_delta_micro=credits_micro,
                idempotency_key=f"{prefix}{bucket['id']}",
                reason="provider_usage",
                metadata={**metadata_base, "over_limit": bucket_over_limit},
                created_at=db_now,
            )
            connection.execute(
                update(QuotaBucketModel)
                .where(QuotaBucketModel.id == bucket["id"])
                .values(
                    consumed_micro=new_consumed,
                    reserved_micro=max(0, int(bucket["reserved_micro"]) - bucket_release),
                    over_limit=bucket_over_limit,
                    version=int(bucket["version"]) + 1,
                    updated_at=db_now,
                )
            )
        connection.execute(
            update(QuotaReservationModel)
            .where(QuotaReservationModel.id == reservation_id)
            .values(
                reserved_micro=max(0, int(reservation["reserved_micro"]) - release_amount),
                settled_micro=int(reservation["settled_micro"]) + credits_micro,
                status="settling",
                over_limit=over_limit or bool(reservation["over_limit"]),
                updated_at=db_now,
            )
        )
        return UsageRecordResult(
            operation_id=operation_id,
            usage_source=usage_source if usage_source in {"provider", "estimated", "none"} else "provider",
            credits_micro=credits_micro,
            usage_status=usage_status,
            over_limit=over_limit,
            pricing_key=pricing_key,
            pricing_version=pricing_version,
        )

    def begin_reservation(
        self,
        reservation_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Move an admitted reservation into the running lease state."""
        at = _utc(now)
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                reservation = connection.execute(
                    select(QuotaReservationModel)
                    .where(QuotaReservationModel.id == reservation_id)
                    .with_for_update()
                ).mappings().first()
                if reservation is None or reservation["status"] not in _ACTIVE_RESERVATION_STATUSES:
                    return False
                if _aware(reservation["lease_expires_at"]) <= at:
                    self.finish_in_transaction(
                        connection,
                        FinishTurn(
                            reservation_id=reservation_id,
                            turn_id=reservation["turn_id"],
                            idempotency_key=f"begin-expiry:{reservation_id}",
                        ),
                        now=at,
                        terminal_status="expired",
                    )
                    return False
                connection.execute(
                    update(QuotaReservationModel)
                    .where(QuotaReservationModel.id == reservation_id)
                    .values(
                        status="running",
                        lease_expires_at=_db_time(at + timedelta(seconds=self.lease_seconds)),
                        last_heartbeat_at=_db_time(at),
                        updated_at=_db_time(at),
                    )
                )
                return True

    def finish_turn(
        self,
        command: FinishTurn,
        *,
        now: datetime | None = None,
    ) -> TurnFinishResult:
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                return self.finish_in_transaction(connection, command, now=now)

    def finish_in_transaction(
        self,
        connection: Connection,
        command: FinishTurn,
        *,
        now: datetime | None = None,
        terminal_status: str | None = None,
    ) -> TurnFinishResult:
        db_now = _db_time(_utc(now))
        prefix = f"finish:{command.idempotency_key}:"
        reservation = connection.execute(
            select(QuotaReservationModel)
            .where(QuotaReservationModel.id == command.reservation_id)
            .with_for_update()
        ).mappings().first()
        if reservation is None:
            raise QuotaDomainError(
                QuotaErrorCode.RESERVATION_NOT_ACTIVE,
                f"Reservation {command.reservation_id!r} does not exist",
            )
        existing = connection.execute(
            select(QuotaLedgerEntryModel)
            .where(
                QuotaLedgerEntryModel.reservation_id == command.reservation_id,
                QuotaLedgerEntryModel.entry_type == "release",
                QuotaLedgerEntryModel.idempotency_key.like(f"{prefix}%"),
            )
            .limit(1)
        ).mappings().first()
        if existing is not None:
            metadata = existing["metadata_json"]
            return TurnFinishResult(
                reservation_id=command.reservation_id,
                status=metadata["status"],
                released_micro=int(metadata["released_micro"]),
            )
        if reservation["turn_id"] != command.turn_id:
            raise QuotaDomainError(
                QuotaErrorCode.RESERVATION_CONFLICT,
                "Finish command does not match the reservation Turn",
            )
        if reservation["status"] in {"settled", "released", "expired"}:
            return TurnFinishResult(
                reservation_id=command.reservation_id,
                status=reservation["status"],
                released_micro=0,
            )
        released = int(reservation["reserved_micro"])
        bucket_rows = self._reservation_buckets(connection, command.reservation_id)
        status = terminal_status or ("settled" if int(reservation["settled_micro"]) > 0 else "released")
        if not bucket_rows:
            self._insert_ledger(
                connection,
                reservation_id=command.reservation_id,
                bucket_id=None,
                entry_type="release",
                amount_micro=-released,
                reserved_delta_micro=-released,
                consumed_delta_micro=0,
                idempotency_key=f"{prefix}none",
                reason="turn_finished" if status == "settled" else "reservation_expired",
                metadata={"status": status, "released_micro": released},
                created_at=db_now,
            )
        for bucket in bucket_rows:
            bucket_release = min(int(bucket["reserved_micro"]), released)
            self._insert_ledger(
                connection,
                reservation_id=command.reservation_id,
                bucket_id=bucket["id"],
                entry_type="release",
                amount_micro=-bucket_release,
                reserved_delta_micro=-bucket_release,
                consumed_delta_micro=0,
                idempotency_key=f"{prefix}{bucket['id']}",
                reason="turn_finished" if status == "settled" else "reservation_expired",
                metadata={"status": status, "released_micro": released},
                created_at=db_now,
            )
            connection.execute(
                update(QuotaBucketModel)
                .where(QuotaBucketModel.id == bucket["id"])
                .values(
                    reserved_micro=max(0, int(bucket["reserved_micro"]) - bucket_release),
                    version=int(bucket["version"]) + 1,
                    updated_at=db_now,
                )
            )
        connection.execute(
            update(QuotaReservationModel)
            .where(QuotaReservationModel.id == command.reservation_id)
            .values(
                reserved_micro=0,
                status=status,
                lease_expires_at=db_now,
                updated_at=db_now,
            )
        )
        return TurnFinishResult(
            reservation_id=command.reservation_id,
            status=status,
            released_micro=released,
        )

    def release_reservation(
        self,
        reservation_id: str,
        *,
        turn_id: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> TurnFinishResult:
        return self.finish_turn(
            FinishTurn(
                reservation_id=reservation_id,
                turn_id=turn_id,
                idempotency_key=idempotency_key,
            ),
            now=now,
        )

    def expire_reservations(self, *, now: datetime | None = None) -> int:
        at = _utc(now)
        count = 0
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                stale = connection.execute(
                    select(QuotaReservationModel.id, QuotaReservationModel.turn_id)
                    .where(
                        QuotaReservationModel.status.in_(_ACTIVE_RESERVATION_STATUSES),
                        QuotaReservationModel.lease_expires_at <= _db_time(at),
                    )
                    .with_for_update()
                ).mappings().all()
                for row in stale:
                    self.finish_in_transaction(
                        connection,
                        FinishTurn(
                            reservation_id=row["id"],
                            turn_id=row["turn_id"],
                            idempotency_key=f"expiry:{row['id']}",
                        ),
                        now=at,
                        terminal_status="expired",
                    )
                    count += 1
        return count

    def heartbeat(
        self,
        reservation_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        at = _utc(now)
        with _GLOBAL_QUOTA_LOCK:
            with self._engine.begin() as connection:
                reservation = connection.execute(
                    select(QuotaReservationModel)
                    .where(QuotaReservationModel.id == reservation_id)
                    .with_for_update()
                ).mappings().first()
                if reservation is None or reservation["status"] not in _ACTIVE_RESERVATION_STATUSES:
                    return False
                if _aware(reservation["lease_expires_at"]) <= at:
                    self.finish_in_transaction(
                        connection,
                        FinishTurn(
                            reservation_id=reservation_id,
                            turn_id=reservation["turn_id"],
                            idempotency_key=f"heartbeat-expiry:{reservation_id}",
                        ),
                        now=at,
                        terminal_status="expired",
                    )
                    return False
                connection.execute(
                    update(QuotaReservationModel)
                    .where(QuotaReservationModel.id == reservation_id)
                    .values(
                        lease_expires_at=_db_time(at + timedelta(seconds=self.lease_seconds)),
                        last_heartbeat_at=_db_time(at),
                        updated_at=_db_time(at),
                    )
                )
                return True

    def snapshot(
        self,
        *,
        user_id: str,
        workspace_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        at = _utc(now)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(QuotaBucketModel)
                .where(
                    QuotaBucketModel.owner_type == "user",
                    QuotaBucketModel.owner_id == user_id,
                    QuotaBucketModel.period_start <= _db_time(at),
                    QuotaBucketModel.period_end > _db_time(at),
                )
            ).mappings().all()
        return {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "buckets": [
                {
                    "bucket_type": row["bucket_type"],
                    "limit_micro": row["limit_micro"],
                    "consumed_micro": row["consumed_micro"],
                    "reserved_micro": row["reserved_micro"],
                    "remaining_micro": self._available(row, 0),
                    "reset_at": _aware(row["period_end"]).isoformat(),
                    "over_limit": bool(row["over_limit"]),
                }
                for row in rows
            ],
        }

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def verify_schema(self) -> None:
        """Fail startup when Phase 2 migrations were not applied."""
        with self._engine.connect() as connection:
            for model in (
                QuotaPolicyModel,
                PolicyBindingModel,
                QuotaBucketModel,
                QuotaReservationModel,
                QuotaLedgerEntryModel,
            ):
                connection.execute(select(model.id).limit(1)).first()

    @staticmethod
    def _find_existing_reservation(
        connection: Connection, command: AdmitTurn
    ) -> dict[str, Any] | None:
        by_key = connection.execute(
            select(QuotaReservationModel)
            .where(QuotaReservationModel.idempotency_key == command.idempotency_key)
            .with_for_update()
        ).mappings().first()
        if by_key is not None:
            return dict(by_key)
        by_turn = connection.execute(
            select(QuotaReservationModel)
            .where(QuotaReservationModel.turn_id == command.turn_id)
            .with_for_update()
        ).mappings().first()
        return dict(by_turn) if by_turn is not None else None

    @staticmethod
    def _admission_result(row: dict[str, Any], *, duplicate: bool) -> TurnAdmissionResult:
        return TurnAdmissionResult(
            allowed=True,
            reservation_id=row["id"],
            reserved_micro=int(row["reserved_micro"]),
            policy_id=row["policy_id"],
            policy_version=row["policy_version"],
            duplicate=duplicate,
        )

    def _effective_binding(
        self,
        connection: Connection,
        command: AdmitTurn,
        *,
        role_codes: Sequence[str],
        classroom_ids: Sequence[str],
        at: datetime,
    ) -> PolicyBinding:
        policy_rows = connection.execute(select(QuotaPolicyModel)).mappings().all()
        policies = {row["id"]: row for row in policy_rows}
        bindings: list[PolicyBinding] = []
        for row in connection.execute(select(PolicyBindingModel)).mappings().all():
            policy_row = policies.get(row["policy_id"])
            if policy_row is None or row["status"] != "active" or policy_row["status"] != "active":
                continue
            effective_from = _aware(row["effective_from"])
            effective_until = _aware(row["effective_until"])
            if effective_from is None or not (effective_from <= at and (effective_until is None or at < effective_until)):
                continue
            policy_from = _aware(policy_row["effective_from"])
            policy_until = _aware(policy_row["effective_until"])
            if policy_from is None or not (policy_from <= at and (policy_until is None or at < policy_until)):
                continue
            bindings.append(
                PolicyBinding(
                    subject_type=row["subject_type"],
                    subject_id=row["subject_id"],
                    policy=QuotaPolicy(
                        policy_id=policy_row["id"],
                        code=policy_row["code"],
                        version=policy_row["version"],
                        request_limit_micro=policy_row["request_limit_micro"],
                        daily_limit_micro=policy_row["daily_limit_micro"],
                        monthly_limit_micro=policy_row["monthly_limit_micro"],
                        concurrency_limit=policy_row["concurrency_limit"],
                        max_overdraft_micro=policy_row["max_overdraft_micro"],
                        allowed_model_profiles=tuple(policy_row["allowed_model_profiles"] or ()),
                        unlimited=bool(policy_row["unlimited"]),
                    ),
                    priority=row["priority"],
                    effective_from=effective_from,
                    effective_until=effective_until,
                )
            )
        try:
            return resolve_effective_policy(
                bindings,
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                role_codes=role_codes,
                classroom_ids=classroom_ids,
                at=at,
            )
        except QuotaDomainError as error:
            raise self._rejection(error.code, str(error)) from error

    @staticmethod
    def _periods(policy: QuotaPolicy, at: datetime):
        if policy.unlimited:
            return []
        periods = []
        if policy.daily_limit_micro is not None:
            start = at.replace(hour=0, minute=0, second=0, microsecond=0)
            periods.append(("daily", start, start + timedelta(days=1), policy.daily_limit_micro))
        if policy.monthly_limit_micro is not None:
            start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            days = monthrange(start.year, start.month)[1]
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            periods.append(("monthly", start, end, policy.monthly_limit_micro))
        return periods

    @staticmethod
    def _estimate_micro(
        connection: Connection,
        command: AdmitTurn,
        at: datetime,
    ) -> int:
        """Conservatively price the input estimate plus the output reserve.

        A configured Gateway admission must never become a free request just
        because its pricing rule is missing.  Callers without a pricing key
        (the pure-domain tests and non-model administrative commands) retain
        an explicit zero estimate.
        """
        if command.pricing_key is None:
            return 0
        rows = connection.execute(
            select(PricingRuleModel)
            .where(
                PricingRuleModel.pricing_key == command.pricing_key,
                PricingRuleModel.status == "active",
                PricingRuleModel.effective_from <= _db_time(at),
                (PricingRuleModel.effective_until.is_(None))
                | (PricingRuleModel.effective_until > _db_time(at)),
            )
            .order_by(PricingRuleModel.effective_from.desc())
        ).mappings().all()
        if len(rows) != 1:
            raise QuotaDomainError(
                QuotaErrorCode.ADMISSION_DENIED,
                f"No unique active pricing rule exists for {command.pricing_key!r}",
            )
        row = rows[0]
        input_tokens = int(command.estimated_input_tokens or 0)
        output_tokens = int(command.estimated_output_tokens)
        output_rate = max(
            int(row["output_credits_micro_per_million_tokens"]),
            int(row["reasoning_output_credits_micro_per_million_tokens"] or 0),
        )
        numerator = (
            input_tokens
            * int(row["ordinary_input_credits_micro_per_million_tokens"])
            + output_tokens * output_rate
        )
        return (numerator + 1_000_000 - 1) // 1_000_000

    @staticmethod
    def _available(bucket: dict[str, Any], overdraft_micro: int) -> int:
        limit = bucket["limit_micro"]
        if limit is None:
            return 2**63 - 1
        return int(limit) + overdraft_micro - int(bucket["consumed_micro"]) - int(bucket["reserved_micro"])

    @staticmethod
    def _get_or_create_bucket(
        connection: Connection,
        *,
        owner_id: str,
        bucket_type: str,
        period_start: datetime,
        period_end: datetime,
        policy: QuotaPolicy,
        limit: int | None,
        now: datetime,
    ) -> dict[str, Any]:
        where = and_(
            QuotaBucketModel.owner_type == "user",
            QuotaBucketModel.owner_id == owner_id,
            QuotaBucketModel.bucket_type == bucket_type,
            QuotaBucketModel.period_start == _db_time(period_start),
            QuotaBucketModel.period_end == _db_time(period_end),
        )
        row = connection.execute(
            select(QuotaBucketModel).where(where).with_for_update()
        ).mappings().first()
        if row is None:
            values = {
                "id": str(uuid.uuid4()),
                "owner_type": "user",
                "owner_id": owner_id,
                "policy_id": policy.policy_id,
                "policy_version": policy.version,
                "bucket_type": bucket_type,
                "period_start": _db_time(period_start),
                "period_end": _db_time(period_end),
                "limit_micro": limit,
                "consumed_micro": 0,
                "reserved_micro": 0,
                "limit_revision": 1,
                "effective_policy_version": policy.version,
                "version": 1,
                "over_limit": False,
                "created_at": _db_time(now),
                "updated_at": _db_time(now),
            }
            if connection.dialect.name == "sqlite":
                # Admission is serialized by _GLOBAL_QUOTA_LOCK for the
                # embedded/SQLite runtime, so a savepoint is unnecessary and
                # would make rollback behavior harder to reason about.
                connection.execute(insert(QuotaBucketModel).values(**values))
            else:
                try:
                    with connection.begin_nested():
                        connection.execute(insert(QuotaBucketModel).values(**values))
                except IntegrityError:
                    pass
            row = connection.execute(
                select(QuotaBucketModel).where(where).with_for_update()
            ).mappings().one()
        elif row["limit_micro"] != limit or row["policy_version"] != policy.version:
            connection.execute(
                update(QuotaBucketModel)
                .where(QuotaBucketModel.id == row["id"])
                .values(
                    limit_micro=limit,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    effective_policy_version=policy.version,
                    limit_revision=int(row["limit_revision"]) + 1,
                    over_limit=(
                        limit is not None and int(row["consumed_micro"]) > int(limit)
                    ),
                    version=int(row["version"]) + 1,
                    updated_at=_db_time(now),
                )
            )
            row = connection.execute(
                select(QuotaBucketModel).where(QuotaBucketModel.id == row["id"]).with_for_update()
            ).mappings().one()
        return dict(row)

    @staticmethod
    def _reservation_buckets(connection: Connection, reservation_id: str) -> list[dict[str, Any]]:
        bucket_ids = connection.execute(
            select(QuotaLedgerEntryModel.bucket_id)
            .where(
                QuotaLedgerEntryModel.reservation_id == reservation_id,
                QuotaLedgerEntryModel.entry_type == "reserve",
                QuotaLedgerEntryModel.bucket_id.is_not(None),
            )
        ).scalars().all()
        if not bucket_ids:
            return []
        rows = connection.execute(
            select(QuotaBucketModel)
            .where(QuotaBucketModel.id.in_(bucket_ids))
            .with_for_update()
        ).mappings().all()
        return [dict(row) for row in rows]

    @staticmethod
    def _insert_ledger(
        connection: Connection,
        *,
        reservation_id: str | None,
        bucket_id: str | None,
        entry_type: str,
        amount_micro: int,
        reserved_delta_micro: int,
        consumed_delta_micro: int,
        idempotency_key: str,
        reason: str,
        metadata: dict[str, Any],
        created_at: datetime,
    ) -> None:
        connection.execute(
            insert(QuotaLedgerEntryModel).values(
                id=str(uuid.uuid4()),
                reservation_id=reservation_id,
                bucket_id=bucket_id,
                grant_id=None,
                entry_type=entry_type,
                amount_micro=amount_micro,
                reserved_delta_micro=reserved_delta_micro,
                consumed_delta_micro=consumed_delta_micro,
                idempotency_key=idempotency_key,
                actor_user_id=None,
                reason=reason,
                metadata_json=metadata,
                created_at=created_at,
            )
        )

    def _expire_stale_in_transaction(self, connection: Connection, at: datetime) -> None:
        rows = connection.execute(
            select(QuotaReservationModel.id, QuotaReservationModel.turn_id)
            .where(
                QuotaReservationModel.status.in_(_ACTIVE_RESERVATION_STATUSES),
                QuotaReservationModel.lease_expires_at <= _db_time(at),
            )
            .with_for_update()
        ).mappings().all()
        for row in rows:
            self.finish_in_transaction(
                connection,
                FinishTurn(
                    reservation_id=row["id"],
                    turn_id=row["turn_id"],
                    idempotency_key=f"expiry:{row['id']}",
                ),
                now=at,
                terminal_status="expired",
            )

    @staticmethod
    def _rejection(
        code: QuotaErrorCode,
        reason: str,
        *,
        remaining_micro: int = 0,
        reset_at: datetime | None = None,
        allowed_model_profiles: Sequence[str] = (),
        retryable: bool = False,
    ) -> QuotaRejectedError:
        return QuotaRejectedError(
            QuotaProblem(
                code=code,
                reason=reason,
                remaining_micro=remaining_micro,
                reset_at=_utc(reset_at) if reset_at is not None else None,
                allowed_model_profiles=tuple(allowed_model_profiles),
                retryable=retryable,
            )
        )
