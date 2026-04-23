"""OwnerService — convenience methods for resource ownership management (T13).

Provides the contract for F008 (resource adaptation) to call when creating resources.
INV-2: every resource must have exactly one owner tuple in OpenFGA.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem

logger = logging.getLogger(__name__)


def _run_async_safe(coro):
    """Run an async coroutine from a sync context, handling event loop issues.

    In FastAPI threadpool threads, asyncio.run() creates a new event loop which
    cannot share connections (aiomysql, Redis) with the main loop. This helper
    detects the running loop and uses run_coroutine_threadsafe() when available.
    """
    try:
        loop = asyncio.get_running_loop()
        # Thread has a running loop — dispatch safely
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=10)
    except RuntimeError:
        # No running loop — safe to create one
        return asyncio.run(coro)


# SpaceChannelMember role → FGA relation mapping (shared by KnowledgeSpace + Channel dual-write)
SCM_ROLE_TO_FGA: dict = {}  # Populated lazily to avoid circular import with UserRoleEnum


def _get_scm_role_to_fga() -> dict:
    """Lazy-load SCM role mapping to avoid circular import."""
    global SCM_ROLE_TO_FGA
    if not SCM_ROLE_TO_FGA:
        from bisheng.common.models.space_channel_member import UserRoleEnum
        SCM_ROLE_TO_FGA = {
            UserRoleEnum.CREATOR: 'owner',
            UserRoleEnum.ADMIN: 'manager',
            UserRoleEnum.MEMBER: 'viewer',
        }
    return SCM_ROLE_TO_FGA


class OwnerService:
    """Stateless service for owner tuple management. All methods are @classmethod."""

    @classmethod
    async def write_owner_tuple(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> None:
        """Write an owner tuple for a newly created resource.

        Called during resource creation (F008 integration point).
        Does not raise on failure — FailedTuple compensation handles retries.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.authorize(
            object_type=object_type,
            object_id=object_id,
            grants=[
                AuthorizeGrantItem(
                    subject_type='user',
                    subject_id=user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
        )

    @classmethod
    def write_owner_tuple_sync(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> None:
        """Sync wrapper for write_owner_tuple. Safe to call from FastAPI threadpool."""
        try:
            _run_async_safe(cls.write_owner_tuple(user_id, object_type, object_id))
        except Exception as e:
            logger.warning('Failed to write owner tuple (sync) for %s:%s: %s', object_type, object_id, e)

    @classmethod
    def delete_resource_tuples_sync(
        cls,
        object_type: str,
        object_id: str,
    ) -> None:
        """Sync wrapper for delete_resource_tuples. Safe to call from FastAPI threadpool."""
        try:
            _run_async_safe(cls.delete_resource_tuples(object_type, object_id))
        except Exception as e:
            logger.warning('Failed to delete tuples (sync) for %s:%s: %s', object_type, object_id, e)

    @classmethod
    async def check_is_owner(
        cls,
        user_id: int,
        object_type: str,
        object_id: str,
    ) -> bool:
        """Check if user is the owner of a resource."""
        from bisheng.permission.domain.services.permission_service import PermissionService
        return await PermissionService.check(
            user_id=user_id,
            relation='owner',
            object_type=object_type,
            object_id=object_id,
        )

    @classmethod
    async def delete_resource_tuples(
        cls,
        object_type: str,
        object_id: str,
    ) -> None:
        """Delete all FGA tuples for a resource (called on resource deletion).

        Reads all tuples via FGA read_tuples, then batch deletes.
        Does not raise on failure — logs warning and returns (AC-03).
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        fga = PermissionService._get_fga()
        if fga is None:
            logger.warning('FGAClient not available for tuple cleanup: %s:%s', object_type, object_id)
            return
        try:
            tuples = await fga.read_tuples(object=f'{object_type}:{object_id}')
            if not tuples:
                return
            from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
            operations = [
                TupleOperation(
                    action='delete',
                    user=t['user'],
                    relation=t['relation'],
                    object=t['object'],
                )
                for t in tuples
            ]
            await PermissionService.batch_write_tuples(operations)
            logger.info('Cleaned up %d tuples for %s:%s', len(operations), object_type, object_id)
        except Exception as e:
            logger.warning('Failed to cleanup tuples for %s:%s: %s', object_type, object_id, e)

    @classmethod
    async def transfer_ownership(
        cls,
        from_user_id: int,
        to_user_id: int,
        object_type: str,
        object_id: str,
    ) -> None:
        """Transfer ownership from one user to another.

        Single authorize() call with revoke old + grant new.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.authorize(
            object_type=object_type,
            object_id=object_id,
            grants=[
                AuthorizeGrantItem(
                    subject_type='user',
                    subject_id=to_user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
            enforce_fga_success=True,
            revokes=[
                AuthorizeRevokeItem(
                    subject_type='user',
                    subject_id=from_user_id,
                    relation='owner',
                    include_children=False,
                ),
            ],
        )
