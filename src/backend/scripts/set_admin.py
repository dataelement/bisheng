#!/usr/bin/env python3
"""Set a user as the platform's Super Admin.

Usage:

    PYTHONPATH=./ .venv/bin/python scripts/set_admin.py <user_id>
    bash scripts/set_admin.sh <user_id>

What it does:

1. Verifies the user exists and is not soft-deleted.
2. Inserts ``(user_id, role_id=AdminRole)`` into ``userrole`` (legacy RBAC),
   skipping the insert when the row already exists.
3. Writes the OpenFGA tuple ``(user:{id}, super_admin, system:global)``
   through ``LegacyRBACSyncService`` so ReBAC checks return True.

Idempotent — running it twice on the same user is safe; the second run
re-syncs the OpenFGA tuple (FGA write is upsert) and reports a no-op for
the userrole row.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.constants import AdminRole  # noqa: E402
from bisheng.permission.domain.services.legacy_rbac_sync_service import (  # noqa: E402
    LegacyRBACSyncService,
)
from bisheng.user.domain.models.user import User  # noqa: E402
from bisheng.user.domain.models.user_role import UserRole  # noqa: E402


async def set_admin(user_id: int) -> int:
    async with get_async_db_session() as session:
        # User table has no tenant_id column but UserRole does — bypass the
        # auto-injected tenant filter so the script works regardless of which
        # tenant context (if any) was active at startup.
        with bypass_tenant_filter():
            user_row = await session.exec(
                select(User).where(User.user_id == user_id)
            )
            user = user_row.first()
            if user is None:
                print(
                    f'[set_admin] User user_id={user_id} not found.',
                    file=sys.stderr,
                )
                return 1
            if user.delete:
                print(
                    f'[set_admin] User user_id={user_id} ({user.user_name}) '
                    'is disabled (delete=1). Aborting.',
                    file=sys.stderr,
                )
                return 1

            existing_row = await session.exec(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id == AdminRole,
                )
            )
            already_admin = existing_row.first() is not None

            if already_admin:
                print(
                    f'[set_admin] user_id={user_id} ({user.user_name}) '
                    'already has AdminRole in userrole. '
                    'Re-syncing OpenFGA tuple to ensure ReBAC consistency.'
                )
            else:
                session.add(UserRole(user_id=user_id, role_id=AdminRole))
                await session.commit()
                print(
                    f'[set_admin] Granted AdminRole to user_id={user_id} '
                    f'({user.user_name}).'
                )

    try:
        await LegacyRBACSyncService.sync_user_role_change(
            user_id=user_id,
            old_role_ids=[],
            new_role_ids=[AdminRole],
        )
        print(
            f'[set_admin] OpenFGA tuple '
            f'(user:{user_id}, super_admin, system:global) synced.'
        )
    except Exception as exc:
        # Legacy RBAC fallback still works even when the FGA write fails, but
        # ReBAC checks will not return super-admin until the tuple lands.
        # Surface this clearly with a non-zero exit code so the operator knows
        # to investigate OpenFGA connectivity.
        print(
            f'[set_admin] WARNING: failed to write OpenFGA tuple: {exc}',
            file=sys.stderr,
        )
        return 2

    print(f'[set_admin] Done. user_id={user_id} is now Super Admin.')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('user_id', type=int, help='Target user ID')
    args = parser.parse_args()

    if args.user_id <= 0:
        print('[set_admin] user_id must be a positive integer.', file=sys.stderr)
        return 1

    return asyncio.run(set_admin(args.user_id))


if __name__ == '__main__':
    sys.exit(main())
