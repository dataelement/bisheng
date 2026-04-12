"""PermissionService — core ReBAC permission engine (T07b).

Five-level permission check chain (AC-02):
  L1: Super admin shortcircuit
  L2: L2 Redis cache (10s TTL, UNCACHEABLE_RELATIONS bypass)
  L3: OpenFGA check
  L4: Owner fallback (DB user_id field)
  L5: Fail-closed on FGA connection error (AD-03)

All methods are @classmethod — no instance state.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.permission.domain.schemas.permission_schema import (
    UNCACHEABLE_RELATIONS,
    VALID_RELATIONS,
    VALID_RESOURCE_TYPES,
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
    PermissionLevel,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)


class PermissionService:
    """Stateless service for ReBAC permission operations."""

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
                logger.warning('FGAClient not available, falling back to owner check')
                creator_id = await cls._get_resource_creator(object_type, object_id)
                return creator_id is not None and creator_id == user_id

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

        # Cache lookup
        from bisheng.permission.domain.services.permission_cache import PermissionCache
        cached = await PermissionCache.get_list_objects(user_id, relation, object_type)
        if cached is not None:
            return cached

        try:
            fga = cls._get_fga()
            if fga is None:
                logger.warning('FGAClient not available for list_objects')
                return []

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

            # Cache result
            await PermissionCache.set_list_objects(user_id, relation, object_type, ids)

            return ids

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during list_objects: %s', e)
            return []
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

    @classmethod
    async def batch_write_tuples(cls, operations: List[TupleOperation]) -> None:
        """Batch write/delete tuples to OpenFGA.

        Used by ChangeHandler.execute_async(). Failures recorded in FailedTuple.
        """
        if not operations:
            return

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
                await cls._save_failed_tuples(operations, 'FGAClient not available')
                return

            await fga.write_tuples(
                writes=writes or None,
                deletes=deletes or None,
            )
        except (FGAConnectionError, Exception) as e:
            logger.error('Failed to batch write tuples: %s', e)
            await cls._save_failed_tuples(operations, str(e))

    @classmethod
    async def get_resource_permissions(
        cls,
        object_type: str,
        object_id: str,
    ) -> List[dict]:
        """List all permission entries for a resource.

        Returns list of {"user": ..., "relation": ..., "object": ...}.
        """
        try:
            fga = cls._get_fga()
            if fga is None:
                return []

            tuples = await fga.read_tuples(
                object=f'{object_type}:{object_id}',
            )
            return tuples

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during read_tuples: %s', e)
            return []
        except Exception as e:
            logger.error('Error reading resource permissions: %s', e)
            return []

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

            # Check owner fallback
            creator_id = await cls._get_resource_creator(object_type, object_id)
            if creator_id is not None and creator_id == user_id:
                return PermissionLevel.owner.value

            return None

        except FGAConnectionError as e:
            logger.error('OpenFGA unreachable during get_permission_level: %s', e)
            return None
        except Exception as e:
            logger.error('Error getting permission level: %s', e)
            return None

    # ── Internal helpers ────────────────────────────────────────

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

    @staticmethod
    def _get_fga():
        """Get FGAClient from app context. Returns None if unavailable."""
        from bisheng.core.openfga.manager import get_fga_client
        return get_fga_client()
