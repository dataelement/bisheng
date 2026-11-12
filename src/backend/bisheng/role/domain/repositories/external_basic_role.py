"""受管基础模板的 SQL、操作栅栏及同事务变更。"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    strict_tenant_filter,
    tenant_execution_scope,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.tenant import Tenant
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.models.external_basic_role import RoleExternalBasicRole

BASIC_MENUS = frozenset(("admin", "build", "create_workflow"))
MENU_DIGEST = sha256("\n".join(sorted(BASIC_MENUS)).encode()).hexdigest()


@dataclass(frozen=True)
class BasicRoleOperation:
    connection_id: str
    tenant_id: int
    operation_id: str
    fence: int
    template_revision: int


@dataclass(frozen=True)
class BasicRoleReceipt:
    connection_id: str
    tenant_id: int
    role_id: int | None
    template_revision: int
    state: str
    local_policy_revision: int
    fence: int


class RoleExternalBasicRoleRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @asynccontextmanager
    async def session(self, tenant_id):
        if type(tenant_id) is not int or tenant_id <= 1 or get_current_tenant_id() not in (1, tenant_id):
            raise KunlianBindingConflictError()
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with self.session_factory() as session:
                try:
                    async with session.begin():
                        yield session
                except IntegrityError:
                    raise KunlianBindingConflictError() from None
                except SQLAlchemyError:
                    raise KunlianDependencyUnavailableError() from None

    @staticmethod
    async def state(session, connection_id):
        return (
            await session.exec(
                select(RoleExternalBasicRole)
                .where(RoleExternalBasicRole.connection_id == connection_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()

    @staticmethod
    def receipt(row):
        return BasicRoleReceipt(
            row.connection_id,
            row.tenant_id,
            row.role_id,
            row.template_revision,
            row.state,
            row.local_policy_revision,
            row.fence,
        )

    @staticmethod
    def suspend(row):
        row.state = "SUSPENDED"
        row.local_blocked = True
        row.local_policy_revision += 1
        row.template_revision += 1
        row.fence += 1
        row.operation_id = None
        row.update_time = datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    async def intact(session, row):
        role = (await session.exec(select(Role).where(Role.id == row.role_id).with_for_update())).first()
        values = (await session.exec(select(RoleAccess).where(RoleAccess.role_id == row.role_id))).all()
        return (
            role is not None
            and role.tenant_id == row.tenant_id
            and role.role_type == "tenant"
            and role.department_id is None
            and role.id not in (1, 2)
            and {(r.type, r.third_id) for r in values} == {(99, key) for key in BASIC_MENUS}
        )

    async def reserve(self, connection_id, tenant_id):
        if not isinstance(connection_id, str) or not connection_id.strip() or len(connection_id) > 64:
            raise KunlianBindingConflictError()
        result = None
        async with self.session(tenant_id) as session:
            tenant = (await session.exec(select(Tenant).where(Tenant.id == tenant_id))).first()
            if tenant is None or tenant.status != "active" or tenant.parent_tenant_id != 1:
                raise KunlianIdentityUnavailableError()
            row = await self.state(session, connection_id)
            if row is None:
                row = RoleExternalBasicRole(connection_id=connection_id, tenant_id=tenant_id, menu_digest=MENU_DIGEST)
            if row.state == "APPLIED" and not await self.intact(session, row):
                self.suspend(row)
            if not row.local_blocked and row.state != "SUSPENDED":
                if row.operation_id is None:
                    row.operation_id = str(uuid4())
                    row.fence += 1
                    row.payload_digest = MENU_DIGEST
                    row.state = "PENDING"
                result = BasicRoleOperation(
                    connection_id, tenant_id, row.operation_id, row.fence, row.template_revision
                )
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
        if result is None:
            raise KunlianIdentityUnavailableError()
        return result

    @staticmethod
    def check_operation(row, operation):
        if row is None:
            raise KunlianBindingConflictError()
        if row.local_blocked:
            raise KunlianIdentityUnavailableError()
        if (row.operation_id, row.fence, row.template_revision, row.payload_digest) != (
            operation.operation_id,
            operation.fence,
            operation.template_revision,
            MENU_DIGEST,
        ):
            raise KunlianBindingConflictError()

    async def apply(self, operation):
        refused = False
        result = None
        async with self.session(operation.tenant_id) as session:
            row = await self.state(session, operation.connection_id)
            self.check_operation(row, operation)
            if row.state == "APPLIED":
                if not await self.intact(session, row):
                    self.suspend(row)
                    row.update_time = datetime.now(UTC).replace(tzinfo=None)
                    session.add(row)
                    refused = True
            else:
                role = None
                if row.role_id is not None:
                    role = (await session.exec(select(Role).where(Role.id == row.role_id).with_for_update())).first()
                if role is None:
                    role = Role(
                        role_name="昆联工作流基础_" + sha256(row.connection_id.encode()).hexdigest()[:12],
                        tenant_id=row.tenant_id,
                        role_type="tenant",
                        create_user=None,
                    )
                    session.add(role)
                    await session.flush()
                    if role.id in (1, 2):
                        raise KunlianBindingConflictError()
                if role.role_type != "tenant" or role.tenant_id != row.tenant_id or role.department_id is not None:
                    raise KunlianBindingConflictError()
                row.role_id = role.id
                await self.replace_menus(session, role.id, row.tenant_id, BASIC_MENUS)
                row.state = "APPLIED"
                row.applied_operation_id, row.applied_fence = row.operation_id, row.fence
                row.applied_template_revision = row.template_revision
                row.menu_digest = MENU_DIGEST
                row.update_time = datetime.now(UTC).replace(tzinfo=None)
                session.add(row)
            if not refused:
                result = self.receipt(row)
        if refused:
            raise KunlianIdentityUnavailableError()
        return result

    @staticmethod
    async def replace_menus(session, role_id, tenant_id, menu_ids):
        rows = (
            await session.exec(
                select(RoleAccess)
                .where(RoleAccess.role_id == role_id, RoleAccess.type == AccessType.WEB_MENU.value)
                .with_for_update()
            )
        ).all()
        for row in rows:
            await session.delete(row)
        session.add_all([RoleAccess(role_id=role_id, third_id=key, type=99, tenant_id=tenant_id) for key in menu_ids])

    async def set_policy(self, connection_id, tenant_id, *, expected_revision, enabled):
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 1:
            raise KunlianBindingConflictError()
        async with self.session(tenant_id) as session:
            row = await self.state(session, connection_id)
            if row is None or row.local_policy_revision != expected_revision:
                raise KunlianBindingConflictError()
            row.local_policy_revision += 1
            row.template_revision += 1
            row.fence += 1
            row.operation_id = None
            row.local_blocked = not enabled
            row.state = "PENDING" if enabled else "SUSPENDED"
            if not enabled and row.role_id:
                await self.replace_menus(session, row.role_id, tenant_id, ())
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            return row.local_policy_revision

    @asynccontextmanager
    async def locked_template(self, session, connection_id, tenant_id, *, expected_revision=None, require_applied=True):
        if get_current_tenant_id() != tenant_id:
            raise KunlianBindingConflictError()
        row = await self.state(session, connection_id)
        valid = row is not None and not row.local_blocked and row.state == "APPLIED" and await self.intact(session, row)
        if not valid:
            if require_applied:
                raise KunlianIdentityUnavailableError()
            yield replace(self.receipt(row), state="SUSPENDED") if row else None
            return
        if expected_revision is not None and row.template_revision != expected_revision:
            raise KunlianBindingConflictError()
        # 调用方只能获得不可变值对象, 锁由同一 SQL 事务持有。
        yield self.receipt(row)

    async def find_managed(self, role_ids):
        if not role_ids:
            return ()
        with tenant_execution_scope(1), strict_tenant_filter(), bypass_tenant_filter():
            async with self.session_factory() as session:
                rows = (
                    await session.exec(
                        select(RoleExternalBasicRole).where(RoleExternalBasicRole.role_id.in_(set(role_ids)))
                    )
                ).all()
                return tuple(self.receipt(row) for row in rows)

    async def mutate(self, reference, *, fields=None, menus=None, remove=False):
        if menus is not None and not set(menus).issubset(BASIC_MENUS):
            raise KunlianBindingConflictError()
        fields = fields or {}
        allowed = {"role_name", "remark", "quota_config", "department_id", "knowledge_space_file_limit"}
        if set(fields) - allowed:
            raise KunlianBindingConflictError()
        async with self.session(reference.tenant_id) as session:
            row = await self.state(session, reference.connection_id)
            if row is None or row.role_id != reference.role_id:
                raise KunlianBindingConflictError()
            role = (await session.exec(select(Role).where(Role.id == reference.role_id).with_for_update())).first()
            if role is None:
                self.suspend(row)
            elif remove:
                self.suspend(row)
                # 先经原过滤器选取并锁定具体行; 不依赖 bulk DELETE 自动注入租户。
                members = (
                    await session.exec(select(UserRole).where(UserRole.role_id == role.id).with_for_update())
                ).all()
                access = (
                    await session.exec(select(RoleAccess).where(RoleAccess.role_id == role.id).with_for_update())
                ).all()
                for record in [*members, *access]:
                    await session.delete(record)
                await session.delete(role)
            else:
                if row.local_blocked and menus:
                    raise KunlianIdentityUnavailableError()
                if menus is not None:
                    await self.replace_menus(session, role.id, row.tenant_id, set(menus))
                    if set(menus) != BASIC_MENUS:
                        self.suspend(row)
                if fields.get("department_id") is not None:
                    self.suspend(row)
                for key, value in fields.items():
                    setattr(role, key, value)
                session.add(role)
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            return True
