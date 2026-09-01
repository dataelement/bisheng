#!/usr/bin/env python3
"""Remove resource permissions created specifically for user-group admins.

F006 migrated legacy ``groupresource`` rows into OpenFGA tuples shaped as::

    user_group:<group_id>#admin --manager--> <resource_type>:<resource_id>

The business rule does not give user-group administrators elevated resource
permissions. They should receive resource access only through normal user-group
membership. The authorization model already makes ``user_group#admin`` a member,
so removing these ``manager`` tuples keeps ordinary ``user_group#member`` grants
effective while removing the unintended elevation.

Run from ``src/backend`` with the same ``config`` used by the service::

    config=config.yaml PYTHONPATH=./ .venv/bin/python \
        scripts/clean_user_group_admin_resource_grants.py
    config=config.yaml PYTHONPATH=./ .venv/bin/python \
        scripts/clean_user_group_admin_resource_grants.py --apply

Dry-run is the default. The script loads all user groups from the database, then
queries OpenFGA by the exact ``user_group:<id>#admin`` subject, ``manager``
relation, and each F006 resource object type. ``--apply`` first disables pending
compensation writes that could recreate a matching tuple, then deletes every
matching tuple, invalidates permission caches, and verifies no target tuple or
retryable write remains.

The script intentionally does not delete ``groupresource`` rows: that legacy
table is still used by audit filters, dashboards, and user-group resource views.
It also does not delete user-group ``admin`` or ``member`` membership tuples.
Do not replay F006 migration step 8 after cleanup; that historical migration
step reconstructs the legacy tuples from ``groupresource``. If it is replayed,
run this cleanup again.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402

ADMIN_SUBJECT_RE = re.compile(r"^user_group:(?P<group_id>\d+)#admin$")
TARGET_RELATION = "manager"
RETRY_LOCK_KEY = "bisheng:lock:retry_failed_tuples"
RETRY_LOCK_TTL_SECONDS = 600
DEAD_REASON = "Disabled by clean_user_group_admin_resource_grants: user-group admins inherit member access only"


@dataclass(frozen=True, order=True)
class AdminResourceGrant:
    user: str
    relation: str
    object: str

    @property
    def group_id(self) -> int:
        match = ADMIN_SUBJECT_RE.fullmatch(self.user)
        if match is None:
            raise ValueError(f"Invalid user-group admin subject: {self.user}")
        return int(match.group("group_id"))

    @property
    def object_type(self) -> str:
        return self.object.partition(":")[0] or "<invalid>"


@dataclass(frozen=True, order=True)
class PendingAdminWrite:
    id: int
    user: str
    relation: str
    object: str


def _is_target(user: str, relation: str, object_name: str) -> bool:
    return bool(
        ADMIN_SUBJECT_RE.fullmatch(user)
        and relation == TARGET_RELATION
        and ":" in object_name
        and not object_name.startswith("user_group:")
    )


def _normalize_grants(tuples: Iterable[dict]) -> list[AdminResourceGrant]:
    grants = {
        AdminResourceGrant(
            user=str(item.get("user", "")),
            relation=str(item.get("relation", "")),
            object=str(item.get("object", "")),
        )
        for item in tuples
        if _is_target(
            str(item.get("user", "")),
            str(item.get("relation", "")),
            str(item.get("object", "")),
        )
    }
    return sorted(grants)


async def _load_group_ids() -> list[int]:
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.group import Group

    async with get_async_db_session() as session:
        result = await session.exec(select(Group.id).order_by(Group.id))
        return [int(group_id) for group_id in result.all() if group_id is not None]


def _target_object_types() -> tuple[str, ...]:
    from bisheng.permission.migration.f006_constants import GROUP_RESOURCE_TYPE_MAPPING

    return tuple(
        sorted({object_type for object_types in GROUP_RESOURCE_TYPE_MAPPING.values() for object_type in object_types})
    )


async def _load_fga_targets(group_ids: Iterable[int]) -> list[AdminResourceGrant]:
    from bisheng.core.openfga.manager import aget_fga_client

    fga = await aget_fga_client()
    if fga is None:
        raise RuntimeError("OpenFGA client is unavailable; refusing to continue")

    tuples: list[dict] = []
    for group_id in sorted(set(group_ids)):
        user = f"user_group:{group_id}#admin"
        for object_type in _target_object_types():
            tuples.extend(
                await fga.read_tuples(
                    user=user,
                    relation=TARGET_RELATION,
                    object=f"{object_type}:",
                )
            )
    return _normalize_grants(tuples)


async def _load_pending_admin_writes() -> list[PendingAdminWrite]:
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.failed_tuple import FailedTuple

    async with get_async_db_session() as session:
        result = await session.exec(
            select(FailedTuple).where(
                FailedTuple.status == "pending",
                FailedTuple.action == "write",
                FailedTuple.relation == TARGET_RELATION,
            )
        )
        pending = []
        for item in result.all():
            if item.id is None or not _is_target(item.fga_user, item.relation, item.object):
                continue
            pending.append(
                PendingAdminWrite(
                    id=int(item.id),
                    user=item.fga_user,
                    relation=item.relation,
                    object=item.object,
                )
            )
        return sorted(pending)


async def _mark_pending_admin_writes_dead(pending_ids: list[int]) -> int:
    if not pending_ids:
        return 0

    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.failed_tuple import FailedTuple

    updated = 0
    async with get_async_db_session() as session:
        result = await session.exec(
            select(FailedTuple).where(
                FailedTuple.id.in_(pending_ids),
                FailedTuple.status == "pending",
                FailedTuple.action == "write",
                FailedTuple.relation == TARGET_RELATION,
            )
        )
        for item in result.all():
            if not _is_target(item.fga_user, item.relation, item.object):
                continue
            item.status = "dead"
            item.error_message = DEAD_REASON
            session.add(item)
            updated += 1
        await session.commit()
    return updated


async def _delete_grants(grants: list[AdminResourceGrant]) -> None:
    if not grants:
        return

    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService

    operations = [
        TupleOperation(
            action="delete",
            user=grant.user,
            relation=grant.relation,
            object=grant.object,
        )
        for grant in grants
    ]
    await PermissionService.batch_write_tuples(
        operations,
        crash_safe=True,
        raise_on_failure=True,
        stop_on_failure=True,
    )


async def _invalidate_permission_cache() -> None:
    from bisheng.permission.domain.services.permission_cache import PermissionCache

    await PermissionCache.invalidate_all()


@asynccontextmanager
async def _hold_retry_lock() -> AsyncIterator[None]:
    from bisheng.core.cache.redis_manager import get_redis_client

    redis = await get_redis_client()
    owner = f"clean-user-group-admin-resource-grants:{uuid.uuid4()}"
    acquired = await redis.asetNx(RETRY_LOCK_KEY, owner, expiration=RETRY_LOCK_TTL_SECONDS)
    if not acquired:
        raise RuntimeError(
            "The failed-tuple retry lock is busy; wait for the current retry cycle and run the script again"
        )
    try:
        yield
    finally:
        try:
            if await redis.aget(RETRY_LOCK_KEY) == owner:
                await redis.adelete(RETRY_LOCK_KEY)
        except Exception:
            logger.exception("Failed to release retry lock {}; it will expire by TTL", RETRY_LOCK_KEY)
            raise


def _report(
    group_ids: list[int],
    grants: list[AdminResourceGrant],
    pending: list[PendingAdminWrite],
    sample_limit: int,
) -> None:
    by_type: dict[str, int] = {}
    affected_group_ids: set[int] = set()
    for grant in grants:
        by_type[grant.object_type] = by_type.get(grant.object_type, 0) + 1
        affected_group_ids.add(grant.group_id)

    logger.info(
        "Scanned {} user group(s); found {} user-group-admin manager tuple(s) "
        "across {} affected group(s); pending retry writes={}",
        len(group_ids),
        len(grants),
        len(affected_group_ids),
        len(pending),
    )
    for object_type, count in sorted(by_type.items()):
        logger.info("  object_type={} tuples={}", object_type, count)
    for grant in grants[:sample_limit]:
        logger.info("  tuple: {} --{}--> {}", grant.user, grant.relation, grant.object)
    if len(grants) > sample_limit:
        logger.info("  ... {} more tuple(s) omitted; use --sample-limit to display more", len(grants) - sample_limit)
    for item in pending[:sample_limit]:
        logger.info("  pending write id={}: {} --{}--> {}", item.id, item.user, item.relation, item.object)
    if len(pending) > sample_limit:
        logger.info("  ... {} more pending write(s) omitted", len(pending) - sample_limit)


async def run(*, apply: bool, sample_limit: int) -> int:
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter():
        if not apply:
            group_ids = await _load_group_ids()
            grants = await _load_fga_targets(group_ids)
            pending = await _load_pending_admin_writes()
            _report(group_ids, grants, pending, sample_limit)
            logger.info("[dry-run] no changes written. Re-run with --apply to execute.")
            return 0

        async with _hold_retry_lock():
            group_ids = await _load_group_ids()
            grants = await _load_fga_targets(group_ids)
            pending = await _load_pending_admin_writes()
            _report(group_ids, grants, pending, sample_limit)

            marked_dead = await _mark_pending_admin_writes_dead([item.id for item in pending])
            await _delete_grants(grants)
            await _invalidate_permission_cache()

            remaining_grants = await _load_fga_targets(group_ids)
            remaining_pending = await _load_pending_admin_writes()
            if remaining_grants or remaining_pending:
                raise RuntimeError(
                    "Cleanup verification failed: "
                    f"remaining tuples={len(remaining_grants)}, pending writes={len(remaining_pending)}"
                )

            logger.info(
                "Cleanup verified: deleted {} tuple(s), disabled {} pending write(s), residual=0",
                len(grants),
                marked_dead,
            )
            return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the cleanup. Without this flag the script is read-only.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=50,
        help="Maximum matching tuples and pending writes to print (default: 50).",
    )
    args = parser.parse_args()
    if args.sample_limit < 0:
        parser.error("--sample-limit must be zero or greater")
    return args


def main() -> int:
    args = _parse_args()

    async def _amain() -> int:
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.manager import close_app_context, initialize_app_context

        await initialize_app_context(config=settings)
        try:
            return await run(apply=args.apply, sample_limit=args.sample_limit)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
