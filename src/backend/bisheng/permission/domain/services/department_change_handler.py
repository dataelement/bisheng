"""Atomic F048 projections for verified department changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
)


@dataclass(frozen=True, slots=True)
class DepartmentProjectionContext:
    tenant_id: int
    department_id: int
    expected_version: int
    store_id: str
    model_id: str
    operator_id: int
    idempotency_key: str


class DepartmentProjectionPort(Protocol):
    async def execute(self, plan: ProjectionPlan): ...


class F048DepartmentChangeHandler:
    """Compile parent mirrors and direct membership into one ledger plan."""

    def __init__(self, *, projection: DepartmentProjectionPort) -> None:
        self._projection = projection

    async def project_created(
        self,
        *,
        context: DepartmentProjectionContext,
        parent_id: int,
    ):
        return await self._projection.execute(
            self.build_created_plan(
                context=context,
                parent_id=parent_id,
            )
        )

    def build_created_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        parent_id: int,
    ) -> ProjectionPlan:
        self._validate_context(context)
        self._validate_parent(context.department_id, parent_id)
        deltas = self._parent_deltas(
            context.department_id,
            parent_id,
            action="WRITE",
        )
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_CREATE",
            change_item_count=1,
            deltas=deltas,
        )

    async def project_moved(
        self,
        *,
        context: DepartmentProjectionContext,
        old_parent_id: int,
        new_parent_id: int,
    ):
        return await self._projection.execute(
            self.build_moved_plan(
                context=context,
                old_parent_id=old_parent_id,
                new_parent_id=new_parent_id,
            )
        )

    def build_moved_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        old_parent_id: int,
        new_parent_id: int,
    ) -> ProjectionPlan:
        self._validate_context(context)
        self._validate_parent(context.department_id, old_parent_id)
        self._validate_parent(context.department_id, new_parent_id)
        if old_parent_id == new_parent_id:
            raise PermissionInvalidResourceError()

        deltas = (
            *self._parent_deltas(
                context.department_id,
                old_parent_id,
                action="DELETE",
                sequence_start=0,
            ),
            *self._parent_deltas(
                context.department_id,
                new_parent_id,
                action="WRITE",
                sequence_start=2,
            ),
        )
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_MOVE",
            change_item_count=1,
            deltas=deltas,
        )

    async def project_members_added(
        self,
        *,
        context: DepartmentProjectionContext,
        user_ids: tuple[int, ...],
    ):
        return await self._projection.execute(
            self.build_members_added_plan(
                context=context,
                user_ids=user_ids,
            )
        )

    def build_members_added_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        user_ids: tuple[int, ...],
    ) -> ProjectionPlan:
        self._validate_context(context)
        normalized = self._normalize_user_ids(user_ids)
        deltas = tuple(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=index,
                action="WRITE",
                user=f"user:{user_id}",
                relation="member",
                object=f"department:{context.department_id}",
            )
            for index, user_id in enumerate(normalized)
        )
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_MEMBERS_ADD",
            change_item_count=len(normalized),
            deltas=deltas,
        )

    async def project_member_removed(
        self,
        *,
        context: DepartmentProjectionContext,
        user_id: int,
    ):
        return await self._projection.execute(
            self.build_member_removed_plan(
                context=context,
                user_id=user_id,
            )
        )

    def build_member_removed_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        user_id: int,
    ) -> ProjectionPlan:
        self._validate_context(context)
        normalized = self._normalize_user_ids((user_id,))
        delta = ProjectionTupleDelta(
            phase="COMMIT",
            sequence=0,
            action="DELETE",
            user=f"user:{normalized[0]}",
            relation="member",
            object=f"department:{context.department_id}",
        )
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_MEMBER_REMOVE",
            change_item_count=1,
            deltas=(delta,),
        )

    def build_archived_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        parent_id: int,
    ) -> ProjectionPlan:
        self._validate_context(context)
        self._validate_parent(context.department_id, parent_id)
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_ARCHIVE",
            change_item_count=1,
            deltas=self._parent_deltas(
                context.department_id,
                parent_id,
                action="DELETE",
            ),
        )

    def build_restored_plan(
        self,
        *,
        context: DepartmentProjectionContext,
        parent_id: int,
    ) -> ProjectionPlan:
        self._validate_context(context)
        self._validate_parent(context.department_id, parent_id)
        return self._build_plan(
            context,
            operation_type="DEPARTMENT_RESTORE",
            change_item_count=1,
            deltas=self._parent_deltas(
                context.department_id,
                parent_id,
                action="WRITE",
            ),
        )

    @staticmethod
    def _build_plan(
        context: DepartmentProjectionContext,
        *,
        operation_type: str,
        change_item_count: int,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> ProjectionPlan:
        return ProjectionPlan(
            tenant_id=context.tenant_id,
            idempotency_key=context.idempotency_key,
            operation_type=operation_type,
            scope_type="department",
            scope_key=str(context.department_id),
            expected_version=context.expected_version,
            target_version=context.expected_version + 1,
            store_id=context.store_id,
            model_id=context.model_id,
            operator_id=context.operator_id,
            change_item_count=change_item_count,
            deltas=deltas,
        )

    @staticmethod
    def _parent_deltas(
        department_id: int,
        parent_id: int,
        *,
        action: str,
        sequence_start: int = 0,
    ) -> tuple[ProjectionTupleDelta, ProjectionTupleDelta]:
        return (
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=sequence_start,
                action=action,
                user=f"department:{parent_id}",
                relation="parent",
                object=f"department:{department_id}",
            ),
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=sequence_start + 1,
                action=action,
                user=f"department:{department_id}",
                relation="child",
                object=f"department:{parent_id}",
            ),
        )

    @staticmethod
    def _validate_context(context: DepartmentProjectionContext) -> None:
        if (
            context.tenant_id <= 0
            or context.department_id <= 0
            or context.expected_version < 0
            or context.operator_id < 0
            or not context.store_id
            or not context.model_id
            or not context.idempotency_key
        ):
            raise PermissionInvalidResourceError()

    @staticmethod
    def _validate_parent(department_id: int, parent_id: int) -> None:
        if parent_id <= 0 or parent_id == department_id:
            raise PermissionInvalidResourceError()

    @staticmethod
    def _normalize_user_ids(user_ids: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(dict.fromkeys(user_ids))
        if not normalized or any(user_id <= 0 for user_id in normalized):
            raise PermissionInvalidResourceError()
        return normalized
