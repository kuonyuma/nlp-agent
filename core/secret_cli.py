"""Hidden-input command line administration for local credentials."""

from __future__ import annotations

import getpass
import re
from pathlib import Path

from dotenv import dotenv_values

from core.secret_store import (
    MANAGED_SECRET_NAMES,
    SecretStoreUnavailable,
    delete_secret,
    looks_like_secret_name,
    secret_status,
    set_secret,
)


def _env_secrets(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    return {
        name: value
        for name, value in dotenv_values(env_path).items()
        if value and looks_like_secret_name(name)
    }


def _remove_env_secrets(env_path: Path, names: set[str]) -> None:
    """Remove migrated assignments while preserving non-secret configuration."""
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    assignment = re.compile(
        r"^\s*(?:export\s+)?(" + "|".join(map(re.escape, names)) + r")\s*=",
        flags=re.IGNORECASE,
    )
    retained = [line for line in lines if not assignment.match(line)]
    env_path.write_text("".join(retained), encoding="utf-8")


def run_secret_command(arguments: list[str], *, env_path: Path) -> int:
    """Run ``main.py secrets`` commands and return a process exit code."""
    command = arguments[0] if arguments else "status"
    try:
        if command == "status":
            values = _env_secrets(env_path)
            names = sorted(set(values) | set(MANAGED_SECRET_NAMES))
            states = secret_status(names)
            for name in names:
                location = (
                    "Windows 凭据管理器"
                    if states[name]
                    else ".env（待迁移）"
                    if name in values
                    else "未配置"
                )
                print(f"{name}: {location}")
            return 0

        if command == "set" and len(arguments) == 2:
            name = arguments[1]
            set_secret(name, getpass.getpass(f"请输入 {name}（输入不回显）: "))
            print(f"已保存 {name} 到 Windows 凭据管理器。")
            return 0

        if command == "setup":
            saved = 0
            print("逐项输入密钥；直接回车会跳过该项，输入不会回显。")
            for name in MANAGED_SECRET_NAMES:
                value = getpass.getpass(f"{name}: ")
                if value:
                    set_secret(name, value)
                    saved += 1
            print(f"已保存 {saved} 项到 Windows 凭据管理器。")
            return 0

        if command == "delete" and len(arguments) == 2:
            name = arguments[1]
            print("已删除。" if delete_secret(name) else "该密钥不存在。")
            return 0

        if command == "migrate-env":
            values = _env_secrets(env_path)
            for name, value in values.items():
                set_secret(name, value)
            if "--remove-from-env" in arguments:
                _remove_env_secrets(env_path, set(values))
                print(f"已迁移并从 .env 删除 {len(values)} 个密钥。")
            else:
                print(
                    f"已迁移 {len(values)} 个密钥到 Windows 凭据管理器。"
                    "确认服务可用后，可执行 `python main.py secrets migrate-env --remove-from-env` 删除 .env 中的明文。"
                )
            return 0
    except (SecretStoreUnavailable, ValueError) as exc:
        print(f"密钥操作失败：{exc}")
        return 1

    print("用法：python main.py secrets [status|setup|set NAME|delete NAME|migrate-env [--remove-from-env]]")
    return 2
