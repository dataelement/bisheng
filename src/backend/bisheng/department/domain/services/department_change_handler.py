"""DepartmentChangeHandler — produces TupleOperation DTOs for OpenFGA integration.

Part of F002-department-tree. Defines the contract between F002 (department tree)
and F004 (ReBAC permissions). Each department mutation (create/move/archive/members)
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
__all__ = ['TupleOperation', 'DepartmentChangeHandler']


class DepartmentChangeHandler:
    """Produces TupleOperation lists for department lifecycle events.

    All methods are @staticmethod — no instance state needed.
    """

    @staticmethod
    def on_created(dept_id: int, parent_id: int) -> List[TupleOperation]:
        """Department created under a parent."""
        return [
            TupleOperation(
                action='write',
                user=f'department:{parent_id}',
                relation='parent',
                object=f'department:{dept_id}',
            ),
        ]

    @staticmethod
    def on_moved(
        dept_id: int, old_parent_id: int, new_parent_id: int,
    ) -> List[TupleOperation]:
        """Department moved from old parent to new parent."""
        return [
            TupleOperation(
                action='delete',
                user=f'department:{old_parent_id}',
                relation='parent',
                object=f'department:{dept_id}',
            ),
            TupleOperation(
                action='write',
                user=f'department:{new_parent_id}',
                relation='parent',
                object=f'department:{dept_id}',
            ),
        ]

    @staticmethod
    def on_archived(dept_id: int, parent_id: int) -> List[TupleOperation]:
        """Department archived (soft-deleted)."""
        return [
            TupleOperation(
                action='delete',
                user=f'department:{parent_id}',
                relation='parent',
                object=f'department:{dept_id}',
            ),
        ]

    @staticmethod
    def on_members_added(
        dept_id: int, user_ids: List[int],
    ) -> List[TupleOperation]:
        """Users added as members of a department."""
        return [
            TupleOperation(
                action='write',
                user=f'user:{uid}',
                relation='member',
                object=f'department:{dept_id}',
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_member_removed(dept_id: int, user_id: int) -> List[TupleOperation]:
        """User removed from a department."""
        return [
            TupleOperation(
                action='delete',
                user=f'user:{user_id}',
                relation='member',
                object=f'department:{dept_id}',
            ),
        ]

    @staticmethod
    async def execute_async(operations: List[TupleOperation]) -> None:
        """Execute tuple operations via OpenFGA (F004 ReBAC integration).

        Delegates to PermissionService.batch_write_tuples(). Failures are
        recorded in FailedTuple compensation queue — does not raise.
        """
        if not operations:
            return
        from bisheng.permission.domain.services.permission_service import PermissionService
        await PermissionService.batch_write_tuples(operations)

    @staticmethod
    def execute(operations: List[TupleOperation]) -> None:
        """Synchronous fallback — logs operations only.

        Prefer execute_async() in async contexts.
        """
        if not operations:
            return
        logger.info(
            'DepartmentChangeHandler: %d tuple operations (sync fallback)',
            len(operations),
        )
        for op in operations:
            logger.debug(
                '  %s(%s, %s, %s)',
                op.action, op.user, op.relation, op.object,
            )
