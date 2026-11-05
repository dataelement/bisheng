#!/usr/bin/env python3
"""Inspect, grant or revoke platform Super Admin identity.

Run from src/backend with the live service's config and environment::

    bash scripts/set_admin.sh 7 --action status
    bash scripts/set_admin.sh 7 --dry-run
    bash scripts/set_admin.sh 7
    bash scripts/set_admin.sh 7 --action revoke
    bash scripts/set_admin.sh 7 --action revoke --apply

The original positional-only invocation still grants immediately. Revocation
is preview-only unless --apply is supplied. User 1 can never be revoked.
DB roles, OpenFGA identity and caches must agree before success is reported.
Exit codes: 0 success/preview, 1 invalid target/precondition, 2 runtime or
partial-write failure. Re-run the same action after repairing connectivity.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.constants import AdminRole  # noqa: E402
from bisheng.database.models.role import Role  # noqa: E402
from bisheng.user.domain.models.user import User  # noqa: E402
from bisheng.user.domain.models.user_role import UserRole  # noqa: E402


async def _read_fga_super(user_id: int) -> bool:
    """Read through the permission application, bypassing cached decisions."""
    from bisheng.permission.application import (
        PermissionObject,
        PermissionSubject,
        get_permission_relation_api,
    )

    permissions = await get_permission_relation_api()
    return await permissions.check(
        subject=PermissionSubject("user", str(user_id)),
        relation="super_admin",
        resource=PermissionObject("system", "global"),
        consistency="HIGHER_CONSISTENCY",
    )


async def _invalidate_caches(user_id: int) -> None:
    """Clear this global identity's decisions across all tenant namespaces."""
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.permission.domain.services.permission_cache import KEY_PREFIX

    redis = await get_redis_client()
    for kind in ("chk", "lst"):
        # scan_iter also handles RedisCluster's per-node cursor dictionaries.
        async for key in redis.async_connection.scan_iter(match=f"{KEY_PREFIX}{kind}:*:{user_id}:*", count=100):
            await redis.async_connection.delete(key)
    await redis.adelete(f"user:{user_id}:is_super")


async def _sync_admin(user_id: int, action: str) -> None:
    """Use strict identity writes; same-action retries belong to this command."""
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService

    await PermissionService.batch_write_tuples(
        [
            TupleOperation(
                action="write" if action == "grant" else "delete",
                user=f"user:{user_id}",
                relation="super_admin",
                object="system:global",
            )
        ],
        raise_on_failure=True,
        stop_on_failure=True,
        recovery_owner="caller",
    )


async def set_admin(user_id: int, *, action: str = "grant", apply: bool | None = None) -> int:
    if user_id <= 0 or action not in {"status", "grant", "revoke"}:
        print("[set_admin] Invalid user ID or action.", file=sys.stderr)
        return 1
    if action == "revoke" and user_id == 1:
        print("[set_admin] The first administrator (user_id=1) cannot be revoked.", file=sys.stderr)
        return 1
    write = action != "status" and (apply if apply is not None else action == "grant")
    db_committed = False
    try:
        async with get_async_db_session() as session:
            # The super-admin identity is global; do not filter it to one tenant.
            with bypass_tenant_filter():
                if write:
                    # Serialize this script's role mutations across processes on
                    # MySQL and DM8, including the last-active-admin precheck.
                    role = (await session.exec(select(Role.id).where(Role.id == AdminRole).with_for_update())).first()
                    if role is None:
                        print("[set_admin] Built-in AdminRole is missing.", file=sys.stderr)
                        return 1
                user = (await session.exec(select(User).where(User.user_id == user_id))).first()
                if user is None:
                    print(f"[set_admin] User user_id={user_id} not found.", file=sys.stderr)
                    return 1
                print(
                    f"[set_admin] user_id={user_id} name={user.user_name!r} person_id={user.external_id!r} disabled={bool(user.delete)} action={action}"
                )
                if action == "grant" and user.delete:
                    print("[set_admin] A disabled user cannot be promoted.", file=sys.stderr)
                    return 1
                rows = (
                    await session.exec(
                        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == AdminRole)
                    )
                ).all()
                db_super = bool(rows)
                fga_super = await _read_fga_super(user_id)
                print(f"[set_admin] DB super_admin={db_super}; OpenFGA super_admin={fga_super}")
                if action == "status":
                    return 0 if db_super == fga_super else 2
                if action == "revoke":
                    others = (
                        await session.exec(
                            select(User.user_id)
                            .join(UserRole, UserRole.user_id == User.user_id)
                            .where(
                                UserRole.role_id == AdminRole,
                                User.user_id != user_id,
                                User.delete == 0,
                            )
                        )
                    ).all()
                    if not others:
                        print("[set_admin] Cannot revoke the last enabled administrator.", file=sys.stderr)
                        return 1
                if not write:
                    print("[set_admin] Preview only; no role, identity or cache changes made.")
                    return 0
                if action == "grant" and not rows:
                    session.add(UserRole(user_id=user_id, role_id=AdminRole, tenant_id=1))
                elif action == "revoke":
                    for row in rows:
                        await session.delete(row)
                await session.commit()
                db_committed = True

        # Force the requested transition even if the DB was already updated by
        # a previous attempt. This repairs partial failures on a same-action retry.
        await _sync_admin(user_id, action)
        await _invalidate_caches(user_id)
        actual = await _read_fga_super(user_id)
        if actual != (action == "grant"):
            raise RuntimeError("OpenFGA verification does not match the requested action")
        logger.info("Super-admin maintenance completed: user_id={} action={}", user_id, action)
        print(f"[set_admin] Done. user_id={user_id} super_admin={actual}.")
        return 0
    except Exception:
        logger.exception(
            "Super-admin maintenance failed: user_id={} action={} db_committed={}", user_id, action, db_committed
        )
        print(
            "[set_admin] Not complete. Inspect both stores, repair connectivity, then retry the SAME action. This command does not enqueue background compensation.",
            file=sys.stderr,
        )
        return 2


async def _run(user_id: int, *, action: str, apply: bool | None) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import app_context, close_app_context, initialize_app_context
    from bisheng.core.openfga.manager import FGAManager
    from bisheng.permission.application.process_runtime import (
        get_f048_process_runtime,
        initialize_f048_background_runtime,
        register_f048_permission_runtime_context,
    )

    try:
        if not settings.openfga.enabled:
            raise RuntimeError("OpenFGA must be enabled; DB-only changes are not supported")
        await initialize_app_context(config=settings)
        # The default OpenFGA context is lazy and has not opened a connection.
        # Replace it with discovery-only production policy, even on dev installs:
        # this maintenance command must never bootstrap a Store or publish a model.
        app_context.unregister_context("openfga")
        app_context.register_context(
            FGAManager(settings.openfga, environment="production", instance_role="maintenance"),
            lazy=True,
        )
        register_f048_permission_runtime_context(initialize_f048_background_runtime)
        await get_f048_process_runtime()
        return await set_admin(user_id, action=action, apply=apply)
    except Exception:
        logger.exception("Super-admin maintenance runtime failed")
        return 2
    finally:
        try:
            await close_app_context()
        finally:
            # ApplicationContextManager skips normal close until initialization
            # finishes. Explicitly close the registry after partial startup too.
            await app_context.get_registry().async_close_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user_id", type=int, help="Internal numeric user ID (not personnel ID)")
    parser.add_argument("--action", choices=("status", "grant", "revoke"), default="grant")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", dest="apply", action="store_true", default=None)
    mode.add_argument("--dry-run", dest="apply", action="store_false")
    args = parser.parse_args()
    if args.user_id <= 0:
        parser.error("user_id must be positive")
    if args.action == "status" and args.apply is not None:
        parser.error("status does not accept --apply or --dry-run")
    if args.action == "revoke" and args.user_id == 1:
        parser.error("the first administrator (user_id=1) cannot be revoked")
    return asyncio.run(_run(args.user_id, action=args.action, apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
