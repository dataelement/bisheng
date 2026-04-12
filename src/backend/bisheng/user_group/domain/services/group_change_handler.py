"""GroupChangeHandler — produces TupleOperation DTOs for OpenFGA integration.

Part of F003-user-group. Defines the contract between F003 (user group)
and F004 (ReBAC permissions). Each user group mutation (create/delete/members/admins)
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
        user: The subject, e.g. "user:7".
        relation: The relationship type, e.g. "member", "admin".
        object: The target, e.g. "user_group:5".
    """
    action: Literal['write', 'delete']
    user: str
    relation: str
    object: str


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
    def execute(operations: List[TupleOperation]) -> None:
        """Execute tuple operations. Currently a log stub.

        F004 (ReBAC) will replace this with actual OpenFGA writes via
        PermissionService.batch_write_tuples().
        """
        if not operations:
            return
        logger.info(
            'GroupChangeHandler: %d tuple operations (stub, F004 not yet)',
            len(operations),
        )
        for op in operations:
            logger.debug(
                '  %s(%s, %s, %s)',
                op.action, op.user, op.relation, op.object,
            )
