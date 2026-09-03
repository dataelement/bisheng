"""Build and apply user-group identity permission changes.

Part of F003-user-group. Defines the contract between F003 (user group)
and the permission module. Each mutation produces semantic grant or revoke
changes without exposing the authorization backend.
"""

from __future__ import annotations

import logging
from typing import List

from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionRelationChange,
    PermissionSubject,
)

logger = logging.getLogger(__name__)

__all__ = ["GroupChangeHandler"]


def _change(action: str, *, group_id: int, user_id: int, relation: str) -> PermissionRelationChange:
    return PermissionRelationChange(
        action="grant" if action == "grant" else "revoke",
        relation=PermissionRelation(
            subject=PermissionSubject("user", str(user_id)),
            relation=relation,
            resource=PermissionObject("user_group", str(group_id)),
        ),
    )


class GroupChangeHandler:
    """Produces permission changes for user-group lifecycle events.

    All methods are @staticmethod — no instance state needed.
    """

    @staticmethod
    def on_created(group_id: int, creator_user_id: int) -> List[PermissionRelationChange]:
        """User group created — creator becomes admin."""
        return [
            _change(
                "grant",
                group_id=group_id,
                user_id=creator_user_id,
                relation="admin",
            ),
        ]

    @staticmethod
    def on_deleted(group_id: int) -> List[PermissionRelationChange]:
        """User group deletion is handled by permission lifecycle cleanup."""
        return []

    @staticmethod
    def on_members_added(
        group_id: int,
        user_ids: List[int],
    ) -> List[PermissionRelationChange]:
        """Users added as members of a user group."""
        return [
            _change(
                "grant",
                group_id=group_id,
                user_id=uid,
                relation="member",
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_member_removed(group_id: int, user_id: int) -> List[PermissionRelationChange]:
        """User removed from a user group."""
        return [
            _change(
                "revoke",
                group_id=group_id,
                user_id=user_id,
                relation="member",
            ),
        ]

    @staticmethod
    def on_admin_set(
        group_id: int,
        user_ids: List[int],
    ) -> List[PermissionRelationChange]:
        """Users set as admins of a user group."""
        return [
            _change(
                "grant",
                group_id=group_id,
                user_id=uid,
                relation="admin",
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_admin_removed(
        group_id: int,
        user_ids: List[int],
    ) -> List[PermissionRelationChange]:
        """Users removed as admins of a user group."""
        return [
            _change(
                "revoke",
                group_id=group_id,
                user_id=uid,
                relation="admin",
            )
            for uid in user_ids
        ]

    @staticmethod
    async def execute_async(operations: List[PermissionRelationChange]) -> None:
        """Apply changes through the crash-safe permission protocol."""
        if not operations:
            return
        from bisheng.permission.application import get_permission_relation_api

        permissions = await get_permission_relation_api()
        await permissions.apply_changes(tuple(operations), crash_safe=True)
        affected_user_ids: set[int] = set()
        for op in operations:
            subject = op.relation.subject
            if subject.subject_type != "user":
                continue
            try:
                affected_user_ids.add(int(subject.subject_id))
            except ValueError:
                continue
        if affected_user_ids:
            from bisheng.permission.domain.services.permission_cache import PermissionCache

            for uid in affected_user_ids:
                await PermissionCache.invalidate_user(uid)

    @staticmethod
    def execute(operations: List[PermissionRelationChange]) -> None:
        """Synchronous fallback — logs operations only.

        Prefer execute_async() in async contexts.
        """
        if not operations:
            return
        logger.info(
            "GroupChangeHandler: %d permission changes (sync fallback)",
            len(operations),
        )
        for op in operations:
            logger.debug(
                "  %s(%s, %s, %s)",
                op.action,
                op.relation.subject,
                op.relation.relation,
                op.relation.resource,
            )
