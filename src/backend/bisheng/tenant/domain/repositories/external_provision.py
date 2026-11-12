"""租户结构、来源操作与回执的持久事务。"""

import json
from contextlib import asynccontextmanager
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
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from bisheng.tenant.domain.models.external_provision import TenantExternalProvision


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ExternalTenantCommand:
    connection_id: str
    issuer: str
    external_tenant_id: str
    display_name: str
    source_batch_id: str
    source_revision: str
    policy_revision: int
    manual_tenant_id: int | None = None
    active: bool = True
    directory_complete: bool = True

    @property
    def source_key(self):
        return _digest(["kunlian", self.issuer, self.external_tenant_id])

    @property
    def payload_digest(self):
        return _digest(
            [
                self.connection_id,
                self.issuer,
                self.external_tenant_id,
                self.display_name,
                self.source_batch_id,
                self.source_revision,
                self.policy_revision,
                self.manual_tenant_id,
            ]
        )


@dataclass(frozen=True)
class ExternalTenantOperation:
    source_key: str
    operation_id: str
    fence: int
    payload_digest: str


@dataclass(frozen=True)
class ExternalTenantReceipt:
    source_key: str
    local_tenant_id: int
    anchor_department_id: int
    operation_id: str
    fence: int
    state: str
    local_policy_revision: int


@dataclass(frozen=True)
class ExternalTenantState:
    source_key: str
    connection_id: str
    local_tenant_id: int | None
    state: str
    local_blocked: bool
    local_policy_revision: int
    fence: int


class TenantExternalProvisionRepository:
    def __init__(self, session_factory=get_async_db_session):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _session(self):
        if get_current_tenant_id() != 1:
            raise KunlianBindingConflictError()
        with strict_tenant_filter():
            async with self.session_factory() as session:
                try:
                    async with session.begin():
                        yield session
                except IntegrityError:
                    raise KunlianBindingConflictError() from None
                except SQLAlchemyError:
                    raise KunlianDependencyUnavailableError() from None

    @staticmethod
    def validate(command):
        values = [
            (command.connection_id, 64),
            (command.issuer, 2048),
            (command.external_tenant_id, 64),
            (command.display_name, 128),
            (command.source_batch_id, 36),
            (command.source_revision, 64),
        ]
        if (
            any(not isinstance(v, str) or not v.strip() or len(v) > n for v, n in values)
            or type(command.policy_revision) is not int
            or command.policy_revision < 1
            or (
                command.manual_tenant_id is not None
                and (type(command.manual_tenant_id) is not int or command.manual_tenant_id <= 1)
            )
        ):
            raise KunlianBindingConflictError()
        if command.active is not True or command.directory_complete is not True:
            raise KunlianIdentityUnavailableError()

    @staticmethod
    async def _row(session, key):
        return (
            await session.exec(
                select(TenantExternalProvision)
                .where(TenantExternalProvision.source_key == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()

    @staticmethod
    def _operation(row):
        return ExternalTenantOperation(row.source_key, row.operation_id, row.fence, row.payload_digest)

    @staticmethod
    def _check(row, operation):
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

    async def reserve(self, command, *, expected_fence=None):
        self.validate(command)
        async with self._session() as session:
            row = await self._row(session, command.source_key)
            if row is None:
                row = TenantExternalProvision(
                    source_key=command.source_key,
                    connection_id=command.connection_id,
                    issuer=command.issuer,
                    issuer_digest=_digest(command.issuer),
                    external_tenant_id=command.external_tenant_id,
                    mapping_origin="manual" if command.manual_tenant_id else "auto",
                )
            if (row.issuer, row.connection_id, row.external_tenant_id) != (
                command.issuer,
                command.connection_id,
                command.external_tenant_id,
            ):
                raise KunlianBindingConflictError()
            if row.local_blocked:
                raise KunlianIdentityUnavailableError()
            if command.policy_revision < row.policy_revision:
                raise KunlianBindingConflictError()
            if row.payload_digest != command.payload_digest or row.operation_id is None:
                if row.fence and expected_fence != row.fence:
                    raise KunlianBindingConflictError()
                row.fence += 1
                row.operation_id = str(uuid4())
                row.payload_digest = command.payload_digest
                row.policy_revision = command.policy_revision
                row.source_batch_id = command.source_batch_id
                row.source_revision = command.source_revision
                row.state = "STRUCTURE_READY" if row.local_tenant_id else "PENDING"
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            return self._operation(row)

    @staticmethod
    async def _structure(session, row):
        tenant = (await session.exec(select(Tenant).where(Tenant.id == row.local_tenant_id).with_for_update())).first()
        anchor = (
            await session.exec(select(Department).where(Department.id == row.anchor_department_id).with_for_update())
        ).first()
        if (
            tenant is None
            or tenant.status != "active"
            or tenant.parent_tenant_id != 1
            or tenant.root_dept_id != row.anchor_department_id
            or anchor is None
            or anchor.tenant_id != 1
            or anchor.mounted_tenant_id != tenant.id
            or anchor.is_tenant_root != 1
            or anchor.status != "active"
        ):
            raise KunlianIdentityUnavailableError()
        return tenant, anchor

    async def ensure_structure(self, command, operation, anchor_provider):
        self.validate(command)
        if operation.source_key != command.source_key or operation.payload_digest != command.payload_digest:
            raise KunlianBindingConflictError()
        async with self._session() as session:
            row = await self._row(session, operation.source_key)
            self._check(row, operation)
            if row.local_tenant_id is None:
                if command.manual_tenant_id:
                    tenant = (
                        await session.exec(
                            select(Tenant).where(Tenant.id == command.manual_tenant_id).with_for_update()
                        )
                    ).first()
                    if tenant is None:
                        raise KunlianBindingConflictError()
                    row.local_tenant_id, row.anchor_department_id = tenant.id, tenant.root_dept_id
                    await self._structure(session, row)
                else:
                    root = (await session.exec(select(Tenant).where(Tenant.id == 1).with_for_update())).first()
                    if (
                        root is None
                        or root.status != "active"
                        or root.parent_tenant_id is not None
                        or not root.root_dept_id
                    ):
                        raise KunlianIdentityUnavailableError()
                    tenant = Tenant(
                        tenant_code="kl_" + command.source_key[:56],
                        tenant_name=command.display_name,
                        parent_tenant_id=1,
                        share_default_to_children=0,
                        create_user=None,
                    )
                    session.add(tenant)
                    await session.flush()
                    anchor_id = await anchor_provider(
                        session,
                        root_department_id=root.root_dept_id,
                        local_tenant_id=tenant.id,
                        source_key=command.source_key,
                        display_name=command.display_name,
                    )
                    tenant.root_dept_id = anchor_id
                    session.add(tenant)
                    row.local_tenant_id, row.anchor_department_id = tenant.id, anchor_id
                row.state = "STRUCTURE_READY"
            else:
                tenant, _ = await self._structure(session, row)
                if command.manual_tenant_id is not None and command.manual_tenant_id != tenant.id:
                    raise KunlianBindingConflictError()
                if row.mapping_origin == "auto":
                    tenant.tenant_name = command.display_name
                    session.add(tenant)
            row.applied_operation_id, row.applied_fence = operation.operation_id, operation.fence
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            await session.flush()
            return self._receipt(row)

    @staticmethod
    def _receipt(row):
        return ExternalTenantReceipt(
            row.source_key,
            row.local_tenant_id,
            row.anchor_department_id,
            row.applied_operation_id,
            row.applied_fence,
            row.state,
            row.local_policy_revision,
        )

    async def mark_ready(self, operation):
        async with self._session() as session:
            row = await self._row(session, operation.source_key)
            self._check(row, operation)
            await self._structure(session, row)
            if row.applied_fence != operation.fence or row.applied_operation_id != operation.operation_id:
                raise KunlianBindingConflictError()
            row.state = "READY"
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            return self._receipt(row)

    async def read_receipt(self, operation):
        async with self._session() as session:
            row = await self._row(session, operation.source_key)
            self._check(row, operation)
            await self._structure(session, row)
            if (
                row.state != "READY"
                or row.applied_fence != operation.fence
                or row.applied_operation_id != operation.operation_id
            ):
                raise KunlianDependencyUnavailableError()
            return self._receipt(row)

    async def set_policy(self, source_key, *, expected_revision, enabled):
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 1:
            raise KunlianBindingConflictError()
        async with self._session() as session:
            row = await self._row(session, source_key)
            if row is None or row.local_policy_revision != expected_revision:
                raise KunlianBindingConflictError()
            row.local_policy_revision += 1
            row.fence += 1
            row.operation_id = None
            row.local_blocked = not enabled
            row.state = "PENDING" if enabled else "BLOCKED"
            row.update_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(row)
            return row.local_policy_revision

    async def read_source_state(self, source_key):
        async with self._session() as session:
            row = await self._row(session, source_key)
            if row is None:
                return None
            return ExternalTenantState(
                row.source_key,
                row.connection_id,
                row.local_tenant_id,
                row.state,
                row.local_blocked,
                row.local_policy_revision,
                row.fence,
            )
