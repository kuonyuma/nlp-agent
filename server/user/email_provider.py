"""Generic SMTP email provider for verification codes.

Replaces the retired Tencent Cloud SMS channel.  A single SMTP implementation
covers every provider that exposes an SMTP endpoint — a personal mailbox
(QQ / 163 / Gmail / Outlook authorization code) as well as transactional
services (Resend / Brevo / SendGrid / Amazon SES) — so switching providers is
a configuration change, not a code change.

Required environment variables for real delivery:
- NLP_AGENT_SMTP_HOST: SMTP server host (e.g. smtp.qq.com)
- NLP_AGENT_SMTP_USER: SMTP login user (usually the sender mailbox)
- NLP_AGENT_SMTP_PASSWORD: SMTP password / authorization code
- NLP_AGENT_SMTP_FROM: sender address shown to recipients

Optional:
- NLP_AGENT_SMTP_PORT (default 465)
- NLP_AGENT_SMTP_SECURITY: "ssl" | "starttls" | "none" (default "ssl")
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional, Protocol

from configs.settings import auth_env_bool, auth_env_value

logger = logging.getLogger(__name__)


def mask_email_for_logging(email: str) -> str:
    """Keep the first local character and the domain for operational logs."""
    value = email.strip().casefold()
    local, _, domain = value.partition("@")
    if not domain:
        return "<invalid-email>"
    head = local[:1] or "*"
    return f"{head}***@{domain}"


def development_email_code_logging_enabled() -> bool:
    """Return whether a local developer explicitly opted into code logging."""
    return auth_env_bool("NLP_AGENT_EMAIL_EXPOSE_CODE", False)


class EmailProvider(Protocol):
    async def send_verification_code(self, email: str, code: str) -> bool: ...


class SmtpEmailProvider:
    """Send verification codes through any standard SMTP server."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        security: str = "ssl",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.security = security

    def _send_sync(self, to: str, code: str) -> None:
        message = MIMEText(
            f"你的 Nova 验证码是 {code}，2 分钟内有效。如非本人操作请忽略本邮件。",
            "plain",
            "utf-8",
        )
        message["Subject"] = "Nova 邮箱验证码"
        message["From"] = self.sender
        message["To"] = to

        if self.security == "ssl":
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=15)
            server.ehlo()
            if self.security == "starttls":
                server.starttls()
                server.ehlo()
        try:
            if self.username:
                server.login(self.username, self.password)
            server.sendmail(self.sender, [to], message.as_string())
        finally:
            server.quit()

    async def send_verification_code(self, email: str, code: str) -> bool:
        """Send a verification code; returns True on success."""
        try:
            # smtplib is a blocking socket API; keep it off the event loop.
            await asyncio.to_thread(self._send_sync, email, code)
            logger.info(
                "[SMTP] Successfully sent verification code to %s",
                mask_email_for_logging(email),
            )
            return True
        except Exception as e:  # noqa: BLE001 - delivery failures must not crash
            logger.error(
                "[SMTP] Exception sending code to %s: %s",
                mask_email_for_logging(email),
                e,
            )
            return False


class DeterministicEmailProvider:
    """Explicit local provider used only by the real HTTP test environment."""

    def __init__(self, *, failure_prefix: str = "") -> None:
        self.failure_prefix = failure_prefix

    async def send_verification_code(self, email: str, code: str) -> bool:
        del code
        return not self.failure_prefix or not email.strip().startswith(self.failure_prefix)


class EmailConfigurationError(RuntimeError):
    """Raised when production email delivery has not been configured."""


def create_email_provider_from_env() -> Optional[EmailProvider]:
    """Create an SMTP email provider from environment variables.

    Returns a provider when SMTP credentials are present, a deterministic stub
    for the HTTP test environment, or ``None`` when development mode is on.
    """
    if (auth_env_value("NLP_AGENT_API_HTTP_EMAIL_PROVIDER", "") or "").strip().lower() == "stub":
        return DeterministicEmailProvider(
            failure_prefix=(
                auth_env_value("NLP_AGENT_API_HTTP_EMAIL_FAILURE_PREFIX", "") or ""
            ).strip()
        )

    host = auth_env_value("NLP_AGENT_SMTP_HOST")
    username = auth_env_value("NLP_AGENT_SMTP_USER")
    password = auth_env_value("NLP_AGENT_SMTP_PASSWORD")
    sender = auth_env_value("NLP_AGENT_SMTP_FROM")
    raw_port = auth_env_value("NLP_AGENT_SMTP_PORT", "465") or "465"
    security = (auth_env_value("NLP_AGENT_SMTP_SECURITY", "ssl") or "ssl").strip().lower()

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise EmailConfigurationError("NLP_AGENT_SMTP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise EmailConfigurationError("NLP_AGENT_SMTP_PORT must be between 1 and 65535")
    if security not in {"ssl", "starttls", "none"}:
        raise EmailConfigurationError(
            "NLP_AGENT_SMTP_SECURITY must be one of: ssl, starttls, none"
        )

    if not all([host, username, password, sender]):
        if auth_env_bool("NLP_AGENT_EMAIL_DEVELOPMENT_MODE", False):
            return None
        raise EmailConfigurationError(
            "Email delivery is not configured; set NLP_AGENT_SMTP_* or explicitly enable NLP_AGENT_EMAIL_DEVELOPMENT_MODE"
        )

    return SmtpEmailProvider(
        host=host,
        port=port,
        username=username,
        password=password,
        sender=sender,
        security=security,
    )
