from sqlalchemy import create_engine
import pytest


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
