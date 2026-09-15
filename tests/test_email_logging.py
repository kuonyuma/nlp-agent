import pytest

from configs import settings as settings_module
from server.user.email_provider import (
    EmailConfigurationError,
    SmtpEmailProvider,
    create_email_provider_from_env,
    development_email_code_logging_enabled,
    mask_email_for_logging,
)


def test_mask_email_for_logging_keeps_only_safe_prefix_and_domain():
    assert mask_email_for_logging("user@example.com") == "u***@example.com"
    assert mask_email_for_logging("Alice.Smith@Sub.Domain.org") == "a***@sub.domain.org"


def test_development_email_code_logging_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("NLP_AGENT_EMAIL_EXPOSE_CODE", raising=False)
    assert development_email_code_logging_enabled() is False

    monkeypatch.setenv("NLP_AGENT_EMAIL_EXPOSE_CODE", "true")
    assert development_email_code_logging_enabled() is True


def test_email_provider_reads_smtp_values_from_project_dotenv(monkeypatch):
    values = {
        "NLP_AGENT_SMTP_HOST": "smtp.example.com",
        "NLP_AGENT_SMTP_USER": "mailer@example.com",
        "NLP_AGENT_SMTP_PASSWORD": "secret",
        "NLP_AGENT_SMTP_FROM": "Nova <mailer@example.com>",
        "NLP_AGENT_SMTP_PORT": "587",
        "NLP_AGENT_SMTP_SECURITY": "starttls",
    }
    for name, value in values.items():
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(settings_module._AUTH_DOTENV, name, value)

    provider = create_email_provider_from_env()

    assert isinstance(provider, SmtpEmailProvider)
    assert provider.host == "smtp.example.com"
    assert provider.port == 587
    assert provider.security == "starttls"


def test_email_provider_rejects_unknown_smtp_security(monkeypatch):
    for name, value in {
        "NLP_AGENT_SMTP_HOST": "smtp.example.com",
        "NLP_AGENT_SMTP_USER": "mailer@example.com",
        "NLP_AGENT_SMTP_PASSWORD": "secret",
        "NLP_AGENT_SMTP_FROM": "mailer@example.com",
        "NLP_AGENT_SMTP_SECURITY": "tls",
    }.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(EmailConfigurationError, match="SMTP_SECURITY"):
        create_email_provider_from_env()


@pytest.mark.parametrize("port", ["not-a-number", "0", "65536"])
def test_email_provider_rejects_invalid_smtp_port(monkeypatch, port):
    for name, value in {
        "NLP_AGENT_SMTP_HOST": "smtp.example.com",
        "NLP_AGENT_SMTP_USER": "mailer@example.com",
        "NLP_AGENT_SMTP_PASSWORD": "secret",
        "NLP_AGENT_SMTP_FROM": "mailer@example.com",
        "NLP_AGENT_SMTP_PORT": port,
    }.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(EmailConfigurationError, match="SMTP_PORT"):
        create_email_provider_from_env()
