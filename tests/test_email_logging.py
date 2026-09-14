from server.user.email_provider import (
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
