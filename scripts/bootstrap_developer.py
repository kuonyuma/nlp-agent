"""Deployment-only bootstrap for the first Pro_NLP developer role.

Run after Alembic migration and user provisioning:
``uv run python scripts/bootstrap_developer.py --username <username>``.
The command refuses to run if an active developer assignment already exists.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select

from configs.settings import settings
from server.infrastructure.mysql import MySQLRuntime
from server.infrastructure.mysql.models import RoleModel, UserModel, UserRoleModel
from server.rbac.service import rbac_service


async def bootstrap(username: str) -> None:
    runtime = MySQLRuntime.from_runtime(settings.database_runtime)
    await runtime.start()
    try:
        async with runtime.session_factory() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(func.count(UserRoleModel.user_id))
                    .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(RoleModel.code == "developer", RoleModel.status == "active")
                )
                if int(existing or 0):
                    raise RuntimeError("an active developer role is already assigned")
                user = await session.scalar(
                    select(UserModel).where(
                        UserModel.username == username, UserModel.status == "active"
                    )
                )
                if user is None:
                    raise RuntimeError("active user was not found")
                await rbac_service.replace_user_roles(
                    session,
                    user_id=user.id,
                    role_codes={"developer"},
                    assigned_by_user_id=None,
                )
        print(f"developer role assigned to {username}")
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign the first Pro_NLP developer")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    asyncio.run(bootstrap(args.username))


if __name__ == "__main__":
    main()
