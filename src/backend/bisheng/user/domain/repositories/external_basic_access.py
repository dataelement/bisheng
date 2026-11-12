"""用户资格与实际 UserRole 同事务提交, 不接管原资料投影。"""

import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
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
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.role.application.external_basic_role import BasicRoleReceipt
from bisheng.user.domain.models.external_basic_access import UserExternalBasicAccess
from bisheng.user.domain.models.external_identity_projection import UserExternalIdentityProjection
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from bisheng.user.domain.repositories.external_identity_projection import ExternalShadowReceipt


@dataclass(frozen=True)
class BasicAccessCommand:
    connection_id: str
    identity_key: str
    tenant_id: int
    user_id: int
    projection: ExternalShadowReceipt
    template: BasicRoleReceipt

    @property
    def payload_digest(self):
        return sha256(
            json.dumps(
                [
                    self.connection_id,
                    self.identity_key,
                    self.tenant_id,
                    self.user_id,
                    self.projection.operation_id,
                    self.projection.fence,
                    self.projection.source_revision,
                    self.template.role_id,
                    self.template.template_revision,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


@dataclass(frozen=True)
class BasicAccessOperation:
    connection_id: str
    identity_key: str
    tenant_id: int
    operation_id: str
    fence: int
    payload_digest: str


@dataclass(frozen=True)
class BasicAccessReceipt:
    user_id: int
    role_id: int | None
    state: str
    effective: bool
    local_blocked: bool
    local_policy_revision: int
    fence: int


@dataclass(frozen=True)
class RoleMutationReceipt:
    before_roles: tuple[int, ...]
    after_roles: tuple[int, ...]


class UserExternalBasicAccessRepository:
    def __init__(self, session_factory=get_async_db_session, *, role_port=None):
        if role_port is None:
            from bisheng.role.application.external_basic_role import (
                ExternalBasicRoleApplication,
                RoleExternalBasicRoleRepository,
            )

            role_port = ExternalBasicRoleApplication(RoleExternalBasicRoleRepository(session_factory))
        self.session_factory = session_factory
        self.role_port = role_port

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
    async def source(session, identity_key, user_id, tenant_id, *, receipt=None, require_active=True):
        with tenant_execution_scope(1), strict_tenant_filter():
            projection = (
                await session.exec(
                    select(UserExternalIdentityProjection)
                    .where(UserExternalIdentityProjection.identity_key == identity_key)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).first()
        user = (await session.exec(select(User).where(User.user_id == user_id).with_for_update())).first()
        if (
            projection is None
            or projection.user_id != user_id
            or user is None
            or user.source != "kunlian"
            or user.external_id != "kunlian:" + identity_key
        ):
            raise KunlianBindingConflictError()
        if require_active and (
            user.delete != 0
            or user.disable_source is not None
            or projection.fence != projection.applied_fence
            or not projection.applied_operation_id
            or projection.operation_id != projection.applied_operation_id
        ):
            raise KunlianIdentityUnavailableError()
        if receipt is not None and (receipt.user_id, receipt.operation_id, receipt.fence, receipt.source_revision) != (
            user_id,
            projection.applied_operation_id,
            projection.applied_fence,
            projection.applied_source_revision,
        ):
            raise KunlianBindingConflictError()
        tenant = (await session.exec(select(Tenant).where(Tenant.id == tenant_id))).first()
        membership = (
            await session.exec(select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.is_active == 1))
        ).first()
        if (
            tenant is None
            or tenant.parent_tenant_id != 1
            or membership is None
            or membership.tenant_id != tenant_id
            or (require_active and (tenant.status != "active" or membership.status != "active"))
        ):
            raise KunlianIdentityUnavailableError()
        return projection

    @staticmethod
    async def state(session, connection_id, identity_key, *, lock=True):
        statement = (
            select(UserExternalBasicAccess)
            .where(
                UserExternalBasicAccess.connection_id == connection_id,
                UserExternalBasicAccess.identity_key == identity_key,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await session.exec(statement)).first()

    @staticmethod
    async def relation(session, user_id, role_id):
        return (
            await session.exec(
                select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id).with_for_update()
            )
        ).first()

    @staticmethod
    def block(row):
        row.local_blocked = True
        row.state = "BLOCKED"
        row.local_policy_revision += 1
        row.fence += 1
        row.operation_id = None
        row.update_time = datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def check(row, operation):
        if row is None:
            raise KunlianBindingConflictError()
        if row.local_blocked:
            raise KunlianIdentityUnavailableError()
        if (row.operation_id, row.fence, row.payload_digest) != (
            operation.operation_id,
            operation.fence,
            operation.payload_digest,
        ):
            raise KunlianBindingConflictError()

    @staticmethod
    def validate(command):
        if (
            not isinstance(command, BasicAccessCommand)
            or not isinstance(command.projection, ExternalShadowReceipt)
            or not isinstance(command.template, BasicRoleReceipt)
        ):
            raise KunlianBindingConflictError()
        if (
            not isinstance(command.connection_id, str)
            or not command.connection_id.strip()
            or len(command.connection_id) > 64
            or not isinstance(command.identity_key, str)
            or len(command.identity_key) != 64
            or any(c not in "0123456789abcdef" for c in command.identity_key)
            or command.template.connection_id != command.connection_id
            or command.template.tenant_id != command.tenant_id
            or command.template.state != "APPLIED"
            or command.user_id != command.projection.user_id
        ):
            raise KunlianBindingConflictError()

    async def reserve(self, command):
        self.validate(command)
        result = None
        async with self.session(command.tenant_id) as session:
            async with self.role_port.lock_template(
                session, command.connection_id, command.tenant_id, expected_revision=command.template.template_revision
            ) as template:
                if template.role_id != command.template.role_id:
                    raise KunlianBindingConflictError()
                await self.source(
                    session, command.identity_key, command.user_id, command.tenant_id, receipt=command.projection
                )
                row = await self.state(session, command.connection_id, command.identity_key)
                if row is None:
                    row = UserExternalBasicAccess(
                        connection_id=command.connection_id,
                        identity_key=command.identity_key,
                        tenant_id=command.tenant_id,
                        user_id=command.user_id,
                    )
                if row.user_id != command.user_id:
                    raise KunlianBindingConflictError()
                relation = await self.relation(session, command.user_id, row.role_id) if row.role_id else None
                if (
                    row.state == "APPLIED"
                    and relation is None
                    and row.role_id == template.role_id
                    and row.template_revision == template.template_revision
                ):
                    self.block(row)
                if not row.local_blocked:
                    # 不能把没有来源回执的现有相同关系当作本次自动关系。
                    if row.role_id is None and await self.relation(session, command.user_id, template.role_id):
                        raise KunlianBindingConflictError()
                    if row.payload_digest != command.payload_digest or row.operation_id is None:
                        row.fence += 1
                        row.operation_id = str(uuid4())
                        row.payload_digest = command.payload_digest
                        row.user_projection_operation_id = command.projection.operation_id
                        row.user_projection_fence = command.projection.fence
                        row.user_projection_revision = command.projection.source_revision
                        row.template_revision = template.template_revision
                        row.role_id = template.role_id
                        row.state = "PENDING"
                    result = BasicAccessOperation(
                        row.connection_id,
                        row.identity_key,
                        row.tenant_id,
                        row.operation_id,
                        row.fence,
                        row.payload_digest,
                    )
                row.update_time = datetime.now(UTC).replace(tzinfo=None)
                session.add(row)
        if result is None:
            raise KunlianIdentityUnavailableError()
        return result

    async def apply(self, command, operation):
        self.validate(command)
        if (operation.connection_id, operation.identity_key, operation.tenant_id, operation.payload_digest) != (
            command.connection_id,
            command.identity_key,
            command.tenant_id,
            command.payload_digest,
        ):
            raise KunlianBindingConflictError()
        async with self.session(command.tenant_id) as session:
            async with self.role_port.lock_template(
                session, command.connection_id, command.tenant_id, expected_revision=command.template.template_revision
            ) as template:
                if template.role_id != command.template.role_id:
                    raise KunlianBindingConflictError()
                await self.source(
                    session, command.identity_key, command.user_id, command.tenant_id, receipt=command.projection
                )
                row = await self.state(session, command.connection_id, command.identity_key)
                self.check(row, operation)
                if row.user_id != command.user_id or row.role_id != template.role_id:
                    raise KunlianBindingConflictError()
                relation = await self.relation(session, row.user_id, row.role_id)
                if row.state == "APPLIED" and relation is None:
                    self.block(row)
                    row.update_time = datetime.now(UTC).replace(tzinfo=None)
                    session.add(row)
                    result = None
                else:
                    if relation is None:
                        session.add(UserRole(user_id=row.user_id, role_id=row.role_id, tenant_id=row.tenant_id))
                    row.state = "APPLIED"
                    row.applied_operation_id, row.applied_fence = row.operation_id, row.fence
                    row.update_time = datetime.now(UTC).replace(tzinfo=None)
                    session.add(row)
                    await session.flush()
                    result = self.receipt(row, True)
        if result is None:
            raise KunlianIdentityUnavailableError()
        return result

    @staticmethod
    def receipt(row, effective):
        return BasicAccessReceipt(
            row.user_id, row.role_id, row.state, effective, row.local_blocked, row.local_policy_revision, row.fence
        )

    async def read(self, connection_id, identity_key, tenant_id):
        async with self.session(tenant_id) as session:
            async with self.role_port.lock_template(
                session, connection_id, tenant_id, require_applied=False
            ) as template:
                candidate = await self.state(session, connection_id, identity_key, lock=False)
                if candidate is None:
                    raise KunlianIdentityUnavailableError()
                projection = await self.source(session, identity_key, candidate.user_id, tenant_id)
                row = await self.state(session, connection_id, identity_key)
                relation = await self.relation(session, row.user_id, row.role_id)
                effective = bool(
                    not row.local_blocked
                    and row.state == "APPLIED"
                    and template
                    and template.state == "APPLIED"
                    and template.template_revision == row.template_revision
                    and template.role_id == row.role_id
                    and relation
                    and row.user_projection_operation_id == projection.applied_operation_id
                    and row.user_projection_fence == projection.applied_fence
                    and row.user_projection_revision == projection.applied_source_revision
                    and row.fence == row.applied_fence
                    and row.operation_id == row.applied_operation_id
                )
                return self.receipt(row, effective)

    async def set_policy(self, connection_id, identity_key, tenant_id, *, expected_revision, enabled):
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 1:
            raise KunlianBindingConflictError()
        async with self.session(tenant_id) as session:
            async with self.role_port.lock_template(session, connection_id, tenant_id, require_applied=False):
                candidate = await self.state(session, connection_id, identity_key, lock=False)
                if candidate is None:
                    raise KunlianBindingConflictError()
                await self.source(session, identity_key, candidate.user_id, tenant_id, require_active=enabled)
                row = await self.state(session, connection_id, identity_key)
                if row is None or row.local_policy_revision != expected_revision:
                    raise KunlianBindingConflictError()
                row.local_policy_revision += 1
                row.fence += 1
                row.operation_id = None
                row.local_blocked = not enabled
                row.state = "PENDING" if enabled else "BLOCKED"
                if not enabled and row.role_id:
                    relations = (
                        await session.exec(
                            select(UserRole)
                            .where(UserRole.user_id == row.user_id, UserRole.role_id == row.role_id)
                            .with_for_update()
                        )
                    ).all()
                    for relation in relations:
                        await session.delete(relation)
                row.update_time = datetime.now(UTC).replace(tzinfo=None)
                session.add(row)
                return row.local_policy_revision

    async def apply_role_mutation(self, user_id, *, add_ids, delete_ids, actor):
        add_ids, delete_ids = set(add_ids), set(delete_ids)
        # 只按确切用户读取来源归属, 目标租户不能来自浏览器参数。
        with tenant_execution_scope(1), strict_tenant_filter(), bypass_tenant_filter():
            async with self.session_factory() as session:
                candidates = (
                    await session.exec(
                        select(UserExternalBasicAccess).where(UserExternalBasicAccess.user_id == user_id)
                    )
                ).all()
        managed = await self.role_port.find_managed_templates(add_ids | delete_ids)
        if not candidates and not managed:
            return None
        if add_ids & delete_ids or 1 in add_ids:
            raise KunlianBindingConflictError()
        # 预留角色的人工追加一律走显式来源恢复, 不接受 role_add 重新授予。
        if any(row.role_id in add_ids for row in managed):
            raise KunlianBindingConflictError()
        tenants = {row.tenant_id for row in candidates} | {row.tenant_id for row in managed}
        if len(tenants) != 1 or not candidates:
            raise KunlianBindingConflictError()
        tenant_id = tenants.pop()
        if not actor.is_admin() and actor.tenant_id != tenant_id:
            raise KunlianBindingConflictError()
        async with self.session(tenant_id) as session, AsyncExitStack() as locks:
            connections = sorted({row.connection_id for row in candidates} | {row.connection_id for row in managed})
            for connection in connections:
                await locks.enter_async_context(
                    self.role_port.lock_template(session, connection, tenant_id, require_applied=False)
                )
            # 所有入口保持模板 -> 原用户投影 -> 资格 -> 实际角色关系的锁顺序。
            for row in sorted(candidates, key=lambda r: r.identity_key):
                await self.source(session, row.identity_key, user_id, tenant_id, require_active=False)
            states = []
            for row in sorted(candidates, key=lambda r: (r.connection_id, r.identity_key)):
                current = await self.state(session, row.connection_id, row.identity_key)
                if current is None or current.user_id != user_id:
                    raise KunlianBindingConflictError()
                states.append(current)
            relations = (
                await session.exec(select(UserRole).where(UserRole.user_id == user_id).with_for_update())
            ).all()
            before = {r.role_id for r in relations}
            after = (before | add_ids) - delete_ids
            if add_ids:
                with bypass_tenant_filter():
                    roles = (await session.exec(select(Role).where(Role.id.in_(add_ids)))).all()
                if {r.id for r in roles} != add_ids or any(
                    r.tenant_id != tenant_id and r.role_type != "global" for r in roles
                ):
                    raise KunlianBindingConflictError()
            for row in states:
                if row.role_id in delete_ids or (row.state == "APPLIED" and row.role_id not in before):
                    self.block(row)
                    row.update_time = datetime.now(UTC).replace(tzinfo=None)
                    session.add(row)
            for relation in relations:
                if relation.role_id in delete_ids:
                    await session.delete(relation)
            session.add_all([UserRole(user_id=user_id, role_id=rid, tenant_id=tenant_id) for rid in add_ids - before])
            session.add(
                AuditLog(
                    operator_id=actor.user_id,
                    operator_name=getattr(actor, "user_name", None),
                    group_ids=[],
                    system_id="system",
                    event_type="update_user_role",
                    object_type="user",
                    object_id=str(user_id),
                    tenant_id=tenant_id,
                    operator_tenant_id=actor.tenant_id,
                    action="user.roles.update",
                    target_type="user",
                    target_id=str(user_id),
                    audit_metadata={
                        "before_role_ids": sorted(before),
                        "after_role_ids": sorted(after),
                        "source": "kunlian_basic_access",
                    },
                )
            )
            return RoleMutationReceipt(tuple(sorted(before)), tuple(sorted(after)))
