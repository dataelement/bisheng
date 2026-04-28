"""Reconcile role_access (MySQL) ↔ OpenFGA tuples for resource permissions.

After the RBAC→ReBAC migration (F006 step3), the old role_access/refresh API
continued to update MySQL without syncing FGA. This script rebuilds the
per-user FGA tuples so they match the current MySQL role_access state.

Algorithm:
  1. Read all non-WEB_MENU role_access rows and expand via user_role to
     per-user (user_id, object_type, relation, resource_id) tuples — the
     "desired" set.
  2. Read existing user:* FGA tuples for users that currently belong to roles.
  3. Diff: write desired tuples missing from FGA; delete stale user:* tuples
     only when they are not backed by an explicit resource permission binding.

Usage:
    python -m bisheng.permission.migration.reconcile_role_access_fga
    python -m bisheng.permission.migration.reconcile_role_access_fga --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import text as sa_text

# Re-use the same mapping as the original migration
ACCESS_TYPE_MAPPING: dict[int, tuple[str, str]] = {
    1: ('knowledge_library', 'viewer'),
    3: ('knowledge_library', 'editor'),
    5: ('assistant', 'viewer'),
    6: ('assistant', 'editor'),
    7: ('tool', 'viewer'),
    8: ('tool', 'editor'),
    9: ('workflow', 'viewer'),
    10: ('workflow', 'editor'),
    11: ('dashboard', 'viewer'),
    12: ('dashboard', 'editor'),
}

KNOWLEDGE_LEGACY_TYPES = {'knowledge_library': 'knowledge_space'}

RESOURCE_TYPES_WITH_FGA = sorted({obj_type for obj_type, _ in ACCESS_TYPE_MAPPING.values()})


@dataclass
class Stats:
    desired: int = 0
    actual: int = 0
    to_write: int = 0
    to_delete: int = 0
    protected: int = 0
    written: int = 0
    deleted: int = 0


async def _candidate_user_ids() -> set[int]:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import AdminRole

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            result = await session.execute(
                sa_text('SELECT DISTINCT user_id FROM userrole WHERE role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            user_ids = {int(row[0]) for row in result.fetchall()}
            try:
                users = await session.execute(
                    sa_text('SELECT user_id FROM user WHERE `delete` = 0'),
                )
                user_ids.update(int(row[0]) for row in users.fetchall())
            except Exception as e:
                logger.warning(f'Failed to load all active users for stale tuple scan: {e}')
            return user_ids


async def _build_desired_set() -> set[tuple[str, str, str, str]]:
    """Return {(user, relation, object_type, resource_id)} from MySQL."""
    from bisheng.core.database import get_async_db_session
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.constants import AdminRole

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            ra_result = await session.execute(
                sa_text('SELECT role_id, third_id, type FROM roleaccess '
                        'WHERE type != 99 AND role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            role_accesses = ra_result.fetchall()

            ur_result = await session.execute(
                sa_text('SELECT user_id, role_id FROM userrole WHERE role_id != :admin_rid'),
                {'admin_rid': AdminRole},
            )
            user_roles = ur_result.fetchall()

    role_user_map: dict[int, list[int]] = {}
    for uid, rid in user_roles:
        role_user_map.setdefault(rid, []).append(uid)

    desired: set[tuple[str, str, str, str]] = set()
    for role_id, third_id, access_type in role_accesses:
        mapping = ACCESS_TYPE_MAPPING.get(access_type)
        if not mapping:
            continue
        obj_type, relation = mapping
        for uid in role_user_map.get(role_id, []):
            desired.add((f'user:{uid}', relation, obj_type, str(third_id)))
            legacy = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
            if legacy:
                desired.add((f'user:{uid}', relation, legacy, str(third_id)))
    return desired


def _all_role_access_object_types() -> set[str]:
    all_types = set(RESOURCE_TYPES_WITH_FGA)
    for obj_type in RESOURCE_TYPES_WITH_FGA:
        legacy = KNOWLEDGE_LEGACY_TYPES.get(obj_type)
        if legacy:
            all_types.add(legacy)
    return all_types


async def _build_actual_set(user_ids: set[int]) -> set[tuple[str, str, str, str]]:
    """Return {(user, relation, object_type, resource_id)} from FGA.

    Only considers current role users, not every OpenFGA tuple in the store.
    Only considers viewer/editor relations (the ones managed by role_access).
    """
    from bisheng.permission.domain.services.permission_service import PermissionService

    fga = PermissionService._get_fga()
    if fga is None:
        logger.error('FGAClient not available — cannot read actual tuples')
        return set()

    role_access_relations = {'viewer', 'editor'}
    actual: set[tuple[str, str, str, str]] = set()
    all_types = _all_role_access_object_types()

    for uid in user_ids:
        user_filter = f'user:{uid}'
        try:
            tuples = await fga.read_tuples(user=user_filter)
        except Exception as e:
            logger.warning(f'Failed to read tuples for {user_filter}: {e}')
            continue
        for t in tuples:
            user = t.get('user', '')
            obj = t.get('object', '')
            rel = t.get('relation', '')
            if user != user_filter or rel not in role_access_relations:
                continue
            parts = obj.split(':', 1)
            if len(parts) != 2:
                continue
            t_type, t_id = parts
            if t_type in all_types:
                actual.add((user, rel, t_type, t_id))
    return actual


async def _resource_permission_user_binding_set() -> set[tuple[str, str, str, str]]:
    """Return FGA tuple signatures backed by resource permission user bindings."""
    from bisheng.common.models.config import ConfigDao

    all_types = _all_role_access_object_types()
    bound: set[tuple[str, str, str, str]] = set()
    row = await ConfigDao.aget_config_by_key('permission_relation_model_bindings_v1')
    if not row or not (row.value or '').strip():
        return bound
    try:
        bindings = json.loads(row.value or '[]')
    except Exception:
        logger.warning('Failed to parse resource permission bindings config')
        return bound
    if not isinstance(bindings, list):
        return bound

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        resource_type = binding.get('resource_type')
        if resource_type not in all_types:
            continue
        if binding.get('subject_type') != 'user':
            continue
        relation = binding.get('relation')
        if relation not in {'viewer', 'editor'}:
            continue
        resource_id = str(binding.get('resource_id'))
        subject_id = binding.get('subject_id')
        if subject_id is None:
            continue
        bound.add((f'user:{subject_id}', relation, resource_type, resource_id))
        legacy = KNOWLEDGE_LEGACY_TYPES.get(resource_type)
        if legacy:
            bound.add((f'user:{subject_id}', relation, legacy, resource_id))
        if resource_type == 'knowledge_space':
            bound.add((f'user:{subject_id}', relation, 'knowledge_library', resource_id))
    return bound


async def reconcile(dry_run: bool = False) -> Stats:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.permission.domain.services.permission_cache import PermissionCache

    stats = Stats()

    logger.info('Building desired set from MySQL role_access ...')
    desired = await _build_desired_set()
    stats.desired = len(desired)
    logger.info(f'Desired tuples: {stats.desired}')

    role_user_ids = await _candidate_user_ids()
    logger.info(f'Candidate users for role_access FGA scan: {len(role_user_ids)}')

    logger.info('Building actual set from FGA ...')
    actual = await _build_actual_set(role_user_ids)
    stats.actual = len(actual)
    logger.info(f'Actual tuples: {stats.actual}')

    protected = await _resource_permission_user_binding_set()
    to_write = desired - actual
    stale = actual - desired
    to_delete = stale - protected
    stats.to_write = len(to_write)
    stats.to_delete = len(to_delete)
    stats.protected = len(stale & protected)

    logger.info(
        f'To write: {stats.to_write}, to delete: {stats.to_delete}, '
        f'protected by explicit bindings: {stats.protected}'
    )

    if dry_run:
        if to_delete:
            logger.info('Sample deletes (first 20):')
            for item in list(to_delete)[:20]:
                logger.info(f'  DELETE {item}')
        if to_write:
            logger.info('Sample writes (first 20):')
            for item in list(to_write)[:20]:
                logger.info(f'  WRITE  {item}')
        return stats

    operations: list[TupleOperation] = []
    affected_user_ids: set[int] = set()

    for user, relation, obj_type, resource_id in to_delete:
        operations.append(TupleOperation(
            action='delete', user=user,
            relation=relation, object=f'{obj_type}:{resource_id}',
        ))
        uid = user.split(':')[1]
        affected_user_ids.add(int(uid))

    for user, relation, obj_type, resource_id in to_write:
        operations.append(TupleOperation(
            action='write', user=user,
            relation=relation, object=f'{obj_type}:{resource_id}',
        ))
        uid = user.split(':')[1]
        affected_user_ids.add(int(uid))

    if operations:
        logger.info(f'Executing {len(operations)} FGA operations ...')
        await PermissionService.batch_write_tuples(operations, crash_safe=True)
        stats.written = stats.to_write
        stats.deleted = stats.to_delete

    if affected_user_ids:
        logger.info(f'Invalidating cache for {len(affected_user_ids)} users ...')
        for uid in affected_user_ids:
            await PermissionCache.invalidate_user(uid)

    return stats


async def _main(dry_run: bool) -> None:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import close_app_context, initialize_app_context

    await initialize_app_context(config=settings)

    try:
        t0 = time.time()
        stats = await reconcile(dry_run=dry_run)
        elapsed = time.time() - t0

        logger.info(
            f"Reconcile {'DRY-RUN' if dry_run else 'DONE'} in {elapsed:.1f}s — "
            f'desired={stats.desired} actual={stats.actual} write={stats.to_write} '
            f'delete={stats.to_delete} protected={stats.protected}'
        )
    finally:
        await close_app_context()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reconcile role_access ↔ FGA tuples')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no writes')
    args = parser.parse_args()
    asyncio.run(_main(dry_run=args.dry_run))
