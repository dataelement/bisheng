"""Business-owned F048 permission adapter for information channels."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from sqlmodel import select

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.group import Group
from bisheng.database.models.tenant import UserTenant
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)

READ_ONLY_CHANNEL_ACTIONS = frozenset({"visible", "use"})


@dataclass(frozen=True, slots=True)
class ChannelPermissionRecord:
    tenant_id: int
    resource_id: str
    status: str
    creator_user_id: int
    permission_version: int
    context_version: str
    shared_read_only: bool = False
    system_read_only: bool = False


@dataclass(frozen=True, slots=True)
class ChannelSubjectRecord:
    tenant_id: int
    subject_type: str
    subject_id: str
    status: str


class ChannelPermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_id: str,
    ) -> ChannelPermissionRecord | None: ...

    async def load_subject(
        self,
        subject_type: str,
        subject_id: str,
    ) -> ChannelSubjectRecord | None: ...


class ChannelDaoPermissionLoader:
    """Load channel and tenant-subject facts from business-owned tables."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_id: str,
    ) -> ChannelPermissionRecord | None:
        async with get_async_db_session() as session:
            row = await session.get(Channel, resource_id)
        if row is None:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type="channel",
            resource_id=str(row.id),
        )
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        return ChannelPermissionRecord(
            tenant_id=tenant_id,
            resource_id=str(row.id),
            status="ACTIVE",
            creator_user_id=int(row.user_id),
            permission_version=version,
            context_version=context_version,
            shared_read_only=bool(row.is_shared),
            system_read_only=False,
        )

    async def load_subject(
        self,
        subject_type: str,
        subject_id: str,
    ) -> ChannelSubjectRecord | None:
        if not subject_id.isdigit():
            return None
        identifier = int(subject_id)
        async with get_async_db_session() as session:
            if subject_type == "user":
                statement = select(UserTenant).where(
                    UserTenant.user_id == identifier,
                    UserTenant.status == "active",
                    UserTenant.is_active == 1,
                )
                row = (await session.execute(statement)).scalars().first()
                tenant_id = int(row.tenant_id) if row else 0
            elif subject_type == "department":
                row = await session.get(Department, identifier)
                tenant_id = int(row.tenant_id or 0) if row else 0
            elif subject_type == "user_group":
                row = await session.get(Group, identifier)
                tenant_id = int(row.tenant_id or 0) if row else 0
            else:
                return None
        if tenant_id <= 0:
            return None
        return ChannelSubjectRecord(
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            status="ACTIVE",
        )


class ChannelPermissionPort(Protocol):
    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...

    async def authorize_created(self, **kwargs): ...

    async def project_delete(self, **kwargs): ...

    async def sync_business_source_model(self, **kwargs): ...

    async def remove_ordinary_sources(self, **kwargs): ...


class F048ChannelPermissionAdapter:
    """Validate channel and grant-subject facts before permission evaluation."""

    def __init__(
        self,
        *,
        loader: ChannelPermissionLoader,
        source_service: GrantSourceService,
        permission: ChannelPermissionPort,
    ) -> None:
        self._loader = loader
        self._source_service = source_service
        self._permission = permission

    async def load_permission_record(
        self,
        resource_id: str,
    ) -> ChannelPermissionRecord | None:
        return await self._loader.load_permission_record(resource_id)

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        record = await self._loader.load_permission_record(resource_id)
        return self._target(record, resource_id, actor, action=action)

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

    async def authorize_created(
        self,
        *,
        record: ChannelPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._target(record, record.resource_id, actor)
        return await self._permission.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=record.creator_user_id,
            mode="CUSTOM",
            source_type="CREATOR",
            protected=True,
        )

    async def project_delete(
        self,
        *,
        record: ChannelPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._target(record, record.resource_id, actor),
        )

    async def sync_membership(
        self,
        *,
        resource_id: str,
        operator_user_id: int,
        subject_user_id: int,
        model_key: str | None,
    ):
        record = await self._loader.load_permission_record(resource_id)
        if record is None:
            raise PermissionInvalidResourceError()
        actor = PermissionActor(
            user_id=operator_user_id,
            current_tenant_id=record.tenant_id,
        )
        target = self._target(record, resource_id, actor)
        subject = await self._loader.load_subject(
            "user",
            str(subject_user_id),
        )
        if subject is None or subject.status != "ACTIVE" or subject.tenant_id != record.tenant_id:
            raise PermissionInvalidResourceError()
        source_ref = f"{resource_id}:user:{subject_user_id}"
        source = self._source_service.canonicalize_source(
            source_id=1,
            subject_type="user",
            subject_id=str(subject_user_id),
            source_type="CHANNEL_MEMBERSHIP",
            source_ref=source_ref,
        )
        return await self._permission.sync_business_source_model(
            actor=actor,
            target=target,
            source=source,
            model_key=model_key,
            idempotency_key=(
                f"channel-membership:{resource_id}:{subject_user_id}:"
                f"{model_key or 'remove'}:{record.permission_version}"
            ),
        )

    async def remove_ordinary_sources(
        self,
        *,
        record: ChannelPermissionRecord,
        actor: PermissionActor,
    ):
        last_outcome = None
        while True:
            current = await self._loader.load_permission_record(
                record.resource_id,
            )
            if current is None:
                raise PermissionInvalidResourceError()
            target = self._target(
                current,
                current.resource_id,
                actor,
            )
            outcome = await self._permission.remove_ordinary_sources(
                actor=actor,
                target=target,
                idempotency_key=(f"channel-private:{current.resource_id}:{current.permission_version}"),
            )
            if outcome is None:
                return last_outcome
            last_outcome = outcome

    async def canonical_source(
        self,
        *,
        source_id: int,
        actor: PermissionActor,
        subject_type: str,
        subject_id: str,
        include_children: bool,
    ) -> GrantSourceRecord:
        normalized_type = subject_type.strip().lower()
        normalized_id = subject_id.strip()
        subject = await self._loader.load_subject(
            normalized_type,
            normalized_id,
        )
        if (
            subject is None
            or subject.status != "ACTIVE"
            or subject.tenant_id != actor.current_tenant_id
            or subject.subject_type != normalized_type
            or subject.subject_id != normalized_id
        ):
            raise PermissionInvalidResourceError()

        source_types = {
            "user": "DIRECT",
            "department": "DEPARTMENT",
            "user_group": "USER_GROUP",
        }
        source_type = source_types.get(normalized_type)
        if source_type is None:
            raise PermissionInvalidResourceError()
        return self._source_service.canonicalize_source(
            source_id=source_id,
            subject_type=normalized_type,
            subject_id=normalized_id,
            source_type=source_type,
            include_children=include_children,
            source_ref=f"channel-grant:{normalized_type}:{normalized_id}",
        )

    @staticmethod
    def _target(
        record: ChannelPermissionRecord | None,
        resource_id: str,
        actor: PermissionActor,
        *,
        action: str | None = None,
    ) -> VerifiedPermissionTarget:
        if (
            record is None
            or record.resource_id != resource_id
            or record.status != "ACTIVE"
            or record.creator_user_id <= 0
        ):
            raise PermissionInvalidResourceError()

        read_only = record.shared_read_only or record.system_read_only
        if record.tenant_id != actor.current_tenant_id and not actor.super_admin and not read_only:
            raise PermissionInvalidResourceError()
        if read_only and action is not None and action not in READ_ONLY_CHANNEL_ACTIONS:
            raise InvalidCatalogActionError(msg=f"Read-only channel does not support action: {action}")
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type="channel",
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
