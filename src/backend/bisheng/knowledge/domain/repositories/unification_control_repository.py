"""Bounded original creator, organization and quota facts for M2.

These reads confer no authority and do not enforce quota or classify historical
memberships. The caller owns the native transaction and runs the original four
tenant probes and SPACE parent gate before consuming individual tenant pages.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    strict_tenant_filter,
)
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.knowledge.domain.repositories.unification_inventory_repository import InventoryPage
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
    _current,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.user.domain.models.user import User

TENANT_COLUMNS = (
    "id",
    "status",
    "parent_tenant_id",
    "root_dept_id",
    "share_default_to_children",
    "quota_config",
    "update_time",
)
MEMBERSHIP_COLUMNS = (
    "id",
    "user_id",
    "tenant_id",
    "is_default",
    "status",
    "is_active",
    "last_access_time",
    "join_time",
)
DEPARTMENT_COLUMNS = (
    "id",
    "tenant_id",
    "parent_id",
    "path",
    "status",
    "is_deleted",
    "is_tenant_root",
    "mounted_tenant_id",
    "update_time",
)
ROLE_COLUMNS = (
    "id",
    "tenant_id",
    "role_type",
    "department_id",
    "quota_config",
    "knowledge_space_file_limit",
    "update_time",
)
USER_ROLE_KEY = ("user_id", "role_id", "id")
USER_ROLE_COLUMNS = (*USER_ROLE_KEY, "tenant_id", "create_time", "update_time")


def _blocked(reason, **facts):
    raise KnowledgeOperationPlanConflictError(reason=f"unification_control_{reason}", **facts)


def _scope(session):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
    ):
        _blocked("native_transaction_scope_required")
    return tenant


def _positive(value):
    return type(value) is int and value > 0


def _bounds(after_id, limit):
    if type(limit) is not int or not 1 <= limit <= 200 or (after_id is not None and not _positive(after_id)):
        _blocked("invalid_page")


def _ids(values):
    if type(values) is not tuple or any(not _positive(ident) for ident in values):
        _blocked("invalid_exact_ids")
    unique = tuple(dict.fromkeys(values))
    if len(unique) > 500:
        _blocked("invalid_exact_ids")
    return unique


def _values(row, columns):
    values = {name: row[name] for name in columns}
    if "quota_config" in values:
        try:
            quota = deepcopy(values["quota_config"])
            json.dumps(quota, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            _blocked("invalid_original_json")
        values["quota_config"] = quota
    return values


@dataclass(frozen=True, slots=True)
class TenantControlFact:
    id: int
    status: str
    parent_tenant_id: int | None
    root_dept_id: int | None
    share_default_to_children: int
    quota_config: dict | None = field(repr=False)
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class MembershipRow:
    id: int
    user_id: int
    tenant_id: int
    is_default: int
    status: str
    is_active: int | None
    last_access_time: datetime | None
    join_time: datetime | None


@dataclass(frozen=True, slots=True)
class DepartmentRow:
    id: int
    tenant_id: int
    parent_id: int | None
    path: str
    status: str
    is_deleted: int
    is_tenant_root: int
    mounted_tenant_id: int | None
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class RoleRow:
    id: int
    tenant_id: int
    role_type: str
    department_id: int | None
    quota_config: dict | None = field(repr=False)
    knowledge_space_file_limit: int | None
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class UserRoleRow:
    user_id: int
    role_id: int
    id: int
    tenant_id: int
    create_time: datetime | None
    update_time: datetime | None


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ControlPage(Generic[T]):
    items: tuple[T, ...]
    next_after: tuple[int, int, int] | None


@dataclass(frozen=True, slots=True)
class CreatorFact:
    user_id: int
    exists: bool
    delete: int | None


@dataclass(frozen=True, slots=True)
class RoleFact:
    id: int
    exists: bool
    tenant_id: int | None
    role_type: str | None
    department_id: int | None
    quota_config: dict | None = field(repr=False)
    knowledge_space_file_limit: int | None
    update_time: datetime | None


class UnificationControlRepository:
    @staticmethod
    async def _read(session, statement, *, global_facts=False):
        _scope(session)
        with session.no_autoflush, strict_tenant_filter():
            try:
                if global_facts:
                    with bypass_tenant_filter():
                        return tuple((await session.execute(statement)).mappings())
                return tuple((await session.execute(statement)).mappings())
            except (TypeError, ValueError):
                _blocked("invalid_original_json")

    async def aget_tenant(self, session: AsyncSession) -> TenantControlFact:
        tenant = _scope(session)
        rows = await self._read(
            session, select(*(getattr(Tenant, name) for name in TENANT_COLUMNS)).where(Tenant.id == tenant)
        )
        if not rows:
            _blocked("current_tenant_missing", id=tenant)
        return TenantControlFact(**_values(rows[0], TENANT_COLUMNS))

    async def _page(self, session, model, columns, row_type, after_id, limit):
        tenant = _scope(session)
        _bounds(after_id, limit)
        query = select(*(getattr(model, name) for name in columns))
        if model is UserTenant:
            # This membership table is deliberately excluded from the C3 listener.
            query = query.where(UserTenant.tenant_id == tenant)
        if after_id is not None:
            query = query.where(model.id > after_id)
        rows = await self._read(session, query.order_by(model.id).limit(limit + 1))
        if any(row["tenant_id"] != tenant for row in rows):
            _blocked("page_tenant_mismatch")
        items = tuple(row_type(**_values(row, columns)) for row in rows[:limit])
        return InventoryPage(items, items[-1].id if len(rows) > limit else None)

    async def alist_memberships(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[MembershipRow]:
        return await self._page(session, UserTenant, MEMBERSHIP_COLUMNS, MembershipRow, after_id, limit)

    async def alist_departments(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[DepartmentRow]:
        return await self._page(session, Department, DEPARTMENT_COLUMNS, DepartmentRow, after_id, limit)

    async def alist_roles(
        self, session: AsyncSession, *, after_id: int | None = None, limit: int = 200
    ) -> InventoryPage[RoleRow]:
        return await self._page(session, Role, ROLE_COLUMNS, RoleRow, after_id, limit)

    async def alist_user_roles(
        self, session: AsyncSession, *, after_key: tuple[int, int, int] | None = None, limit: int = 200
    ) -> ControlPage[UserRoleRow]:
        tenant = _scope(session)
        _bounds(None, limit)
        if after_key is not None and (
            type(after_key) is not tuple or len(after_key) != 3 or any(not _positive(ident) for ident in after_key)
        ):
            _blocked("invalid_page_key")
        query = select(*(getattr(UserRole, name) for name in USER_ROLE_COLUMNS))
        if after_key is not None:
            user, role, ident = after_key
            query = query.where(
                or_(
                    UserRole.user_id > user,
                    and_(UserRole.user_id == user, UserRole.role_id > role),
                    and_(UserRole.user_id == user, UserRole.role_id == role, UserRole.id > ident),
                )
            )
        rows = await self._read(
            session, query.order_by(UserRole.user_id, UserRole.role_id, UserRole.id).limit(limit + 1)
        )
        for row in rows:
            if row["tenant_id"] != tenant or any(not _positive(row[name]) for name in USER_ROLE_KEY):
                _blocked("invalid_user_role_key")
        items = tuple(UserRoleRow(**_values(row, USER_ROLE_COLUMNS)) for row in rows[:limit])
        next_after = tuple(getattr(items[-1], name) for name in USER_ROLE_KEY) if len(rows) > limit else None
        return ControlPage(items, next_after)

    async def ainspect_users(self, session: AsyncSession, *, user_ids: tuple[int, ...]) -> tuple[CreatorFact, ...]:
        _scope(session)
        ids = _ids(user_ids)
        source = User.__table__.alias("m2_exact_creator")
        facts = {}
        for offset in range(0, len(ids), 200):
            rows = await self._read(
                session,
                select(source.c.user_id, source.c.delete).where(source.c.user_id.in_(ids[offset : offset + 200])),
                global_facts=True,
            )
            facts.update((row["user_id"], CreatorFact(row["user_id"], True, row["delete"])) for row in rows)
        return tuple(facts[ident] if ident in facts else CreatorFact(ident, False, None) for ident in ids)

    async def ainspect_roles(self, session: AsyncSession, *, role_ids: tuple[int, ...]) -> tuple[RoleFact, ...]:
        _scope(session)
        ids = _ids(role_ids)
        source = Role.__table__.alias("m2_exact_role")
        facts = {}
        for offset in range(0, len(ids), 200):
            rows = await self._read(
                session,
                select(*(source.c[name] for name in ROLE_COLUMNS)).where(source.c.id.in_(ids[offset : offset + 200])),
                global_facts=True,
            )
            facts.update((row["id"], RoleFact(**_values(row, ROLE_COLUMNS), exists=True)) for row in rows)
        return tuple(
            facts[ident] if ident in facts else RoleFact(ident, False, None, None, None, None, None, None)
            for ident in ids
        )

    async def avalidate_global_integrity(self, session: AsyncSession) -> None:
        tenant_id = _scope(session)
        transaction = TransactionIdentity.capture(session)
        for model in (UserTenant, Department):
            source = model.__table__.alias("m2_control_row")
            tenant = Tenant.__table__.alias("m2_control_tenant")
            keys = ("id",)
            _current(session, tenant_id, transaction)
            rows = await self._read(
                session,
                select(*(source.c[name] for name in keys))
                .outerjoin(tenant, tenant.c.id == source.c.tenant_id)
                .where(or_(source.c.tenant_id.is_(None), source.c.tenant_id <= 0, tenant.c.id.is_(None)))
                .limit(1),
                global_facts=True,
            )
            _current(session, tenant_id, transaction)
            if rows:
                _blocked(f"invalid_tenant_{model.__tablename__}", **dict(rows[0]))
        _current(session, tenant_id, transaction)
        await UnificationSpaceMembershipRepository().avalidate_global_integrity(session)
        _current(session, tenant_id, transaction)
