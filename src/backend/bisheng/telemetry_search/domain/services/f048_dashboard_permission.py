"""Business-owned F048 permission adapter for dashboards."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.telemetry_search.domain.models.dashboard_dao import DashboardDao

CUSTOM_DASHBOARD_TYPE = "custom"
PRESET_DASHBOARD_TYPES = frozenset({"preset_oss", "preset_commercial"})
VALID_DASHBOARD_STATUSES = frozenset({"draft", "published"})


@dataclass(frozen=True, slots=True)
class DashboardPermissionRecord:
    tenant_id: int
    resource_id: str
    dashboard_type: str
    status: str
    owner_user_id: int | None
    permission_version: int
    context_version: str


class DashboardPermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_id: str,
    ) -> DashboardPermissionRecord | None: ...


class DashboardDaoPermissionLoader:
    """Load dashboard tenant/type/status before authorization."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_id: str,
    ) -> DashboardPermissionRecord | None:
        if not resource_id.isdigit():
            return None
        row = await DashboardDao.get_one(int(resource_id))
        if row is None or row.id is None:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type="dashboard",
            resource_id=str(row.id),
        )
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        return DashboardPermissionRecord(
            tenant_id=tenant_id,
            resource_id=str(row.id),
            dashboard_type=str(row.dashboard_type),
            status=str(row.status),
            owner_user_id=row.user_id,
            permission_version=version,
            context_version=context_version,
        )


class DashboardPermissionPort(Protocol):
    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]: ...

    async def authorize_created(self, **kwargs): ...

    async def project_copy(self, **kwargs): ...

    async def project_delete(self, **kwargs): ...


class F048DashboardPermissionAdapter:
    """Validate dashboard facts before invoking the permission facade."""

    def __init__(
        self,
        *,
        loader: DashboardPermissionLoader,
        permission: DashboardPermissionPort,
    ) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(
        self,
        resource_id: str,
    ) -> DashboardPermissionRecord | None:
        return await self._loader.load_permission_record(resource_id)

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        del action
        record = await self._loader.load_permission_record(resource_id)
        return self._target(record, resource_id, actor)

    async def check_action(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> bool:
        target = await self.resolve_permission_target(
            resource_id=resource_id,
            actor=actor,
            action=action,
        )
        return await self._permission.check_action(actor, target, action)

    async def batch_check_loaded(
        self,
        *,
        records: tuple[DashboardPermissionRecord, ...],
        actor: PermissionActor,
    ) -> tuple[bool, ...]:
        targets = tuple(self._record_target(record, actor) for record in records)
        return await self._permission.batch_check_actions(
            actor,
            targets,
            "visible",
        )

    async def authorize_created(
        self,
        *,
        record: DashboardPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._record_target(record, actor)
        return await self._permission.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=record.owner_user_id,
            mode="CUSTOM",
            source_type="CREATOR",
            protected=True,
        )

    async def project_delete(
        self,
        *,
        record: DashboardPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._record_target(record, actor),
        )

    async def project_copy(
        self,
        *,
        source: DashboardPermissionRecord,
        target: DashboardPermissionRecord,
        actor: PermissionActor,
        new_owner_user_id: int,
    ):
        return await self._permission.project_copy(
            actor=actor,
            source=self._record_target(source, actor),
            target=self._record_target(target, actor),
            owner_user_id=new_owner_user_id,
            mode="CUSTOM",
        )

    def _record_target(
        self,
        record: DashboardPermissionRecord,
        actor: PermissionActor,
    ) -> VerifiedPermissionTarget:
        return self._target(
            record,
            record.resource_id,
            actor,
        )

    @staticmethod
    def _target(
        record: DashboardPermissionRecord | None,
        resource_id: str,
        actor: PermissionActor,
    ) -> VerifiedPermissionTarget:
        if (
            record is None
            or record.resource_id != resource_id
            or record.dashboard_type not in {CUSTOM_DASHBOARD_TYPE, *PRESET_DASHBOARD_TYPES}
            or record.status not in VALID_DASHBOARD_STATUSES
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
            or record.owner_user_id is None
            or record.owner_user_id <= 0
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type="dashboard",
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
