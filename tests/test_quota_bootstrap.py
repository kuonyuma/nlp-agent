from sqlalchemy import create_engine
import pytest

from server.infrastructure.mysql.base import Base
from server.quota.models import (
    PolicyBindingModel,
    QuotaAdjustmentModel,
    QuotaBucketModel,
    QuotaConcurrencyLockModel,
    QuotaGrantModel,
    QuotaLedgerEntryModel,
    QuotaPolicyModel,
    QuotaReservationModel,
)
from server.quota.service import QuotaService


def test_usage_reporter_bootstrap_configures_and_cleans_up(monkeypatch):
    from server.quota import bootstrap

    configured = []
    monkeypatch.setattr(
        bootstrap,
        "configure_global_model_usage_reporter",
        lambda reporter: configured.append(reporter),
    )
    engine = create_engine("sqlite:///:memory:")
    reporter = bootstrap.configure_usage_reporter(engine)

    assert reporter is not None
    assert configured == [reporter]

    bootstrap.shutdown_usage_reporter(reporter)
    assert configured == [reporter, None]


def test_required_usage_reporter_rejects_missing_database_configuration():
    from server.quota import bootstrap

    with pytest.raises(bootstrap.UsageReporterConfigurationError, match="required"):
        bootstrap.configure_usage_reporter("", required=True)


def test_quota_schema_verification_probes_counter_primary_key():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            QuotaPolicyModel.__table__,
            PolicyBindingModel.__table__,
            QuotaBucketModel.__table__,
            QuotaConcurrencyLockModel.__table__,
            QuotaReservationModel.__table__,
            QuotaLedgerEntryModel.__table__,
            QuotaGrantModel.__table__,
            QuotaAdjustmentModel.__table__,
        ],
    )

    QuotaService(engine).verify_schema()

    with engine.connect() as connection:
        assert connection.execute(
            QuotaConcurrencyLockModel.__table__.select()
        ).first() is None
