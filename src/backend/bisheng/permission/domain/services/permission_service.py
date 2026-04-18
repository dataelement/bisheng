"""PermissionService — core ReBAC permission engine (T07b).

Permission check chain (AC-02):
  L1: Super admin shortcircuit（等效 owner，无 FGA 元组）
  L2: Redis cache（10s TTL，UNCACHEABLE_RELATIONS bypass）
  L3: OpenFGA check
  L4: DB creator = self → owner
  L4b: 部门管理员隐式「可管理」（管辖子树内成员创建的应用/知识库，无 FGA 元组、不出现在授权列表）
  L5: Fail-closed on FGA connection error（AD-03）

All methods are @classmethod — no instance state.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional, Set

from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.permission.domain.schemas.permission_schema import (
    UNCACHEABLE_RELATIONS,
    VALID_RELATIONS,
    VALID_RESOURCE_TYPES,
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
        'workflow', 'assistant', 'knowledge_space',
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

        # L2: Cache lookup (skip for UNCACHEABLE_RELATIONS)
        if relation not in UNCACHEABLE_RELATIONS:
            from bisheng.permission.domain.services.permission_cache import PermissionCache
            cached = await PermissionCache.get_check(user_id, relation, object_type, object_id)
            if cached is not None:
                return cached

        # L3: OpenFGA check
        try:
            fga = cls._get_fga()
            if fga is None:
                logger.warning('FGAClient not available, falling back to owner / implicit dept-admin')
                creator_id = await cls._get_resource_creator(object_type, object_id)
                if creator_id is not None and creator_id == user_id:
                    return True
                if creator_id is not None and await cls._implicit_dept_admin_covers(user_id, creator_id):
                    return cls._relation_implicit_manager_ok(relation, object_type)
                return False

            allowed = await fga.check(
                user=f'user:{user_id}',
                relation=relation,
                object=f'{object_type}:{object_id}',
            )

            # L4: Owner fallback — if FGA says no, check DB creator field
            if not allowed:
                creator_id = await cls._get_resource_creator(object_type, object_id)
                if creator_id is not None and creator_id == user_id:
                    allowed = True
                elif (
                    creator_id is not None
                    and await cls._implicit_dept_admin_covers(user_id, creator_id)
                    and cls._relation_implicit_manager_ok(relation, object_type)
                ):
                    allowed = True

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
                # 必须与隐式部门范围并集：旧缓存可能仅有 FGA list_objects，或部署前未合并隐式 ID
                implicit = await cls._resource_ids_implicit_dept_admin_scope(user_id, object_type)
                return list(set(cached) | set(implicit or []))

        try:
            fga = cls._get_fga()
            if fga is None:
                logger.warning('FGAClient not available for list_objects, using implicit dept-admin scope only')
                ids = await cls._resource_ids_implicit_dept_admin_scope(user_id, object_type)
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

            # 与 OpenFGA 并集：部门管理员对其管辖子树内成员创建的资源隐式具备可读/可管（不写 FGA）
            implicit = await cls._resource_ids_implicit_dept_admin_scope(user_id, object_type)
            if implicit:
                ids = list(set(ids) | set(implicit))

            # Cache result (skip for UNCACHEABLE_RELATIONS)
            if relation not in UNCACHEABLE_RELATIONS:
                await PermissionCache.set_list_objects(user_id, relation, object_type, ids)

            return ids

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during list_objects: %s', e)
            ids = await cls._resource_ids_implicit_dept_admin_scope(user_id, object_type)
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
    ) -> None:
        """Grant or revoke permissions on a resource.

        Expands department subjects to include sub-departments when include_children=True.
        Delegates to batch_write_tuples() for FGA writes + FailedTuple compensation.
        """
        operations: List[TupleOperation] = []
        affected_user_ids: set[int] = set()
        fga_object = f'{object_type}:{object_id}'

        for grant in (grants or []):
            fga_users = await cls._expand_subject(
                grant.subject_type, grant.subject_id, grant.include_children,
            )
            for fga_user in fga_users:
                operations.append(TupleOperation(
                    action='write', user=fga_user, relation=grant.relation, object=fga_object,
                ))
            if grant.subject_type == 'user':
                affected_user_ids.add(grant.subject_id)

        for revoke in (revokes or []):
            fga_users = await cls._expand_subject(
                revoke.subject_type, revoke.subject_id, revoke.include_children,
            )
            for fga_user in fga_users:
                operations.append(TupleOperation(
                    action='delete', user=fga_user, relation=revoke.relation, object=fga_object,
                ))
            if revoke.subject_type == 'user':
                affected_user_ids.add(revoke.subject_id)

        if not operations:
            return

        await cls.batch_write_tuples(operations)

        # Invalidate cache for directly affected users
        if affected_user_ids:
            from bisheng.permission.domain.services.permission_cache import PermissionCache
            for uid in affected_user_ids:
                await PermissionCache.invalidate_user(uid)

    # OpenFGA Write API limit per request
    _FGA_BATCH_SIZE = 100

    @classmethod
    async def batch_write_tuples(cls, operations: List[TupleOperation], crash_safe: bool = False) -> None:
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

        # Pre-record for crash safety — delete on success
        pre_recorded_ids: List[int] = []
        if crash_safe:
            pre_recorded_ids = await cls._pre_record_failed_tuples(operations)

        writes = [
            {'user': op.user, 'relation': op.relation, 'object': op.object}
            for op in operations if op.action == 'write'
        ]
        deletes = [
            {'user': op.user, 'relation': op.relation, 'object': op.object}
            for op in operations if op.action == 'delete'
        ]

        try:
            fga = cls._get_fga()
            if fga is None:
                if not crash_safe:
                    await cls._save_failed_tuples(operations, 'FGAClient not available')
                return

            # Chunk writes and deletes to stay within per-request limit
            batch = cls._FGA_BATCH_SIZE
            w_chunks = [writes[i:i + batch] for i in range(0, len(writes), batch)] if writes else []
            d_chunks = [deletes[i:i + batch] for i in range(0, len(deletes), batch)] if deletes else []

            max_chunks = max(len(w_chunks), len(d_chunks), 1)
            for idx in range(max_chunks):
                w = w_chunks[idx] if idx < len(w_chunks) else None
                d = d_chunks[idx] if idx < len(d_chunks) else None
                if w or d:
                    await fga.write_tuples(writes=w, deletes=d)

            # FGA succeeded — clean up pre-recorded FailedTuples
            if pre_recorded_ids:
                await cls._delete_pre_recorded(pre_recorded_ids)

        except Exception as e:
            logger.error('Failed to batch write tuples: %s', e)
            if not crash_safe:
                await cls._save_failed_tuples(operations, str(e))
            # If crash_safe, pre-recorded entries remain as 'pending' for retry

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
            fga = cls._get_fga()
            if fga is None:
                return []

            tuples = await fga.read_tuples(
                object=f'{object_type}:{object_id}',
            )
            if not tuples:
                return []

            return await cls._enrich_permission_tuples(tuples)

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

        # Step 3: Batch resolve names
        name_map = await cls._resolve_subject_names(user_ids, dept_ids, group_ids)

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
                    relation=p['relation'],
                ))

        return items

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

        try:
            fga = cls._get_fga()
            if fga is None:
                creator_id = await cls._get_resource_creator(object_type, object_id)
                if creator_id is not None and creator_id == user_id:
                    return PermissionLevel.owner.value
                if creator_id is not None and await cls._implicit_dept_admin_covers(user_id, creator_id):
                    return PermissionLevel.can_manage.value
                return None

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

            creator_id = await cls._get_resource_creator(object_type, object_id)
            if creator_id is not None and creator_id == user_id:
                return PermissionLevel.owner.value
            # 部门管理员对管辖子树内成员创建的资源隐式为「可管理」档位（不写 FGA，不出现在授权列表）
            if creator_id is not None and await cls._implicit_dept_admin_covers(user_id, creator_id):
                return PermissionLevel.can_manage.value

            return None

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during get_permission_level: %s', e)
            return None
        except Exception as e:
            logger.error('Error getting permission level: %s', e)
            return None

    # ── Internal helpers ────────────────────────────────────────

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
        uids = list(creator_uids)
        from bisheng.core.database import get_async_db_session
        from sqlmodel import col, select

        async with get_async_db_session() as session:
            if object_type == 'knowledge_space':
                from bisheng.knowledge.domain.models.knowledge import Knowledge

                stmt = select(Knowledge.id).where(col(Knowledge.user_id).in_(uids))
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
        return []

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
            if object_type in ('workflow', 'assistant'):
                from bisheng.database.models.flow import FlowDao
                flow = await FlowDao.aget_flow_by_id(object_id)
                return flow.user_id if flow else None

            if object_type == 'knowledge_space':
                from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
                ks = await KnowledgeDao.aquery_by_id(int(object_id))
                return ks.user_id if ks else None

            if object_type == 'knowledge_file':
                from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
                files = await KnowledgeFileDao.aget_file_by_ids([int(object_id)])
                return files[0].user_id if files else None

            # For other types (tool, channel, dashboard, folder), no direct
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
