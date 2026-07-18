from __future__ import annotations

from pathlib import Path

from configs import settings as settings_module
from configs.settings import Settings
from core import secret_cli


def test_windows_credential_source_precedes_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_module,
        "get_secret",
        lambda name: "credential-value" if name == "DEEPSEEK_API_KEY" else None,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-value")

    configured = Settings(_env_file=None)

    assert configured.secret_value("DEEPSEEK_API_KEY") == "credential-value"
    assert configured.model_dump(mode="json")["DEEPSEEK_API_KEY"] == "**********"


def test_migrate_env_removes_assignments_with_whitespace(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TAVILY_API_KEY = tavily-value\nREDIS_PASSWORD=redis-value\nREDIS_HOST=localhost\n",
        encoding="utf-8",
    )
    stored: dict[str, str] = {}
    monkeypatch.setattr(secret_cli, "set_secret", stored.__setitem__)

    assert secret_cli.run_secret_command(
        ["migrate-env", "--remove-from-env"], env_path=env_path
    ) == 0

    assert stored == {"TAVILY_API_KEY": "tavily-value", "REDIS_PASSWORD": "redis-value"}
    assert env_path.read_text(encoding="utf-8") == "REDIS_HOST=localhost\n"


def test_status_lists_managed_credentials_after_env_is_clean(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        secret_cli,
        "secret_status",
        lambda names: {name: name == "DEEPSEEK_API_KEY" for name in names},
    )

    assert secret_cli.run_secret_command(["status"], env_path=tmp_path / ".env") == 0

    output = capsys.readouterr().out
    assert "DEEPSEEK_API_KEY: Windows 凭据管理器" in output
    assert "TAVILY_API_KEY: 未配置" in output
