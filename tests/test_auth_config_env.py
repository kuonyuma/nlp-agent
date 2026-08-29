from __future__ import annotations

from configs.settings import auth_env_bool, auth_env_int
from server.web.auth import SameOriginSessionAuth
from server.web.database_auth import DatabaseSessionAuth


def test_database_auth_reads_session_config_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("NLP_AGENT_AUTH_SESSION_TTL_S", "28800")
    monkeypatch.setenv("NLP_AGENT_AUTH_IDLE_TIMEOUT_S", "3600")
    monkeypatch.setenv("NLP_AGENT_AUTH_RATE_WINDOW_S", "900")
    monkeypatch.setenv("NLP_AGENT_AUTH_COOKIE_SECURE", "false")

    auth = DatabaseSessionAuth.from_config({})

    assert auth.ttl_s == 28800
    assert auth.idle_timeout_s == 3600
    assert auth._username_rate_limiter.window_s == 900
    assert auth.secure is False


def test_legacy_auth_reads_session_config_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("NLP_AGENT_AUTH_SESSION_TTL_S", "28800")
    monkeypatch.setenv("NLP_AGENT_AUTH_IDLE_TIMEOUT_S", "3600")

    auth = SameOriginSessionAuth.from_config({})

    assert auth.ttl_s == 28800
    assert auth.idle_timeout_s == 3600


def test_env_helpers_share_api_key_precedence(monkeypatch) -> None:
    monkeypatch.setenv("NLP_AGENT_AUTH_SESSION_TTL_S", "28800")
    monkeypatch.setenv("NLP_AGENT_AUTH_COOKIE_SECURE", "false")

    assert auth_env_int("NLP_AGENT_AUTH_SESSION_TTL_S", 1800) == 28800
    assert auth_env_bool("NLP_AGENT_AUTH_COOKIE_SECURE", True) is False
