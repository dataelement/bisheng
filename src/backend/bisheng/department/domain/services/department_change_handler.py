"""Build and apply department identity permission changes.

Part of F002-department-tree. Defines the contract between F002 (department tree)
and the permission module. Each department mutation produces semantic grant
or revoke changes without exposing the authorization backend.
"""

from __future__ import annotations

import logging

from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionRelationChange,
    PermissionSubject,
)

logger = logging.getLogger(__name__)

__all__ = ["DepartmentChangeHandler"]


def _change(
    action: str,
    *,
    subject_type: str,
    subject_id: int,
    relation: str,
    department_id: int,
) -> PermissionRelationChange:
    return PermissionRelationChange(
        action="grant" if action == "grant" else "revoke",
        relation=PermissionRelation(
            subject=PermissionSubject(subject_type, str(subject_id)),
            relation=relation,
            resource=PermissionObject("department", str(department_id)),
        ),
    )


class DepartmentChangeHandler:
    """Produces permission changes for department lifecycle events.

    All methods are @staticmethod — no instance state needed.
    """

    @staticmethod
    def on_created(dept_id: int, parent_id: int) -> list[PermissionRelationChange]:
        """Department created under a parent."""
        return [
            _change(
                "grant",
                subject_type="department",
                subject_id=parent_id,
                relation="parent",
                department_id=dept_id,
            ),
        ]

    @staticmethod
    def on_moved(
        dept_id: int,
        old_parent_id: int,
        new_parent_id: int,
    ) -> list[PermissionRelationChange]:
        """Department moved from old parent to new parent."""
        return [
            _change(
                "revoke",
                subject_type="department",
                subject_id=old_parent_id,
                relation="parent",
                department_id=dept_id,
            ),
            _change(
                "grant",
                subject_type="department",
                subject_id=new_parent_id,
                relation="parent",
                department_id=dept_id,
            ),
        ]

    @staticmethod
    def on_reparented(
        dept_id: int,
        old_parent_id: int | None,
        new_parent_id: int | None,
    ) -> list[PermissionRelationChange]:
        """None-safe parent-edge delta for any create/move/detach.

        Emits a ``delete`` for a real old parent and a ``write`` for a real
        new parent; no-ops when a side is None (root has no parent edge) or
        the parent is unchanged. This is the single op-builder every
        mutation path (F002 manual, F014 SSO upsert/remove, single-root
        collapse) should use so ``department#parent`` always mirrors the DB
        tree without ever emitting a bogus ``department:None`` tuple.

        - None → real  : [write new]      (new top-level attached under root)
        - real → None  : [delete old]     (archived / removed)
        - real → real  : [delete, write]  (moved between parents)
        - unchanged / both None: []
        """
        old_p = old_parent_id or None
        new_p = new_parent_id or None
        if old_p == new_p:
            return []
        ops: list[PermissionRelationChange] = []
        if old_p is not None:
            ops.append(
                _change(
                    "revoke",
                    subject_type="department",
                    subject_id=old_p,
                    relation="parent",
                    department_id=dept_id,
                )
            )
        if new_p is not None:
            ops.append(
                _change(
                    "grant",
                    subject_type="department",
                    subject_id=new_p,
                    relation="parent",
                    department_id=dept_id,
                )
            )
        return ops

    @staticmethod
    def on_archived(dept_id: int, parent_id: int) -> list[PermissionRelationChange]:
        """Department archived (soft-deleted)."""
        return [
            _change(
                "revoke",
                subject_type="department",
                subject_id=parent_id,
                relation="parent",
                department_id=dept_id,
            ),
        ]

    @staticmethod
    def on_members_added(
        dept_id: int,
        user_ids: list[int],
    ) -> list[PermissionRelationChange]:
        """Users added as members of a department."""
        return [
            _change(
                "grant",
                subject_type="user",
                subject_id=uid,
                relation="member",
                department_id=dept_id,
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_member_removed(dept_id: int, user_id: int) -> list[PermissionRelationChange]:
        """User removed from a department."""
        return [
            _change(
                "revoke",
                subject_type="user",
                subject_id=user_id,
                relation="member",
                department_id=dept_id,
            ),
        ]

    @staticmethod
    def on_admin_set(
        dept_id: int,
        user_ids: list[int],
    ) -> list[PermissionRelationChange]:
        """Users set as admins of a department."""
        return [
            _change(
                "grant",
                subject_type="user",
                subject_id=uid,
                relation="admin",
                department_id=dept_id,
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_admin_removed(
        dept_id: int,
        user_ids: list[int],
    ) -> list[PermissionRelationChange]:
        """Users removed as admins of a department."""
        return [
            _change(
                "revoke",
                subject_type="user",
                subject_id=uid,
                relation="admin",
                department_id=dept_id,
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_purged(
        dept_id: int,
        member_user_ids: list[int],
        admin_user_ids: list[int],
    ) -> list[PermissionRelationChange]:
        """Department permanently deleted — revoke all remaining relations."""
        ops: list[PermissionRelationChange] = []
        for uid in member_user_ids:
            ops.append(
                _change(
                    "revoke",
                    subject_type="user",
                    subject_id=uid,
                    relation="member",
                    department_id=dept_id,
                )
            )
        for uid in admin_user_ids:
            ops.append(
                _change(
                    "revoke",
                    subject_type="user",
                    subject_id=uid,
                    relation="admin",
                    department_id=dept_id,
                )
            )
        return ops

    @staticmethod
    async def execute_async(operations: list[PermissionRelationChange]) -> None:
        """Apply changes through the crash-safe permission protocol."""
        if not operations:
            return
        from bisheng.permission.application import get_permission_relation_api

        permissions = await get_permission_relation_api()
        await permissions.apply_changes(tuple(operations), crash_safe=True)

    @staticmethod
    def execute(operations: list[PermissionRelationChange]) -> None:
        """Synchronous fallback — logs operations only.

        Prefer execute_async() in async contexts.
        """
        if not operations:
            return
        logger.info(
            "DepartmentChangeHandler: %d permission changes (sync fallback)",
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
