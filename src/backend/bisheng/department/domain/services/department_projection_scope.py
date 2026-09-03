"""Business-owned durable scope for F048 department identity projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.core.context import FunctionContextManager
from bisheng.core.context.manager import app_context
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.services.department_change_handler import (
    F048DepartmentChangeHandler,
)
from bisheng.permission.domain.services.projection_plan import (
    ProjectionOutcome,
    ProjectionPlan,
)

DEPARTMENT_PROJECTION_CURRENT = "CURRENT"
DEPARTMENT_PROJECTION_PROJECTING = "PROJECTING"
DEPARTMENT_PROJECTION_FAILED_CLOSED = "FAILED_CLOSED"


class DepartmentProjectionLedgerPort(Protocol):
    async def prepare(
        self,
        plan: ProjectionPlan,
    ) -> PermissionProjectionOperation: ...

    async def execute(
        self,
        plan: ProjectionPlan,
    ) -> ProjectionOutcome: ...

    async def abandon_prepared(
        self,
        plan: ProjectionPlan,
        error: Exception,
    ) -> None: ...

    async def reconcile_operation(
        self,
        operation_id: int,
    ) -> ProjectionOutcome: ...


@dataclass(frozen=True, slots=True)
class PreparedDepartmentProjection:
    plan: ProjectionPlan
    operation_id: int


class SqlDepartmentProjectionScope:
    """Keep department topology facts outside the permission domain.

    A DepartmentService transaction first prepares the permission ledger, then
    binds that operation ID to the department row in the same transaction as
    the verified topology or membership mutation. The permission ledger calls
    ``reserve`` before its first OpenFGA write; only that durable binding is
    accepted, so a prepared operation whose business transaction rolled back
    cannot project stale or invented department facts.
    """

    async def bind(
        self,
        session: AsyncSession,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        department_id = self._identity(plan, operation_id)
        statement = (
            update(Department)
            .where(
                Department.id == department_id,
                Department.tenant_id == plan.tenant_id,
                Department.permission_projection_version == plan.expected_version,
                Department.permission_projection_state == DEPARTMENT_PROJECTION_CURRENT,
            )
            .values(
                permission_projection_state=(DEPARTMENT_PROJECTION_PROJECTING),
                permission_projection_operation_id=operation_id,
            )
        )
        result = await session.execute(statement)
        if result.rowcount:
            return
        row = await self._load(
            session,
            plan,
            for_update=True,
        )
        if (
            row is not None
            and row.permission_projection_version == plan.expected_version
            and row.permission_projection_state == DEPARTMENT_PROJECTION_PROJECTING
            and row.permission_projection_operation_id == operation_id
        ):
            return
        raise PermissionVersionConflictError(msg="Department permission projection changed concurrently")

    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        self._identity(plan, operation_id)
        async with get_async_db_session() as session:
            row = await self._load(
                session,
                plan,
                for_update=True,
            )
        if (
            row is None
            or row.permission_projection_version != plan.expected_version
            or row.permission_projection_state != DEPARTMENT_PROJECTION_PROJECTING
            or row.permission_projection_operation_id != operation_id
        ):
            raise PermissionPublishNotReadyError(
                msg=("Department business mutation is not durably bound to this projection")
            )

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool:
        self._identity(plan, operation_id)
        async with get_async_db_session() as session:
            row = await self._load(session, plan)
        return bool(
            row is not None
            and row.permission_projection_version == plan.expected_version
            and row.permission_projection_state == DEPARTMENT_PROJECTION_PROJECTING
            and row.permission_projection_operation_id == operation_id
        )

    async def fail_closed(
        self,
        plan: ProjectionPlan,
        reason: str,
    ) -> None:
        del reason
        department_id = self._identity(plan)
        async with get_async_db_session() as session:
            async with session.begin():
                await session.execute(
                    update(Department)
                    .where(
                        Department.id == department_id,
                        Department.tenant_id == plan.tenant_id,
                        Department.permission_projection_version == plan.expected_version,
                        Department.permission_projection_state == DEPARTMENT_PROJECTION_PROJECTING,
                    )
                    .values(
                        permission_projection_state=(DEPARTMENT_PROJECTION_FAILED_CLOSED),
                    )
                )

    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        department_id = self._identity(plan, operation_id)
        async with get_async_db_session() as session:
            async with session.begin():
                result = await session.execute(
                    update(Department)
                    .where(
                        Department.id == department_id,
                        Department.tenant_id == plan.tenant_id,
                        Department.permission_projection_version == plan.expected_version,
                        Department.permission_projection_state == DEPARTMENT_PROJECTION_PROJECTING,
                        Department.permission_projection_operation_id == operation_id,
                    )
                    .values(
                        permission_projection_version=plan.target_version,
                        permission_projection_state=(DEPARTMENT_PROJECTION_CURRENT),
                        permission_projection_operation_id=operation_id,
                    )
                )
                if result.rowcount:
                    return
                row = await self._load(session, plan, for_update=True)
                if (
                    row is not None
                    and row.permission_projection_version == plan.target_version
                    and row.permission_projection_state == DEPARTMENT_PROJECTION_CURRENT
                    and row.permission_projection_operation_id == operation_id
                ):
                    return
                raise PermissionPublishNotReadyError(msg=("Department projection binding changed before finalize"))

    @staticmethod
    async def _load(
        session: AsyncSession,
        plan: ProjectionPlan,
        *,
        for_update: bool = False,
    ) -> Department | None:
        statement = select(Department).where(
            Department.id == int(plan.scope_key),
            Department.tenant_id == plan.tenant_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await session.execute(statement)).scalars().first()

    @staticmethod
    def _identity(
        plan: ProjectionPlan,
        operation_id: int | None = None,
    ) -> int:
        if (
            plan.scope_type != "department"
            or not plan.scope_key.isdigit()
            or int(plan.scope_key) <= 0
            or plan.tenant_id <= 0
            or plan.expected_version < 0
            or plan.target_version != plan.expected_version + 1
            or (operation_id is not None and operation_id <= 0)
        ):
            raise PermissionPublishNotReadyError(msg="Invalid department projection scope")
        return int(plan.scope_key)


class DepartmentProjectionRuntime:
    """Coordinate business transaction binding with the permission ledger."""

    def __init__(
        self,
        *,
        ledger: DepartmentProjectionLedgerPort,
        scope: SqlDepartmentProjectionScope,
    ) -> None:
        self._ledger = ledger
        self.scope = scope
        self.handler = F048DepartmentChangeHandler(projection=ledger)

    async def prepare(
        self,
        plan: ProjectionPlan,
    ) -> PreparedDepartmentProjection:
        operation = await self._ledger.prepare(plan)
        if operation.id is None:
            raise PermissionPublishNotReadyError(msg="Department projection operation has no durable ID")
        return PreparedDepartmentProjection(
            plan=plan,
            operation_id=int(operation.id),
        )

    async def bind(
        self,
        session: AsyncSession,
        prepared: PreparedDepartmentProjection,
    ) -> None:
        await self.scope.bind(
            session,
            prepared.plan,
            prepared.operation_id,
        )

    async def execute(
        self,
        prepared: PreparedDepartmentProjection,
    ) -> ProjectionOutcome:
        return await self._ledger.execute(prepared.plan)

    async def reconcile_operation(
        self,
        operation_id: int,
    ) -> ProjectionOutcome:
        return await self._ledger.reconcile_operation(operation_id)

    async def abandon(
        self,
        prepared: PreparedDepartmentProjection,
        error: Exception,
    ) -> None:
        await self._ledger.abandon_prepared(prepared.plan, error)


_scope = SqlDepartmentProjectionScope()
DEPARTMENT_PROJECTION_RUNTIME_CONTEXT = "department_projection_runtime"


def get_department_projection_scope() -> SqlDepartmentProjectionScope:
    return _scope


def register_department_projection_runtime_context() -> None:
    """Register department projection without constructing it eagerly."""

    try:
        app_context.get_context(DEPARTMENT_PROJECTION_RUNTIME_CONTEXT)
        return
    except KeyError:
        pass

    async def initialize() -> DepartmentProjectionRuntime:
        from bisheng.permission.application.process_runtime import get_f048_process_runtime

        process_runtime = await get_f048_process_runtime()
        components = getattr(process_runtime, "components", process_runtime)
        ledger = getattr(components, "projection", None)
        if ledger is None:
            raise PermissionPublishNotReadyError(msg="Permission projection ledger is unavailable")
        return DepartmentProjectionRuntime(
            ledger=ledger,
            scope=_scope,
        )

    app_context.register_context(
        FunctionContextManager(
            name=DEPARTMENT_PROJECTION_RUNTIME_CONTEXT,
            init_func=initialize,
        ),
        dependencies=["permission_runtime"],
        lazy=True,
    )


async def get_department_projection_runtime() -> DepartmentProjectionRuntime:
    return await app_context.async_get_instance(DEPARTMENT_PROJECTION_RUNTIME_CONTEXT)
