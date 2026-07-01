"""DepartmentChangeHandler — produces TupleOperation DTOs for OpenFGA integration.

Part of F002-department-tree. Defines the contract between F002 (department tree)
and F004 (ReBAC permissions). Each department mutation (create/move/archive/members)
produces a list of TupleOperations that describe the intended OpenFGA writes/deletes.

execute_async() delegates to PermissionService.batch_write_tuples() for real OpenFGA writes.
execute() is kept as a synchronous fallback (logs only).
"""

from __future__ import annotations

import logging

from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["DepartmentChangeHandler", "TupleOperation"]


class DepartmentChangeHandler:
    """Produces TupleOperation lists for department lifecycle events.

    All methods are @staticmethod — no instance state needed.
    """

    @staticmethod
    def on_created(dept_id: int, parent_id: int) -> list[TupleOperation]:
        """Department created under a parent."""
        return [
            TupleOperation(
                action="write",
                user=f"department:{parent_id}",
                relation="parent",
                object=f"department:{dept_id}",
            ),
        ]

    @staticmethod
    def on_moved(
        dept_id: int,
        old_parent_id: int,
        new_parent_id: int,
    ) -> list[TupleOperation]:
        """Department moved from old parent to new parent."""
        return [
            TupleOperation(
                action="delete",
                user=f"department:{old_parent_id}",
                relation="parent",
                object=f"department:{dept_id}",
            ),
            TupleOperation(
                action="write",
                user=f"department:{new_parent_id}",
                relation="parent",
                object=f"department:{dept_id}",
            ),
        ]

    @staticmethod
    def on_reparented(
        dept_id: int,
        old_parent_id: int | None,
        new_parent_id: int | None,
    ) -> list[TupleOperation]:
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
        ops: list[TupleOperation] = []
        if old_p is not None:
            ops.append(
                TupleOperation(
                    action="delete",
                    user=f"department:{old_p}",
                    relation="parent",
                    object=f"department:{dept_id}",
                )
            )
        if new_p is not None:
            ops.append(
                TupleOperation(
                    action="write",
                    user=f"department:{new_p}",
                    relation="parent",
                    object=f"department:{dept_id}",
                )
            )
        return ops

    @staticmethod
    def on_archived(dept_id: int, parent_id: int) -> list[TupleOperation]:
        """Department archived (soft-deleted)."""
        return [
            TupleOperation(
                action="delete",
                user=f"department:{parent_id}",
                relation="parent",
                object=f"department:{dept_id}",
            ),
        ]

    @staticmethod
    def on_members_added(
        dept_id: int,
        user_ids: list[int],
    ) -> list[TupleOperation]:
        """Users added as members of a department."""
        return [
            TupleOperation(
                action="write",
                user=f"user:{uid}",
                relation="member",
                object=f"department:{dept_id}",
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_member_removed(dept_id: int, user_id: int) -> list[TupleOperation]:
        """User removed from a department."""
        return [
            TupleOperation(
                action="delete",
                user=f"user:{user_id}",
                relation="member",
                object=f"department:{dept_id}",
            ),
        ]

    @staticmethod
    def on_admin_set(
        dept_id: int,
        user_ids: list[int],
    ) -> list[TupleOperation]:
        """Users set as admins of a department."""
        return [
            TupleOperation(
                action="write",
                user=f"user:{uid}",
                relation="admin",
                object=f"department:{dept_id}",
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_admin_removed(
        dept_id: int,
        user_ids: list[int],
    ) -> list[TupleOperation]:
        """Users removed as admins of a department."""
        return [
            TupleOperation(
                action="delete",
                user=f"user:{uid}",
                relation="admin",
                object=f"department:{dept_id}",
            )
            for uid in user_ids
        ]

    @staticmethod
    def on_purged(
        dept_id: int,
        member_user_ids: list[int],
        admin_user_ids: list[int],
    ) -> list[TupleOperation]:
        """Department permanently deleted — clean up all remaining tuples."""
        ops: list[TupleOperation] = []
        for uid in member_user_ids:
            ops.append(
                TupleOperation(
                    action="delete",
                    user=f"user:{uid}",
                    relation="member",
                    object=f"department:{dept_id}",
                )
            )
        for uid in admin_user_ids:
            ops.append(
                TupleOperation(
                    action="delete",
                    user=f"user:{uid}",
                    relation="admin",
                    object=f"department:{dept_id}",
                )
            )
        return ops

    @staticmethod
    async def execute_async(operations: list[TupleOperation]) -> None:
        """Execute tuple operations via OpenFGA (F004 ReBAC integration).

        Uses crash_safe=True so that if the process crashes after DB commit
        but before FGA write, the pre-recorded FailedTuples ensure recovery.
        """
        if not operations:
            return
        from bisheng.permission.domain.services.permission_service import PermissionService

        await PermissionService.batch_write_tuples(operations, crash_safe=True)

    @staticmethod
    def execute(operations: list[TupleOperation]) -> None:
        """Synchronous fallback — logs operations only.

        Prefer execute_async() in async contexts.
        """
        if not operations:
            return
        logger.info(
            "DepartmentChangeHandler: %d tuple operations (sync fallback)",
            len(operations),
        )
        for op in operations:
            logger.debug(
                "  %s(%s, %s, %s)",
                op.action,
                op.user,
                op.relation,
                op.object,
            )
