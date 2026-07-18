"""OS-backed secret storage used by Settings and local administration commands.

Pydantic's ``SecretStr`` prevents accidental disclosure in logs and serialized
settings. It deliberately does not encrypt values at rest, so local secrets
are persisted in the operating system credential store through ``keyring``.
"""

from __future__ import annotations

from collections.abc import Iterable


SERVICE_NAME = "Pro_NLP"
MANAGED_SECRET_NAMES = (
    "AMAP_API_KEY",
    "ARK_API_KEY",
    "DEEPSEEK_API_KEY",
    "LANGCHAIN_API_KEY",
    "MYSQL_PASSWORD",
    "NLP_AGENT_WEB_SECRET",
    "QWEATHER_API_KEY",
    "REDIS_PASSWORD",
    "TAVILY_API_KEY",
    "aliyun_API_KEY",
    "volcengine_API_KEY",
)


class SecretStoreUnavailable(RuntimeError):
    """Raised when the operating-system credential backend cannot be used."""



def _keyring():
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise SecretStoreUnavailable("缺少 keyring 依赖。请执行 `uv sync` 后重试。") from exc
    return keyring, KeyringError


def get_secret(name: str) -> str | None:
    """Read one secret without ever logging its value."""
    keyring, keyring_error = _keyring()
    try:
        return keyring.get_password(SERVICE_NAME, name)
    except keyring_error as exc:
        raise SecretStoreUnavailable(f"无法读取系统凭据库：{exc}") from exc


def set_secret(name: str, value: str) -> None:
    """Store one non-empty value in the operating-system credential store."""
    if not value:
        raise ValueError("密钥不能为空")
    keyring, keyring_error = _keyring()
    try:
        keyring.set_password(SERVICE_NAME, name, value)
    except keyring_error as exc:
        raise SecretStoreUnavailable(f"无法写入系统凭据库：{exc}") from exc


def delete_secret(name: str) -> bool:
    """Delete one credential and return whether it existed."""
    keyring, keyring_error = _keyring()
    try:
        if keyring.get_password(SERVICE_NAME, name) is None:
            return False
        keyring.delete_password(SERVICE_NAME, name)
        return True
    except keyring_error as exc:
        raise SecretStoreUnavailable(f"无法删除系统凭据库中的密钥：{exc}") from exc


def secret_status(names: Iterable[str]) -> dict[str, bool]:
    """Return presence only; callers must never display secret values."""
    return {name: bool(get_secret(name)) for name in names}


def looks_like_secret_name(name: str) -> bool:
    """Classify conventional environment-variable names for migration."""
    normalized = name.upper()
    return normalized.endswith(("_API_KEY", "_PASSWORD", "_SECRET", "_TOKEN"))
