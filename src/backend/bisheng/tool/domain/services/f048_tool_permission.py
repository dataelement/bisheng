"""Business-owned F048 adapter for tool categories."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao

SYSTEM_TOOL_ACTIONS = frozenset({"visible", "use"})


@dataclass(frozen=True, slots=True)
class ToolPermissionRecord:
    tenant_id: int
    resource_id: str
    status: str
    owner_user_id: int | None
    permission_version: int
    context_version: str
    preset: bool
    system_allowlisted: bool


class ToolPermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_id: str,
    ) -> ToolPermissionRecord | None: ...


class ToolDaoPermissionLoader:
    """Load one tool-category business record before permission checks."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_id: str,
    ) -> ToolPermissionRecord | None:
        if not resource_id.isdigit():
            return None
        row = await GptsToolsDao.aget_one_tool_type(int(resource_id))
        if row is None or row.id is None or row.is_delete:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type="tool",
            resource_id=str(row.id),
        )
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        preset = row.is_preset == ToolPresetType.PRESET.value
        return ToolPermissionRecord(
            tenant_id=tenant_id,
            resource_id=str(row.id),
            status="ACTIVE",
            owner_user_id=row.user_id,
            permission_version=version,
            context_version=context_version,
            preset=preset,
            system_allowlisted=preset and row.user_id is None,
        )


class ToolPermissionPort(Protocol):
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

    async def authorize_system_owned(self, **kwargs): ...

    async def project_delete(self, **kwargs): ...


class F048ToolPermissionAdapter:
    """Reject invalid/preset tool facts before the sole permission facade."""

    def __init__(
        self,
        *,
        loader: ToolPermissionLoader,
        permission: ToolPermissionPort,
    ) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(
        self,
        *,
        resource_id: str,
    ) -> ToolPermissionRecord | None:
        return await self._loader.load_permission_record(resource_id)

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        record = await self._loader.load_permission_record(resource_id)
        return self._target(record, actor, resource_id, action=action)

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
        records: tuple[ToolPermissionRecord, ...],
        actor: PermissionActor,
        action: str,
    ) -> tuple[bool, ...]:
        targets = tuple(self._record_target(record, actor, action=action) for record in records)
        return await self._permission.batch_check_actions(
            actor,
            targets,
            action,
        )

    async def authorize_created(
        self,
        *,
        record: ToolPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._record_target(record, actor)
        if record.preset:
            return await self._permission.authorize_system_owned(
                actor=actor,
                target=target,
                action_codes=tuple(sorted(SYSTEM_TOOL_ACTIONS)),
            )
        return await self._permission.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=record.owner_user_id,
            mode="CUSTOM",
            protected=True,
        )

    async def project_delete(
        self,
        *,
        record: ToolPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._record_target(record, actor),
        )

    def _record_target(
        self,
        record: ToolPermissionRecord,
        actor: PermissionActor,
        *,
        action: str | None = None,
    ) -> VerifiedPermissionTarget:
        return self._target(
            record,
            actor,
            record.resource_id,
            action=action,
        )

    @staticmethod
    def _target(
        record: ToolPermissionRecord | None,
        actor: PermissionActor,
        resource_id: str,
        *,
        action: str | None,
    ) -> VerifiedPermissionTarget:
        if (
            record is None
            or record.resource_id != resource_id
            or record.status != "ACTIVE"
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
            or (record.preset and not record.system_allowlisted)
            or (not record.preset and not record.owner_user_id)
        ):
            raise PermissionInvalidResourceError()
        if record.preset and action is not None and action not in SYSTEM_TOOL_ACTIONS:
            raise InvalidCatalogActionError(msg=f"Preset tool does not support action: {action}")
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type="tool",
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
