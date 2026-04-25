"""PermissionService — core ReBAC permission engine (T07b).

Permission check chain (AC-02 / F013 spec §6):
  L1: Super admin shortcircuit (等效 owner，无 FGA 元组)
  L2: Redis cache (10s TTL, UNCACHEABLE_RELATIONS bypass)
  L3: F013 — Tenant IN-list visibility gate (resolve resource tenant_id;
      reject when not in user's visible set unless tenant#shared_to#member)
  L4: F013 — Child Tenant admin shortcut (skip Root: no tenant#admin tuples
      by design, INV-T3)
  L5: OpenFGA check (was L3)
  L6: DB creator = self → owner fallback (was L4)
  L6b: 部门管理员隐式「可管理」（管辖子树内成员创建的应用/知识库）
  L7: Fail-closed on FGA connection error (AD-03)

All methods are @classmethod — no instance state.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional, Set

from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError
from bisheng.permission.domain.schemas.permission_schema import (
    UNCACHEABLE_RELATIONS,
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
    PermissionLevel,
    ResourcePermissionItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)


class PermissionService:
    """Stateless service for ReBAC permission operations."""

    #: 隐式「部门管理范围」仅适用于应用/助手/知识库（与创建者主属部门树相关）
    _IMPLICIT_SCOPE_RESOURCE_TYPES = frozenset({
        'workflow', 'assistant', 'knowledge_space', 'knowledge_library',
    })
    _TENANT_GATED_RESOURCE_TYPES = frozenset({
        'workflow', 'assistant', 'knowledge_space', 'knowledge_library',
    })

    # ── Public API ──────────────────────────────────────────────

    @classmethod
    async def check(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> bool:
        """Five-level permission check.

        Returns True if user has the given relation on the resource.
        """
        # L1: Super admin shortcircuit
        if login_user and login_user.is_admin():
            return True

        # L3 / L4 — F013 tenant gating (only when login_user is supplied; legacy
        # call sites that pass None preserve their previous behavior).
        denied_by_tenant_gate, shortcut_level = await cls._evaluate_tenant_gate(
            user_id=user_id,
            object_type=object_type,
            object_id=object_id,
            login_user=login_user,
        )
        if denied_by_tenant_gate:
            return False
        if shortcut_level is not None:
            return cls._permission_level_satisfies_relation(
                shortcut_level, relation, object_type,
            )

        # L2: Cache lookup (skip for UNCACHEABLE_RELATIONS). This happens after
        # tenant gating so visibility / tenant-admin changes cannot be bypassed
        # by a stale cached allow.
        if relation not in UNCACHEABLE_RELATIONS:
            from bisheng.permission.domain.services.permission_cache import PermissionCache
            cached = await PermissionCache.get_check(user_id, relation, object_type, object_id)
            if cached is not None:
                return cached

        # L5: OpenFGA check
        try:
            fga = await cls._aget_fga()
            if fga is None:
                logger.warning('FGAClient not available, falling back to owner / implicit dept-admin')
                implicit_level = await cls._get_implicit_permission_level_after_gate(
                    user_id, object_type, object_id,
                )
                return cls._permission_level_satisfies_relation(
                    implicit_level, relation, object_type,
                )

            allowed = await fga.check(
                user=f'user:{user_id}',
                relation=relation,
                object=f'{object_type}:{object_id}',
            )

            if not allowed:
                for legacy_type in await cls._legacy_alias_object_types(object_type, object_id):
                    allowed = await fga.check(
                        user=f'user:{user_id}',
                        relation=relation,
                        object=f'{legacy_type}:{object_id}',
                    )
                    if allowed:
                        break

            # L4: Owner fallback — if FGA says no, check DB creator field
            if not allowed:
                implicit_level = await cls._get_implicit_permission_level_after_gate(
                    user_id, object_type, object_id,
                )
                allowed = cls._permission_level_satisfies_relation(
                    implicit_level, relation, object_type,
                )

            # Write to cache
            if relation not in UNCACHEABLE_RELATIONS:
                from bisheng.permission.domain.services.permission_cache import PermissionCache
                await PermissionCache.set_check(user_id, relation, object_type, object_id, allowed)

            return allowed

        except FGAConnectionError as e:
            # L5: Fail-closed (AD-03)
            logger.error('OpenFGA unreachable during check, denying access: %s', e)
            return False
        except Exception as e:
            logger.error('Unexpected error during permission check: %s', e)
            return False

    @classmethod
    async def list_accessible_ids(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        login_user=None,
    ) -> Optional[List[str]]:
        """List resource IDs the user can access.

        Returns None for admin (caller should not filter).
        Returns list of ID strings for normal users.
        """
        # Admin shortcircuit
        if login_user and login_user.is_admin():
            return None

        # Cache lookup (skip for UNCACHEABLE_RELATIONS)
        from bisheng.permission.domain.services.permission_cache import PermissionCache
        if relation not in UNCACHEABLE_RELATIONS:
            cached = await PermissionCache.get_list_objects(user_id, relation, object_type)
            if cached is not None:
                return await cls._finalize_accessible_ids(
                    cached, user_id, object_type, login_user=login_user,
                )

        try:
            fga = await cls._aget_fga()
            if fga is None:
                logger.warning('FGAClient not available for list_objects, using fallback scopes only')
                ids = await cls._finalize_accessible_ids(
                    [], user_id, object_type, login_user=login_user,
                )
                if relation not in UNCACHEABLE_RELATIONS:
                    await PermissionCache.set_list_objects(user_id, relation, object_type, ids)
                return ids

            # OpenFGA returns ["workflow:abc", "workflow:def"]
            raw_objects = await fga.list_objects(
                user=f'user:{user_id}',
                relation=relation,
                type=object_type,
            )

            # Extract IDs: "workflow:abc" → "abc"
            ids = []
            for obj in raw_objects:
                parts = obj.split(':', 1)
                if len(parts) == 2:
                    ids.append(parts[1])

            for legacy_type in await cls._legacy_alias_object_types(object_type):
                legacy_objects = await fga.list_objects(
                    user=f'user:{user_id}',
                    relation=relation,
                    type=legacy_type,
                )
                legacy_ids = []
                for obj in legacy_objects:
                    parts = obj.split(':', 1)
                    if len(parts) == 2:
                        legacy_ids.append(parts[1])
                ids.extend(await cls._filter_legacy_alias_ids(object_type, legacy_ids))

            ids = await cls._finalize_accessible_ids(
                ids, user_id, object_type, login_user=login_user,
            )

            # Cache result (skip for UNCACHEABLE_RELATIONS)
            if relation not in UNCACHEABLE_RELATIONS:
                await PermissionCache.set_list_objects(user_id, relation, object_type, ids)

            return ids

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during list_objects: %s', e)
            ids = await cls._finalize_accessible_ids(
                [], user_id, object_type, login_user=login_user,
            )
            return ids
        except Exception as e:
            logger.error('Unexpected error during list_accessible_ids: %s', e)
            return []

    @classmethod
    async def authorize(
        cls,
        object_type: str,
        object_id: str,
        grants: List[AuthorizeGrantItem] = None,
        revokes: List[AuthorizeRevokeItem] = None,
        enforce_fga_success: bool = False,
    ) -> None:
        """Grant or revoke permissions on a resource.

        Expands department subjects to include sub-departments when include_children=True.
        Delegates to batch_write_tuples() for FGA writes + FailedTuple compensation.
        """
        operations: List[TupleOperation] = []
        affected_user_ids: set[int] = set()
        fga_objects = [f'{object_type}:{object_id}']
        for legacy_type in await cls._legacy_alias_object_types(object_type, object_id):
            fga_objects.append(f'{legacy_type}:{object_id}')

        for grant in (grants or []):
            fga_users = await cls._expand_subject(
                grant.subject_type, grant.subject_id, grant.include_children,
            )
            for fga_user in fga_users:
                for fga_object in fga_objects:
                    operations.append(TupleOperation(
                        action='write', user=fga_user, relation=grant.relation, object=fga_object,
                    ))
            affected_user_ids.update(await cls._affected_user_ids_for_subject(
                grant.subject_type, grant.subject_id, grant.include_children,
            ))

        for revoke in (revokes or []):
            fga_users = await cls._expand_subject(
                revoke.subject_type, revoke.subject_id, revoke.include_children,
            )
            for fga_user in fga_users:
                for fga_object in fga_objects:
                    operations.append(TupleOperation(
                        action='delete', user=fga_user, relation=revoke.relation, object=fga_object,
                    ))
            affected_user_ids.update(await cls._affected_user_ids_for_subject(
                revoke.subject_type, revoke.subject_id, revoke.include_children,
            ))

        if not operations:
            return

        await cls.batch_write_tuples(
            operations,
            raise_on_failure=enforce_fga_success,
            stop_on_failure=enforce_fga_success,
        )

        # Invalidate cache for directly affected users
        if affected_user_ids:
            from bisheng.permission.domain.services.permission_cache import PermissionCache
            for uid in affected_user_ids:
                await PermissionCache.invalidate_user(uid)

    # OpenFGA Write API limit per request
    _FGA_BATCH_SIZE = 100

    @classmethod
    async def batch_write_tuples(
        cls,
        operations: List[TupleOperation],
        crash_safe: bool = False,
        raise_on_failure: bool = False,
        stop_on_failure: bool = False,
    ) -> None:
        """Batch write/delete tuples to OpenFGA.

        Chunks into batches of _FGA_BATCH_SIZE to respect OpenFGA's per-request limit.
        Used by ChangeHandler.execute_async(). Failures recorded in FailedTuple.

        Args:
            operations: List of tuple operations to execute.
            crash_safe: If True, pre-insert FailedTuple records before the FGA call
                so a process crash between MySQL commit and FGA write leaves
                recoverable records. On FGA success, the pre-inserted records are
                deleted. Used by ChangeHandler callsites where the DB transaction
                has already committed.
        """
        if not operations:
            return
        operations = cls._dedupe_operations(operations)

        # Pre-record for crash safety — delete on success
        pre_recorded_ids: List[int] = []
        saved_failure_ops = False
        if crash_safe:
            pre_recorded_ids = await cls._pre_record_failed_tuples(operations)

        try:
            fga = await cls._aget_fga()
            if fga is None:
                if not crash_safe:
                    await cls._save_failed_tuples(operations, 'FGAClient not available')
                if raise_on_failure:
                    raise FGAConnectionError('FGAClient not available')
                return

            # Chunk the original operation list so writes+deletes together stay
            # within the per-request limit. If a batch trips on duplicate
            # writes / missing deletes, fall back to single-tuple writes and
            # treat those idempotent cases as success.
            batch = cls._FGA_BATCH_SIZE
            failed_ops: List[TupleOperation] = []
            for idx in range(0, len(operations), batch):
                chunk = operations[idx:idx + batch]
                writes = [
                    {'user': op.user, 'relation': op.relation, 'object': op.object}
                    for op in chunk if op.action == 'write'
                ]
                deletes = [
                    {'user': op.user, 'relation': op.relation, 'object': op.object}
                    for op in chunk if op.action == 'delete'
                ]
                try:
                    await fga.write_tuples(
                        writes=writes or None,
                        deletes=deletes or None,
                    )
                except FGAWriteError as e:
                    logger.info(
                        'Batch tuple write fell back to single writes for %d ops: %s',
                        len(chunk), e,
                    )
                    failed_ops.extend(
                        await cls._write_operations_individually(
                            fga,
                            chunk,
                            stop_on_failure=stop_on_failure,
                        ),
                    )

            if failed_ops:
                logger.error(
                    'OpenFGA tuple write left %d unresolved operations (raise_on_failure=%s, crash_safe=%s)',
                    len(failed_ops), raise_on_failure, crash_safe,
                )
                if not crash_safe:
                    await cls._save_failed_tuples(
                        failed_ops,
                        'OpenFGA single-tuple fallback failed',
                    )
                    saved_failure_ops = True
                if raise_on_failure:
                    raise FGAWriteError(
                        f'OpenFGA write did not complete successfully; {len(failed_ops)} tuple operations failed',
                    )
                return

            # FGA succeeded — clean up pre-recorded FailedTuples
            if pre_recorded_ids:
                await cls._delete_pre_recorded(pre_recorded_ids)

        except Exception as e:
            logger.error('Failed to batch write tuples: %s', e)
            if not crash_safe and not saved_failure_ops:
                await cls._save_failed_tuples(operations, str(e))
            # If crash_safe, pre-recorded entries remain as 'pending' for retry
            if raise_on_failure:
                raise

    @classmethod
    async def _write_operations_individually(
        cls,
        fga,
        operations: List[TupleOperation],
        stop_on_failure: bool = False,
    ) -> List[TupleOperation]:
        """Replay a failed batch one tuple at a time.

        OpenFGA rejects duplicate writes and deletes of already-missing tuples
        as invalid input. Those cases are semantically idempotent for our
        callers, so we treat them as success and only return truly failed ops.
        """
        failed: List[TupleOperation] = []
        for index, op in enumerate(operations):
            payload = {
                'user': op.user,
                'relation': op.relation,
                'object': op.object,
            }
            try:
                if op.action == 'write':
                    await fga.write_tuples(writes=[payload])
                else:
                    await fga.write_tuples(deletes=[payload])
            except FGAWriteError as e:
                if cls._is_idempotent_tuple_error(op.action, str(e)):
                    logger.info(
                        'Ignoring idempotent OpenFGA %s failure for %s %s %s: %s',
                        op.action, op.user, op.relation, op.object, e,
                    )
                    continue
                failed.append(op)
                if stop_on_failure:
                    remaining = operations[index + 1:]
                    if remaining:
                        logger.warning(
                            'Stopping tuple fallback after non-idempotent %s failure; skipping %d trailing operations',
                            op.action, len(remaining),
                        )
                        failed.extend(remaining)
                    break
            except FGAConnectionError:
                raise
            except Exception:
                failed.append(op)
                if stop_on_failure:
                    remaining = operations[index + 1:]
                    if remaining:
                        logger.warning(
                            'Stopping tuple fallback after unexpected %s failure; skipping %d trailing operations',
                            op.action, len(remaining),
                        )
                        failed.extend(remaining)
                    break
        return failed

    @staticmethod
    def _is_idempotent_tuple_error(action: str, error_msg: str) -> bool:
        text = error_msg.lower()
        if action == 'write':
            return (
                'already exists' in text
                or 'cannot write a tuple which already exists' in text
            )
        if action == 'delete':
            return (
                'did not exist' in text
                or 'tuple to be deleted did not exist' in text
            )
        return False

    @staticmethod
    def _dedupe_operations(
        operations: List[TupleOperation],
    ) -> List[TupleOperation]:
        seen: set[tuple[str, str, str, str]] = set()
        deduped: List[TupleOperation] = []
        for op in operations:
            key = (op.action, op.user, op.relation, op.object)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(op)
        return deduped

    # Regex to parse FGA subject: "user:7", "department:5#member", "user_group:3#member"
    _SUBJECT_RE = re.compile(r'^(user|department|user_group):(\d+)(#member)?$')

    @classmethod
    async def get_resource_permissions(
        cls,
        object_type: str,
        object_id: str,
    ) -> List[ResourcePermissionItem]:
        """List enriched permission entries for a resource.

        Reads raw FGA tuples, parses subjects, resolves names via DB,
        and returns structured ResourcePermissionItem list.
        """
        try:
            fga = await cls._aget_fga()
            if fga is None:
                return []

            tuples = await fga.read_tuples(object=f'{object_type}:{object_id}')
            for legacy_type in await cls._legacy_alias_object_types(object_type, object_id):
                tuples.extend(await fga.read_tuples(object=f'{legacy_type}:{object_id}'))
            if not tuples:
                return []

            deduped = list({
                (t.get('user', ''), t.get('relation', '')): t
                for t in tuples
            }.values())
            return await cls._enrich_permission_tuples(deduped)

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during read_tuples: %s', e)
            return []
        except Exception as e:
            logger.error('Error reading resource permissions: %s', e)
            return []

    @classmethod
    async def _enrich_permission_tuples(
        cls,
        tuples: List[dict],
    ) -> List[ResourcePermissionItem]:
        """Parse FGA tuples, resolve subject names, merge department entries."""
        # Step 1: Parse and filter tuples
        parsed = []
        for t in tuples:
            m = cls._SUBJECT_RE.match(t.get('user', ''))
            if not m:
                continue
            subject_type, subject_id_str, member_suffix = m.groups()
            # OpenFGA 中部门/用户组对资源的授权 subject 写作 department:id#member、user_group:id#member；
            # 仅 user 不应带 #member，若出现则跳过。
            if member_suffix:
                if subject_type == 'user':
                    continue
            parsed.append({
                'subject_type': subject_type,
                'subject_id': int(subject_id_str),
                'relation': t.get('relation', ''),
            })

        if not parsed:
            return []

        # Step 2: Collect IDs by subject_type
        user_ids = [p['subject_id'] for p in parsed if p['subject_type'] == 'user']
        dept_ids = [p['subject_id'] for p in parsed if p['subject_type'] == 'department']
        group_ids = [p['subject_id'] for p in parsed if p['subject_type'] == 'user_group']

        # Step 3: Batch resolve names and user-group captions for the user/group list UI
        name_map, user_group_names_map, user_group_member_names_map = await asyncio.gather(
            cls._resolve_subject_names(user_ids, dept_ids, group_ids),
            cls._resolve_user_group_names(user_ids),
            cls._resolve_user_group_member_names(group_ids),
        )

        # Step 4: Build items and merge department entries
        dept_tracker: dict[tuple, ResourcePermissionItem] = {}
        items: List[ResourcePermissionItem] = []

        for p in parsed:
            key = (p['subject_type'], p['subject_id'])
            name = name_map.get(key)

            if p['subject_type'] == 'department':
                dept_key = (p['subject_id'], p['relation'])
                if dept_key in dept_tracker:
                    # Multiple tuples for same dept+relation → include_children=True
                    dept_tracker[dept_key].include_children = True
                else:
                    item = ResourcePermissionItem(
                        subject_type=p['subject_type'],
                        subject_id=p['subject_id'],
                        subject_name=name,
                        relation=p['relation'],
                        include_children=False,
                    )
                    dept_tracker[dept_key] = item
                    items.append(item)
            else:
                items.append(ResourcePermissionItem(
                    subject_type=p['subject_type'],
                    subject_id=p['subject_id'],
                    subject_name=name,
                    subject_member_names=user_group_member_names_map.get(p['subject_id'])
                    if p['subject_type'] == 'user_group' else None,
                    subject_group_names=user_group_names_map.get(p['subject_id']) if p['subject_type'] == 'user' else None,
                    relation=p['relation'],
                ))

        return items

    @classmethod
    async def _resolve_user_group_names(
        cls,
        user_ids: List[int],
    ) -> dict[int, List[str]]:
        """Batch-resolve user group names for user subjects in permission lists."""
        if not user_ids:
            return {}

        try:
            from bisheng.database.models.user_group import UserGroupDao

            groups_map = await UserGroupDao.aget_user_groups_batch(list(set(user_ids)))
        except Exception as e:
            logger.warning('Failed to resolve user group names: %s', e)
            return {}

        resolved: dict[int, List[str]] = {}
        for user_id, groups in groups_map.items():
            names: List[str] = []
            for group in groups or []:
                group_name = getattr(group, 'group_name', None)
                if group_name and group_name not in names:
                    names.append(group_name)
            if names:
                resolved[int(user_id)] = names

        return resolved

    @classmethod
    async def _resolve_user_group_member_names(
        cls,
        group_ids: List[int],
    ) -> dict[int, List[str]]:
        """Batch-resolve visible member names for user-group subjects."""
        if not group_ids:
            return {}

        try:
            from bisheng.database.models.user_group import UserGroupDao
            from bisheng.user.domain.models.user import UserDao

            rows = await UserGroupDao.aget_group_users(list(set(group_ids)))
            if not rows:
                return {}

            member_group_pairs: list[tuple[int, int]] = []
            user_ids = set()
            for row in rows:
                group_id = int(getattr(row, 'group_id', 0) or 0)
                user_id = int(getattr(row, 'user_id', 0) or 0)
                if not group_id or not user_id:
                    continue
                member_group_pairs.append((group_id, user_id))
                user_ids.add(user_id)

            if not member_group_pairs:
                return {}

            users = await UserDao.aget_user_by_ids(sorted(user_ids))
            user_name_map = {
                int(user.user_id): user.user_name
                for user in users or []
                if getattr(user, 'delete', 0) == 0 and getattr(user, 'user_name', None)
            }

            resolved: dict[int, List[str]] = {}
            for group_id, user_id in member_group_pairs:
                user_name = user_name_map.get(user_id)
                if not user_name:
                    continue
                names = resolved.setdefault(group_id, [])
                if user_name not in names:
                    names.append(user_name)
            return resolved
        except Exception as e:
            logger.warning('Failed to resolve user-group member names: %s', e)
            return {}

    @classmethod
    async def _resolve_subject_names(
        cls,
        user_ids: List[int],
        dept_ids: List[int],
        group_ids: List[int],
    ) -> dict[tuple, Optional[str]]:
        """Batch-resolve subject names from DB. Returns {(type, id): name}.

        Runs all DAO queries concurrently via asyncio.gather.
        """
        async def _fetch_users():
            if not user_ids:
                return []
            from bisheng.user.domain.models.user import UserDao
            return await UserDao.aget_user_by_ids(user_ids) or []

        async def _fetch_depts():
            if not dept_ids:
                return []
            from bisheng.database.models.department import DepartmentDao
            return await DepartmentDao.aget_by_ids(dept_ids) or []

        async def _fetch_groups():
            if not group_ids:
                return []
            from bisheng.database.models.group import GroupDao
            return await GroupDao.aget_group_by_ids(group_ids) or []

        results = await asyncio.gather(
            _fetch_users(), _fetch_depts(), _fetch_groups(),
            return_exceptions=True,
        )

        name_map: dict[tuple, Optional[str]] = {}
        extractors = [
            (results[0], 'user', lambda u: (u.user_id, u.user_name)),
            (results[1], 'department', lambda d: (d.id, d.name)),
            (results[2], 'user_group', lambda g: (g.id, g.group_name)),
        ]
        for result, subject_type, extractor in extractors:
            if isinstance(result, Exception):
                logger.warning('Failed to resolve %s names: %s', subject_type, result)
                continue
            for item in result:
                id_val, name_val = extractor(item)
                name_map[(subject_type, id_val)] = name_val

        return name_map

    @classmethod
    async def get_permission_level(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> Optional[str]:
        """Get user's highest permission level on a resource (AD-04).

        Uses batch_check for efficiency. Returns PermissionLevel value or None.
        """
        if login_user and login_user.is_admin():
            return PermissionLevel.owner.value

        denied_by_tenant_gate, shortcut_level = await cls._evaluate_tenant_gate(
            user_id=user_id,
            object_type=object_type,
            object_id=object_id,
            login_user=login_user,
        )
        if denied_by_tenant_gate:
            return None
        if shortcut_level is not None:
            return shortcut_level

        try:
            fga = await cls._aget_fga()
            if fga is None:
                return await cls._get_implicit_permission_level_after_gate(
                    user_id, object_type, object_id,
                )

            # Batch check all 4 levels
            checks = [
                {'user': f'user:{user_id}', 'relation': level.value, 'object': f'{object_type}:{object_id}'}
                for level in PermissionLevel
            ]
            results = await fga.batch_check(checks)

            # Return highest level that is True
            for level, allowed in zip(PermissionLevel, results):
                if allowed:
                    return level.value

            for legacy_type in await cls._legacy_alias_object_types(object_type, object_id):
                legacy_checks = [
                    {'user': f'user:{user_id}', 'relation': level.value, 'object': f'{legacy_type}:{object_id}'}
                    for level in PermissionLevel
                ]
                legacy_results = await fga.batch_check(legacy_checks)
                for level, allowed in zip(PermissionLevel, legacy_results):
                    if allowed:
                        return level.value

            return await cls._get_implicit_permission_level_after_gate(
                user_id, object_type, object_id,
            )

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during get_permission_level: %s', e)
            return None
        except Exception as e:
            logger.error('Error getting permission level: %s', e)
            return None

    # ── Internal helpers ────────────────────────────────────────

    @classmethod
    async def get_implicit_permission_level(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> Optional[str]:
        """Resolve non-tuple permission sources only.

        This intentionally excludes direct OpenFGA grants so fine-grained
        permission services can layer custom bound models on top of implicit
        access such as owner fallback, tenant-admin shortcut, and implicit
        department-admin scope without over-granting explicit custom models.
        """
        is_admin = getattr(login_user, 'is_admin', None)
        if callable(is_admin) and is_admin():
            return PermissionLevel.owner.value

        denied_by_tenant_gate, shortcut_level = await cls._evaluate_tenant_gate(
            user_id=user_id,
            object_type=object_type,
            object_id=object_id,
            login_user=login_user,
        )
        if denied_by_tenant_gate:
            return None
        if shortcut_level is not None:
            return shortcut_level

        return await cls._get_implicit_permission_level_after_gate(
            user_id, object_type, object_id,
        )

    @classmethod
    async def _evaluate_tenant_gate(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
        login_user=None,
    ) -> tuple[bool, Optional[str]]:
        """Return ``(denied, shortcut_level)`` for tenant visibility/admin rules."""
        visible_tenants = getattr(login_user, 'get_visible_tenants', None)
        if login_user is None or not callable(visible_tenants):
            return False, None

        resource_tenant_id = await cls._resolve_resource_tenant(object_type, object_id)
        if resource_tenant_id is None:
            return False, None

        visible = await visible_tenants()
        if resource_tenant_id not in visible:
            if not await cls._is_shared_to(
                user_id, resource_tenant_id, visible_tenant_ids=visible,
            ):
                return True, None

        from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
        if resource_tenant_id != ROOT_TENANT_ID:
            tenant = await TenantDao.aget_by_id(resource_tenant_id)
            if tenant is not None and tenant.parent_tenant_id is not None:
                has_tenant_admin = getattr(login_user, 'has_tenant_admin', None)
                if callable(has_tenant_admin) and await has_tenant_admin(resource_tenant_id):
                    # check() historically short-circuits tenant admins for any
                    # relation. Expose the same effective level here so list /
                    # level callers stay aligned with check().
                    return False, PermissionLevel.owner.value

        return False, None

    @classmethod
    async def _get_implicit_permission_level_after_gate(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> Optional[str]:
        try:
            creator_id = await cls._get_resource_creator(object_type, object_id)
            if creator_id is not None and creator_id == user_id:
                return PermissionLevel.owner.value
            if creator_id is not None and await cls._implicit_dept_admin_covers(user_id, creator_id):
                return PermissionLevel.can_manage.value
            department_space_level = await cls._implicit_department_space_member_level(
                user_id,
                object_type,
                object_id,
            )
            if department_space_level is not None:
                return department_space_level
            return None
        except Exception as e:
            logger.debug(
                'Could not resolve implicit permission level for %s:%s: %s',
                object_type, object_id, e,
            )
            return None

    @classmethod
    def _permission_level_satisfies_relation(
        cls,
        level: Optional[str],
        relation: str,
        object_type: str,
    ) -> bool:
        if level == PermissionLevel.owner.value:
            return True
        if level == PermissionLevel.can_manage.value:
            return cls._relation_implicit_manager_ok(relation, object_type)
        if level == PermissionLevel.can_edit.value:
            return relation in ('can_edit', 'can_read', 'editor', 'viewer')
        if level == PermissionLevel.can_read.value:
            return relation in ('can_read', 'viewer')
        return False

    @classmethod
    def _relation_implicit_manager_ok(cls, relation: str, object_type: str) -> bool:
        """隐式部门管理档位可满足的 relation（不写 FGA；所有者/删除仍走显式规则）。"""
        if object_type not in cls._IMPLICIT_SCOPE_RESOURCE_TYPES:
            return False
        if relation in ('owner', 'can_delete'):
            return False
        if relation in ('can_manage', 'can_edit', 'can_read', 'manager', 'editor', 'viewer'):
            return True
        return False

    @classmethod
    async def _implicit_dept_admin_covers(cls, viewer_user_id: int, creator_user_id: int) -> bool:
        """当前用户作为部门管理员时，其管辖部门子树是否覆盖创建者的任职部门之一。"""
        if viewer_user_id == creator_user_id:
            return False
        from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

        admin_depts = await DepartmentDao.aget_user_admin_departments(viewer_user_id)
        if not admin_depts:
            return False
        subtree: Set[int] = set()
        for ad in admin_depts:
            if ad and getattr(ad, 'path', None):
                subtree |= set(await DepartmentDao.aget_subtree_ids(ad.path))
        if not subtree:
            return False
        uds = await UserDepartmentDao.aget_user_departments(creator_user_id)
        if not uds:
            return False
        for ud in uds:
            if int(ud.department_id) in subtree:
                return True
        return False

    @classmethod
    async def _implicit_department_space_member_level(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> Optional[str]:
        if object_type != 'knowledge_space' or not str(object_id).isdigit():
            return None

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.department import UserDepartmentDao
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao

        with bypass_tenant_filter():
            binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(object_id))
            if binding is None:
                return None
            user_departments = await UserDepartmentDao.aget_user_departments(user_id)
        if any(int(row.department_id) == int(binding.department_id) for row in user_departments):
            return PermissionLevel.can_read.value
        return None

    @classmethod
    async def _distinct_user_ids_in_departments(cls, department_ids: Set[int]) -> Set[int]:
        if not department_ids:
            return set()
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.department import UserDepartment
        from sqlmodel import col, select

        async with get_async_db_session() as session:
            stmt = select(UserDepartment.user_id).where(
                col(UserDepartment.department_id).in_(list(department_ids)),
            )
            result = await session.exec(stmt)
            rows = result.all()
        out: Set[int] = set()
        for row in rows:
            uid = row[0] if isinstance(row, tuple) else row
            out.add(int(uid))
        return out

    @classmethod
    async def _resource_ids_by_creator_user_ids(
        cls, object_type: str, creator_uids: Set[int],
    ) -> List[str]:
        if not creator_uids:
            return []
        from bisheng.core.context.tenant import bypass_tenant_filter
        uids = list(creator_uids)
        from bisheng.core.database import get_async_db_session
        from sqlmodel import col, select

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                if object_type == 'knowledge_space':
                    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum

                    stmt = select(Knowledge.id).where(
                        col(Knowledge.user_id).in_(uids),
                        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                    )
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'knowledge_library':
                    from bisheng.knowledge.domain.models.knowledge import Knowledge
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

                    stmt = select(Knowledge.id).where(
                        col(Knowledge.user_id).in_(uids),
                        Knowledge.type.in_([
                            KnowledgeTypeEnum.NORMAL.value,
                            KnowledgeTypeEnum.QA.value,
                        ]),
                    )
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'workflow':
                    from bisheng.database.models.flow import Flow

                    stmt = select(Flow.id).where(col(Flow.user_id).in_(uids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'assistant':
                    from bisheng.database.models.assistant import Assistant

                    stmt = select(Assistant.id).where(col(Assistant.user_id).in_(uids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'knowledge_file':
                    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

                    stmt = select(KnowledgeFile.id).where(col(KnowledgeFile.user_id).in_(uids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'tool':
                    from bisheng.tool.domain.models.gpts_tools import GptsToolsType

                    stmt = select(GptsToolsType.id).where(col(GptsToolsType.user_id).in_(uids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'channel':
                    from bisheng.channel.domain.models.channel import Channel

                    stmt = select(Channel.id).where(col(Channel.user_id).in_(uids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
        return []

    @classmethod
    async def _resource_ids_in_tenants(
        cls,
        object_type: str,
        tenant_ids: Set[int],
    ) -> List[str]:
        if not tenant_ids:
            return []
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session
        from sqlmodel import col, select

        tids = list(tenant_ids)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                if object_type == 'workflow':
                    from bisheng.database.models.flow import Flow

                    stmt = select(Flow.id).where(col(Flow.tenant_id).in_(tids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type == 'assistant':
                    from bisheng.database.models.assistant import Assistant

                    stmt = select(Assistant.id).where(col(Assistant.tenant_id).in_(tids))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
                if object_type in {'knowledge_space', 'knowledge_library'}:
                    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum

                    stmt = select(Knowledge.id).where(col(Knowledge.tenant_id).in_(tids))
                    if object_type == 'knowledge_space':
                        stmt = stmt.where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
                    else:
                        stmt = stmt.where(Knowledge.type.in_([
                            KnowledgeTypeEnum.NORMAL.value,
                            KnowledgeTypeEnum.QA.value,
                        ]))
                    result = await session.exec(stmt)
                    rows = result.all()
                    return [str(row[0] if isinstance(row, tuple) else row) for row in rows]
        return []

    @classmethod
    async def _resource_tenant_map(
        cls,
        object_type: str,
        object_ids: List[str],
    ) -> dict[str, int]:
        if not object_ids or object_type not in cls._TENANT_GATED_RESOURCE_TYPES:
            return {}

        from bisheng.core.context.tenant import bypass_tenant_filter

        mapping: dict[str, int] = {}
        with bypass_tenant_filter():
            if object_type == 'workflow':
                from bisheng.database.models.flow import FlowDao

                rows = await FlowDao.aget_flow_by_ids(object_ids)
                for row in rows or []:
                    mapping[str(row.id)] = int(row.tenant_id)
                return mapping
            if object_type == 'assistant':
                from bisheng.database.models.assistant import AssistantDao

                rows = await AssistantDao.aget_assistants_by_ids(object_ids)
                for row in rows or []:
                    mapping[str(row.id)] = int(row.tenant_id)
                return mapping
            if object_type in {'knowledge_space', 'knowledge_library'}:
                from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

                numeric_ids = [int(one) for one in object_ids if str(one).isdigit()]
                if not numeric_ids:
                    return {}
                rows = await KnowledgeDao.aget_list_by_ids(numeric_ids)
                for row in rows or []:
                    if object_type == 'knowledge_space' and row.type != KnowledgeTypeEnum.SPACE.value:
                        continue
                    if object_type == 'knowledge_library' and row.type not in (
                        KnowledgeTypeEnum.NORMAL.value,
                        KnowledgeTypeEnum.QA.value,
                    ):
                        continue
                    mapping[str(row.id)] = int(row.tenant_id)
                return mapping
        return {}

    @classmethod
    async def _resource_ids_child_tenant_admin_scope(
        cls,
        login_user,
        object_type: str,
    ) -> List[str]:
        get_visible_tenants = getattr(login_user, 'get_visible_tenants', None)
        has_tenant_admin = getattr(login_user, 'has_tenant_admin', None)
        if (
            login_user is None
            or object_type not in cls._TENANT_GATED_RESOURCE_TYPES
            or not callable(get_visible_tenants)
            or not callable(has_tenant_admin)
        ):
            return []

        from bisheng.database.models.tenant import ROOT_TENANT_ID

        visible = await get_visible_tenants()
        candidate_tenant_ids = [
            int(tid) for tid in visible
            if int(tid) != ROOT_TENANT_ID
        ]
        if not candidate_tenant_ids:
            return []

        admin_checks = await asyncio.gather(*[
            has_tenant_admin(tid) for tid in candidate_tenant_ids
        ])
        admin_tenant_ids = {
            tid for tid, allowed in zip(candidate_tenant_ids, admin_checks) if allowed
        }
        return await cls._resource_ids_in_tenants(object_type, admin_tenant_ids)

    @classmethod
    async def _filter_ids_by_tenant_gate(
        cls,
        user_id: int,
        object_type: str,
        object_ids: List[str],
        login_user,
    ) -> List[str]:
        if login_user is None or object_type not in cls._TENANT_GATED_RESOURCE_TYPES or not object_ids:
            return object_ids

        tenant_map = await cls._resource_tenant_map(object_type, object_ids)
        if not tenant_map:
            return object_ids

        visible = set(await login_user.get_visible_tenants())
        shared_tenant_ids = sorted({
            tenant_id for tenant_id in tenant_map.values()
            if tenant_id not in visible
        })
        shared_checks = await asyncio.gather(*[
            cls._is_shared_to(user_id, tenant_id, visible_tenant_ids=visible)
            for tenant_id in shared_tenant_ids
        ])
        shared_by_tenant = {
            tenant_id: allowed
            for tenant_id, allowed in zip(shared_tenant_ids, shared_checks)
        }
        return [
            object_id for object_id in object_ids
            if (
                tenant_map.get(object_id) is None
                or tenant_map[object_id] in visible
                or shared_by_tenant.get(tenant_map[object_id], False)
            )
        ]

    @classmethod
    async def _finalize_accessible_ids(
        cls,
        ids: List[str],
        user_id: int,
        object_type: str,
        login_user=None,
    ) -> List[str]:
        ordered_ids = list(dict.fromkeys(str(one) for one in (ids or [])))

        creator_owned_ids = await cls._resource_ids_by_creator_user_ids(
            object_type, {user_id},
        )
        if creator_owned_ids:
            ordered_ids = list(dict.fromkeys([
                *ordered_ids,
                *(str(one) for one in creator_owned_ids),
            ]))

        implicit_ids = await cls._resource_ids_implicit_dept_admin_scope(
            user_id, object_type,
        )
        if implicit_ids:
            ordered_ids = list(dict.fromkeys([
                *ordered_ids,
                *(str(one) for one in implicit_ids),
            ]))

        tenant_admin_scope_ids = await cls._resource_ids_child_tenant_admin_scope(
            login_user, object_type,
        )
        if tenant_admin_scope_ids:
            ordered_ids = list(dict.fromkeys([
                *ordered_ids,
                *(str(one) for one in tenant_admin_scope_ids),
            ]))

        return await cls._filter_ids_by_tenant_gate(
            user_id, object_type, ordered_ids, login_user,
        )

    @classmethod
    async def _resource_ids_implicit_dept_admin_scope(
        cls, viewer_user_id: int, object_type: str,
    ) -> List[str]:
        """部门管理员在 list_objects 并集中额外可见的资源（子树成员创建）。"""
        if object_type not in cls._IMPLICIT_SCOPE_RESOURCE_TYPES:
            return []
        from bisheng.database.models.department import DepartmentDao

        admin_depts = await DepartmentDao.aget_user_admin_departments(viewer_user_id)
        logger.info(
            '[implicit-scope] viewer=%s type=%s admin_depts=%s',
            viewer_user_id, object_type,
            [(d.id, getattr(d, 'name', None), getattr(d, 'path', None)) for d in admin_depts or []],
        )
        if not admin_depts:
            return []
        subtree: Set[int] = set()
        for ad in admin_depts:
            if ad and getattr(ad, 'path', None):
                ids = await DepartmentDao.aget_subtree_ids(ad.path)
                logger.info(
                    '[implicit-scope] subtree from path=%s ids=%s',
                    ad.path, ids,
                )
                subtree |= set(ids)
        if not subtree:
            logger.info('[implicit-scope] empty subtree for viewer=%s', viewer_user_id)
            return []
        member_uids = await cls._distinct_user_ids_in_departments(subtree)
        logger.info(
            '[implicit-scope] viewer=%s subtree=%s members=%s',
            viewer_user_id, sorted(subtree), sorted(member_uids),
        )
        if not member_uids:
            return []
        ids = await cls._resource_ids_by_creator_user_ids(object_type, member_uids)
        logger.info(
            '[implicit-scope] viewer=%s type=%s resource_ids=%s',
            viewer_user_id, object_type, ids,
        )
        return ids

    @classmethod
    async def _legacy_alias_object_types(
        cls,
        object_type: str,
        object_id: str | None = None,
    ) -> List[str]:
        if object_type != 'knowledge_library':
            return []
        if object_id is None:
            return ['knowledge_space']
        try:
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

            obj = await KnowledgeDao.aquery_by_id(int(object_id))
            if obj and obj.type != KnowledgeTypeEnum.SPACE.value:
                return ['knowledge_space']
        except Exception as e:
            logger.debug('Could not resolve legacy alias object type for %s:%s: %s', object_type, object_id, e)
        return []

    @classmethod
    async def _filter_legacy_alias_ids(
        cls,
        object_type: str,
        ids: List[str],
    ) -> List[str]:
        if object_type != 'knowledge_library' or not ids:
            return ids
        try:
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

            numeric_ids = [int(one) for one in ids if str(one).isdigit()]
            if not numeric_ids:
                return []
            objects = await KnowledgeDao.aget_list_by_ids(numeric_ids)
            return [
                str(obj.id) for obj in objects
                if obj.type != KnowledgeTypeEnum.SPACE.value
            ]
        except Exception as e:
            logger.debug('Could not filter legacy alias ids for %s: %s', object_type, e)
            return []

    @classmethod
    async def _expand_subject(
        cls,
        subject_type: str,
        subject_id: int,
        include_children: bool = True,
    ) -> List[str]:
        """Expand a subject to OpenFGA user strings.

        user → ["user:{id}"]
        department + include_children → ["department:{id}#member" for each subtree dept]
        department + not include_children → ["department:{id}#member"]
        user_group → ["user_group:{id}#member"]
        """
        if subject_type == 'user':
            return [f'user:{subject_id}']

        if subject_type == 'department':
            if include_children:
                from bisheng.database.models.department import DepartmentDao
                dept = await DepartmentDao.aget_by_id(subject_id)
                if dept is None:
                    logger.warning('Department %d not found for expansion', subject_id)
                    return [f'department:{subject_id}#member']

                subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path)
                return [f'department:{did}#member' for did in subtree_ids]
            else:
                return [f'department:{subject_id}#member']

        if subject_type == 'user_group':
            return [f'user_group:{subject_id}#member']

        logger.warning('Unknown subject type: %s', subject_type)
        return []

    @classmethod
    async def _affected_user_ids_for_subject(
        cls,
        subject_type: str,
        subject_id: int,
        include_children: bool = True,
    ) -> Set[int]:
        """Expand an auth subject to concrete user ids for cache invalidation."""
        if subject_type == 'user':
            return {int(subject_id)}

        if subject_type == 'department':
            from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

            department_ids = {int(subject_id)}
            if include_children:
                dept = await DepartmentDao.aget_by_id(subject_id)
                if dept is not None and getattr(dept, 'path', None):
                    subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path)
                    department_ids = {int(one) for one in subtree_ids}

            if not department_ids:
                return set()

            membership_lists = await asyncio.gather(*[
                UserDepartmentDao.aget_user_ids_by_department(department_id)
                for department_id in sorted(department_ids)
            ])
            affected: Set[int] = set()
            for user_ids in membership_lists:
                affected.update(int(user_id) for user_id in user_ids)
            return affected

        if subject_type == 'user_group':
            from bisheng.database.models.user_group import UserGroupDao

            rows = await UserGroupDao.aget_group_users([subject_id])
            return {
                int(row.user_id)
                for row in rows
                if getattr(row, 'user_id', None) is not None
            }

        return set()

    @classmethod
    async def _get_resource_creator(
        cls,
        object_type: str,
        object_id: str,
    ) -> Optional[int]:
        """Query DB for the creator (user_id) of a resource.

        Owner fallback (AC-06): when FGA write is delayed, DB creator field
        provides a safety net for the resource owner.
        """
        try:
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                if object_type == 'workflow':
                    from bisheng.database.models.flow import FlowDao
                    flow = await FlowDao.aget_flow_by_id(object_id)
                    return flow.user_id if flow else None
                if object_type == 'assistant':
                    from bisheng.database.models.assistant import AssistantDao

                    assistant = await AssistantDao.aget_one_assistant(object_id)
                    return assistant.user_id if assistant else None

                if object_type == 'knowledge_space':
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
                    ks = await KnowledgeDao.aquery_by_id(int(object_id))
                    return ks.user_id if ks and ks.type == KnowledgeTypeEnum.SPACE.value else None

                if object_type == 'knowledge_library':
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

                    kb = await KnowledgeDao.aquery_by_id(int(object_id))
                    if kb and kb.type in (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value):
                        return kb.user_id
                    return None

                if object_type == 'knowledge_file':
                    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
                    files = await KnowledgeFileDao.aget_file_by_ids([int(object_id)])
                    return files[0].user_id if files else None

                if object_type == 'tool':
                    from bisheng.tool.domain.models.gpts_tools import GptsToolsDao

                    tool_type = await GptsToolsDao.aget_one_tool_type(int(object_id))
                    return tool_type.user_id if tool_type else None

                if object_type == 'channel':
                    from bisheng.channel.domain.models.channel import Channel
                    from bisheng.core.database import get_async_db_session
                    from sqlmodel import select

                    async with get_async_db_session() as session:
                        result = await session.exec(
                            select(Channel).where(Channel.id == object_id),
                        )
                        channel = result.first()
                    return channel.user_id if channel else None

            # For other types (dashboard, folder), no direct
            # user_id field — owner fallback not applicable, return None.
            return None

        except Exception as e:
            logger.debug('Could not query resource creator for %s:%s: %s', object_type, object_id, e)
            return None

    @classmethod
    async def _save_failed_tuples(
        cls,
        operations: List[TupleOperation],
        error_msg: str,
    ) -> None:
        """Record failed operations in the compensation queue (INV-4)."""
        if not operations:
            return
        try:
            from bisheng.database.models.failed_tuple import FailedTuple, FailedTupleDao

            tuples = [
                FailedTuple(
                    action=op.action,
                    fga_user=op.user,
                    relation=op.relation,
                    object=op.object,
                    error_message=error_msg,
                )
                for op in operations
            ]
            await FailedTupleDao.acreate_batch(tuples)
            logger.warning(
                'Recorded %d failed tuples for compensation: %s',
                len(tuples), error_msg[:200],
            )
        except Exception as e:
            logger.critical(
                'CRITICAL: Failed to record failed tuples (data loss risk): %s', e,
            )

    @classmethod
    async def _pre_record_failed_tuples(cls, operations: List[TupleOperation]) -> List[int]:
        """Pre-insert FailedTuple records as 'pending' for crash safety.

        Returns list of record IDs to delete on FGA success.
        """
        try:
            from bisheng.database.models.failed_tuple import FailedTuple, FailedTupleDao

            tuples = [
                FailedTuple(
                    action=op.action,
                    fga_user=op.user,
                    relation=op.relation,
                    object=op.object,
                    error_message='pre-recorded for crash safety',
                )
                for op in operations
            ]
            await FailedTupleDao.acreate_batch(tuples)
            return [t.id for t in tuples if t.id]
        except Exception as e:
            logger.warning('Failed to pre-record failed tuples: %s', e)
            return []

    @classmethod
    async def _delete_pre_recorded(cls, record_ids: List[int]) -> None:
        """Delete pre-recorded FailedTuples after FGA success."""
        if not record_ids:
            return
        try:
            from bisheng.database.models.failed_tuple import FailedTupleDao
            for rid in record_ids:
                await FailedTupleDao.aupdate_succeeded(rid)
        except Exception as e:
            logger.debug('Failed to clean up pre-recorded tuples: %s', e)

    @staticmethod
    def _get_fga():
        """Get FGAClient from app context. Returns None if unavailable."""
        from bisheng.core.openfga.manager import get_fga_client
        return get_fga_client()

    @classmethod
    async def _aget_fga(cls):
        """Async accessor for FGAClient.

        PermissionService methods are async and FGAManager is initialized
        asynchronously. Prefer the async accessor here so write paths do not
        falsely degrade to ``FGAClient not available`` when the sync accessor
        cannot materialize the optional context.

        Falls back to ``_get_fga()`` so existing tests that patch the sync
        helper keep working without broad rewrites.
        """
        from bisheng.core.openfga.manager import aget_fga_client

        fga = await aget_fga_client()
        if fga is not None:
            return fga
        return cls._get_fga()

    # ── F013 helpers (Tenant tree) ──────────────────────────────

    @classmethod
    async def _resolve_resource_tenant(cls, object_type: str, object_id: str):
        """Resolve a resource's owning tenant_id, or None to skip tenant gating.

        F013 only enforces tenant gating for primary resource types that carry
        an owning tenant_id we can look up cheaply (workflow, assistant,
        knowledge_space / knowledge_library). Other types (folder,
        knowledge_file, channel, tool,
        dashboard, llm_*) inherit visibility via their parent or are not yet
        wired to multi-tenant; for those, returning None falls through to the
        existing FGA chain which still honors tenant#shared_to#member at the
        DSL level. Any DAO error degrades to None for safety (legacy paths).
        """
        try:
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                if object_type == 'workflow':
                    from bisheng.database.models.flow import FlowDao
                    obj = await FlowDao.aget_flow_by_id(str(object_id))
                    return obj.tenant_id if obj else None
                if object_type == 'assistant':
                    from bisheng.database.models.assistant import AssistantDao
                    obj = await AssistantDao.aget_one_assistant(str(object_id))
                    return obj.tenant_id if obj else None
                if object_type == 'knowledge_space':
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
                    obj = await KnowledgeDao.aquery_by_id(int(object_id))
                    return obj.tenant_id if obj and obj.type == KnowledgeTypeEnum.SPACE.value else None
                if object_type == 'knowledge_library':
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

                    obj = await KnowledgeDao.aquery_by_id(int(object_id))
                    if obj and obj.type in (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value):
                        return obj.tenant_id
                    return None
        except Exception as e:  # noqa: BLE001 — defensive degradation
            logger.warning(
                '_resolve_resource_tenant failed for %s:%s: %s',
                object_type, object_id, e,
            )
            return None
        return None

    @classmethod
    async def _is_shared_to(
        cls,
        user_id: int,
        target_tenant_id: int,
        visible_tenant_ids: Optional[List[int]] = None,
    ) -> bool:
        """True iff any visible tenant of the user has ``shared_to`` on target tenant.

        F017 writes tuples as ``tenant:{child}#shared_to -> tenant:{root}``.
        OpenFGA ``object`` must stay in ``type:id`` form, so we must query
        against ``object=tenant:{target}`` and use the visible tenant itself
        as the tuple subject.
        """
        fga = await cls._aget_fga()
        if fga is None:
            return False

        candidate_tenant_ids = [
            int(one) for one in (visible_tenant_ids or []) if str(one).isdigit()
        ]
        if not candidate_tenant_ids:
            try:
                from bisheng.database.models.tenant import UserTenantDao, ROOT_TENANT_ID

                active = await UserTenantDao.aget_active_user_tenant(user_id)
                if active and active.tenant_id != ROOT_TENANT_ID:
                    candidate_tenant_ids = [int(active.tenant_id), ROOT_TENANT_ID]
                else:
                    candidate_tenant_ids = [ROOT_TENANT_ID]
            except Exception as e:
                logger.warning(
                    '[FGA shared_to check] fallback visible tenant lookup failed '
                    'user_id=%s target_tenant_id=%s error=%s',
                    user_id, target_tenant_id, e,
                )
                return False

        fga_relation = 'shared_to'
        fga_object = f'tenant:{target_tenant_id}'
        try:
            for tenant_id in candidate_tenant_ids:
                fga_user = f'tenant:{tenant_id}'
                logger.info(
                    '[FGA shared_to check] user_id=%s target_tenant_id=%s '
                    'candidate_tenant_id=%s user=%s relation=%s object=%s',
                    user_id, target_tenant_id, tenant_id, fga_user, fga_relation, fga_object,
                )
                if await fga.check(
                    user=fga_user,
                    relation=fga_relation,
                    object=fga_object,
                ):
                    return True
            return False
        except FGAConnectionError:
            return False
        except Exception as e:
            logger.error(
                '[FGA shared_to check] failed user_id=%s target_tenant_id=%s '
                'candidate_tenant_ids=%s relation=%s object=%s error=%s',
                user_id, target_tenant_id, candidate_tenant_ids, fga_relation, fga_object, e,
            )
            return False
