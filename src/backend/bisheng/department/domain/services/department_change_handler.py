"""DepartmentChangeHandler — produces TupleOperation DTOs for OpenFGA integration.

Part of F002-department-tree. Defines the contract between F002 (department tree)
and F004 (ReBAC permissions). Each department mutation (create/move/archive/members)
produces a list of TupleOperations that describe the intended OpenFGA writes/deletes.

Currently execute() is a log stub — F004 will replace it with actual OpenFGA writes
via PermissionService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Literal

logger = logging.getLogger(__name__)


@dataclass
class TupleOperation:
    """A single OpenFGA tuple write or delete operation.

    Attributes:
        action: 'write' to create a relationship, 'delete' to remove it.
        user: The subject, e.g. "user:7" or "department:5#member".
        relation: The relationship type, e.g. "member", "admin", "parent".
        object: The target, e.g. "department:5".
    """
    action: Literal['write', 'delete']
    user: str
    relation: str
    object: str


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
    def execute(operations: List[TupleOperation]) -> None:
        """Execute tuple operations. Currently a log stub.

        F004 (ReBAC) will replace this with actual OpenFGA writes via
        PermissionService.batch_write_tuples().
        """
        if not operations:
            return
        logger.info(
            'DepartmentChangeHandler: %d tuple operations (stub, F004 not yet)',
            len(operations),
        )
        for op in operations:
            logger.debug(
                '  %s(%s, %s, %s)',
                op.action, op.user, op.relation, op.object,
            )
