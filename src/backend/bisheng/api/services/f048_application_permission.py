"""Business-owned F048 adapter for workflows and assistants."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
)
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)

SYSTEM_APPLICATION_ACTIONS = frozenset({"visible", "use"})


@dataclass(frozen=True, slots=True)
class ApplicationPermissionRecord:
    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    owner_user_id: int
    permission_version: int
    context_version: str
    system_owned: bool = False
    system_allowlisted: bool = False


class ApplicationPermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> ApplicationPermissionRecord | None: ...


class ApplicationDaoPermissionLoader:
    """Load workflow/assistant facts through their owning DAOs."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> ApplicationPermissionRecord | None:
        if resource_type == "workflow":
            row = await FlowDao.aget_flow_by_id(resource_id)
            if row is None or row.flow_type != FlowType.WORKFLOW.value:
                return None
            try:
                status = FlowStatus(row.status).name
            except ValueError:
                return None
            tenant_id = int(row.tenant_id or 0)
            owner_id = int(row.user_id or 0)
            updated = row.update_time
        elif resource_type == "assistant":
            row = await AssistantDao.aget_one_assistant(resource_id)
            if row is None or row.is_delete:
                return None
            try:
                status = AssistantStatus(row.status).name
            except ValueError:
                return None
            tenant_id = int(row.tenant_id or 0)
            owner_id = int(row.user_id or 0)
            updated = row.update_time
        else:
            return None
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        context_version = sha256(
            (f"{permission_context}|{updated.isoformat() if updated else '0'}").encode()
        ).hexdigest()[:64]
        return ApplicationPermissionRecord(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            owner_user_id=owner_id,
            permission_version=version,
            context_version=context_version,
        )


class ApplicationPermissionPort(Protocol):
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


class F048ApplicationPermissionAdapter:
    """Validate application facts before invoking concrete actions."""

    def __init__(
        self,
        *,
        loader: ApplicationPermissionLoader,
        permission: ApplicationPermissionPort,
    ) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> ApplicationPermissionRecord | None:
        return await self._loader.load_permission_record(
            resource_type,
            resource_id,
        )

    async def resolve_permission_target(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        record = await self._loader.load_permission_record(
            resource_type,
            resource_id,
        )
        return self._target(
            record,
            actor,
            resource_type,
            resource_id,
            action=action,
        )

    async def check_action(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> bool:
        target = await self.resolve_permission_target(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            action=action,
        )
        return await self._permission.check_action(actor, target, action)

    async def batch_check_loaded(
        self,
        *,
        records: tuple[ApplicationPermissionRecord, ...],
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
        record: ApplicationPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._record_target(record, actor)
        if record.system_owned:
            return await self._permission.authorize_system_owned(
                actor=actor,
                target=target,
                action_codes=tuple(sorted(SYSTEM_APPLICATION_ACTIONS)),
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
        record: ApplicationPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._record_target(record, actor),
        )

    def _record_target(
        self,
        record: ApplicationPermissionRecord,
        actor: PermissionActor,
        *,
        action: str | None = None,
    ) -> VerifiedPermissionTarget:
        return self._target(
            record,
            actor,
            record.resource_type,
            record.resource_id,
            action=action,
        )

    @staticmethod
    def _target(
        record: ApplicationPermissionRecord | None,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
        *,
        action: str | None,
    ) -> VerifiedPermissionTarget:
        if (
            record is None
            or resource_type not in {"workflow", "assistant"}
            or record.resource_type != resource_type
            or record.resource_id != resource_id
            or record.status not in {"OFFLINE", "ONLINE"}
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
            or (record.system_owned and not record.system_allowlisted)
            or (not record.system_owned and record.owner_user_id <= 0)
        ):
            raise PermissionInvalidResourceError()
        if record.system_owned and action is not None and action not in SYSTEM_APPLICATION_ACTIONS:
            raise InvalidCatalogActionError(msg=f"System application does not support action: {action}")
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
