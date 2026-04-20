"""GroupChangeHandler — produces TupleOperation DTOs for OpenFGA integration.

Part of F003-user-group. Defines the contract between F003 (user group)
and F004 (ReBAC permissions). Each user group mutation (create/delete/members/admins)
produces a list of TupleOperations that describe the intended OpenFGA writes/deletes.

execute_async() delegates to PermissionService.batch_write_tuples() for real OpenFGA writes.
execute() is kept as a synchronous fallback (logs only).
"""

from __future__ import annotations

import logging
from typing import List

from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ['TupleOperation', 'GroupChangeHandler']


class GroupChangeHandler:
    """Produces TupleOperation lists for user group lifecycle events.

    All methods are @staticmethod — no instance state needed.
    """

    @staticmethod
    def on_created(group_id: int, creator_user_id: int) -> List[TupleOperation]:
        """User group created — creator becomes admin."""
        return [
            TupleOperation(
                action='write',
                user=f'user:{creator_user_id}',
                relation='admin',
                object=f'user_group:{group_id}',
            ),
        ]

    @staticmethod
    def on_deleted(group_id: int) -> List[TupleOperation]:
        """User group deleted — F004 handles cascade cleanup of all tuples."""
        return []

    @staticmethod
    def on_members_added(
        group_id: int, user_ids: List[int],
    ) -> List[TupleOperation]:
        """Users added as members of a user group."""
        return [
            TupleOperation(
                action='write',
                user=f'user:{uid}',
                relation='member',
                object=f'user_group:{group_id}',
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_member_removed(group_id: int, user_id: int) -> List[TupleOperation]:
        """User removed from a user group."""
        return [
            TupleOperation(
                action='delete',
                user=f'user:{user_id}',
                relation='member',
                object=f'user_group:{group_id}',
            ),
        ]

    @staticmethod
    def on_admin_set(
        group_id: int, user_ids: List[int],
    ) -> List[TupleOperation]:
        """Users set as admins of a user group."""
        return [
            TupleOperation(
                action='write',
                user=f'user:{uid}',
                relation='admin',
                object=f'user_group:{group_id}',
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_admin_removed(
        group_id: int, user_ids: List[int],
    ) -> List[TupleOperation]:
        """Users removed as admins of a user group."""
        return [
            TupleOperation(
                action='delete',
                user=f'user:{uid}',
                relation='admin',
                object=f'user_group:{group_id}',
            )
            for uid in user_ids
        ]

    @staticmethod
    async def execute_async(operations: List[TupleOperation]) -> None:
        """Execute tuple operations via OpenFGA (F004 ReBAC integration).

        Uses crash_safe=True so that if the process crashes after DB commit
        but before FGA write, the pre-recorded FailedTuples ensure recovery.
        """
        if not operations:
            return
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.batch_write_tuples(operations, crash_safe=True)

    @staticmethod
    def execute(operations: List[TupleOperation]) -> None:
        """Synchronous fallback — logs operations only.

        Prefer execute_async() in async contexts.
        """
        if not operations:
            return
        logger.info(
            'GroupChangeHandler: %d tuple operations (sync fallback)',
            len(operations),
        )
        for op in operations:
            logger.debug(
                '  %s(%s, %s, %s)',
                op.action, op.user, op.relation, op.object,
            )
