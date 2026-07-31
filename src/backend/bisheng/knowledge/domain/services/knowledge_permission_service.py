import logging
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Protocol

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import (
    InvalidPermissionModeError,
    PermissionInvalidResourceError,
)
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.knowledge.domain.models.knowledge import (
    KnowledgeDao,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    check_business_action,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)

_PERMISSION_SYNC_TIMEOUT_SECONDS = 60


class KnowledgePermissionService:
    """Action-native F048 checks for business-verified knowledge libraries."""

    @classmethod
    async def check_action_async(
        cls,
        login_user: UserPayload,
        knowledge_id: int,
        action: str,
    ) -> bool:
        return await check_business_action(
            login_user,
            resource_type="knowledge_library",
            resource_id=knowledge_id,
            action=action,
        )

    @classmethod
    def check_action_sync(
        cls,
        login_user: UserPayload,
        knowledge_id: int,
        action: str,
    ) -> bool:
        return run_async_safe(
            cls.check_action_async(
                login_user=login_user,
                knowledge_id=knowledge_id,
                action=action,
            ),
            timeout=_PERMISSION_SYNC_TIMEOUT_SECONDS,
        )

    @classmethod
    async def get_knowledge_action_map_async(
        cls,
        login_user: UserPayload,
        knowledge_ids: list[int],
        actions: list[str],
    ) -> dict[int, set[str]]:
        normalized_ids = [int(knowledge_id) for knowledge_id in knowledge_ids]
        normalized_actions = tuple(dict.fromkeys(actions))
        if not normalized_ids or not normalized_actions:
            return {}

        action_map = await batch_check_business_actions(
            login_user,
            resource_type="knowledge_library",
            resource_ids=normalized_ids,
            actions=normalized_actions,
        )
        return {knowledge_id: set(action_map.get(str(knowledge_id), frozenset())) for knowledge_id in normalized_ids}

    @classmethod
    def get_knowledge_action_map_sync(
        cls,
        login_user: UserPayload,
        knowledge_ids: list[int],
        actions: list[str],
    ) -> dict[int, set[str]]:
        return run_async_safe(
            cls.get_knowledge_action_map_async(
                login_user,
                knowledge_ids,
                actions,
            ),
            timeout=_PERMISSION_SYNC_TIMEOUT_SECONDS,
        )

    async def filter_knowledge_ids_by_action_async(
        self,
        login_user: UserPayload,
        knowledge_ids: list[int],
        action: str,
    ) -> list[int]:
        normalized_ids = [int(knowledge_id) for knowledge_id in knowledge_ids]
        if not normalized_ids:
            return []
        start = perf_counter()
        action_map = await self.get_knowledge_action_map_async(
            login_user,
            normalized_ids,
            [action],
        )
        filtered_ids = [
            knowledge_id for knowledge_id in normalized_ids if action in action_map.get(knowledge_id, set())
        ]
        logger.info(
            "[perf][knowledge.action_map] user_id=%s action=%s candidates=%s kept=%s took_ms=%.2f",
            getattr(login_user, "user_id", None),
            action,
            len(normalized_ids),
            len(filtered_ids),
            (perf_counter() - start) * 1000,
        )
        return filtered_ids

    async def ensure_action_async(
        self,
        login_user: UserPayload,
        knowledge_id: int,
        action: str,
    ) -> None:
        allowed = await self.check_action_async(
            login_user,
            knowledge_id,
            action,
        )
        if not allowed:
            raise UnAuthorizedError()

    def ensure_action_sync(
        self,
        login_user: UserPayload,
        knowledge_id: int,
        action: str,
    ) -> None:
        if not self.check_action_sync(login_user, knowledge_id, action):
            raise UnAuthorizedError()

    async def ensure_knowledge_write_async(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        await self.ensure_action_async(login_user, knowledge_id, "edit")

    async def ensure_knowledge_delete_async(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        await self.ensure_action_async(login_user, knowledge_id, "delete")

    async def ensure_knowledge_read_async(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        await self.ensure_action_async(login_user, knowledge_id, "visible")

    async def ensure_knowledge_use_async(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        await self.ensure_action_async(login_user, knowledge_id, "use")

    def ensure_knowledge_write_sync(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        self.ensure_action_sync(login_user, knowledge_id, "edit")

    def ensure_knowledge_delete_sync(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        self.ensure_action_sync(login_user, knowledge_id, "delete")

    def ensure_knowledge_read_sync(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        self.ensure_action_sync(login_user, knowledge_id, "visible")

    def ensure_knowledge_use_sync(
        self,
        login_user: UserPayload,
        owner_user_id: int,
        knowledge_id: int,
    ) -> None:
        del owner_user_id
        self.ensure_action_sync(login_user, knowledge_id, "use")


@dataclass(frozen=True, slots=True)
class KnowledgeContainerPermissionRecord:
    """Business-verified permission facts for a space or library."""

    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    kind: str
    owner_user_id: int
    permission_version: int
    context_version: str


class KnowledgeContainerPermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeContainerPermissionRecord | None: ...


class KnowledgePermissionVersionPort(Protocol):
    async def get_permission_version(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
    ) -> tuple[int, str]: ...

    async def mode_for_target(
        self,
        target: VerifiedPermissionTarget,
    ): ...


class KnowledgeContainerDaoPermissionLoader:
    """Load business facts first, then obtain permission-owned version state."""

    def __init__(self, version_port: KnowledgePermissionVersionPort) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeContainerPermissionRecord | None:
        if not resource_id.isdigit():
            return None
        row = await KnowledgeDao.aquery_by_id(int(resource_id))
        if row is None or row.id is None or row.tenant_id is None:
            return None
        try:
            kind = KnowledgeTypeEnum(row.type).name
            status = KnowledgeState(row.state).name
        except ValueError:
            return None
        allowed_kinds = {
            "knowledge_space": {"SPACE"},
            "knowledge_library": {"NORMAL", "QA"},
        }
        if kind not in allowed_kinds.get(resource_type, set()):
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=row.tenant_id,
            resource_type=resource_type,
            resource_id=str(row.id),
        )
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        return KnowledgeContainerPermissionRecord(
            tenant_id=row.tenant_id,
            resource_type=resource_type,
            resource_id=str(row.id),
            status=status,
            kind=kind,
            owner_user_id=int(row.user_id or 0),
            permission_version=version,
            context_version=context_version,
        )


class KnowledgeContainerPermissionPort(Protocol):
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

    async def sync_business_source_model(self, **kwargs): ...

    async def remove_ordinary_sources(self, **kwargs): ...

    async def sync_public_reader(self, **kwargs): ...


class F048KnowledgeContainerPermissionAdapter:
    """Keep container business validation outside the permission domain."""

    def __init__(
        self,
        *,
        loader: KnowledgeContainerPermissionLoader,
        source_service: GrantSourceService | None = None,
        permission: KnowledgeContainerPermissionPort,
    ) -> None:
        self._loader = loader
        self._source_service = source_service or GrantSourceService()
        self._permission = permission

    async def load_permission_record(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeContainerPermissionRecord | None:
        return await self._loader.load_permission_record(
            resource_type,
            resource_id,
        )

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
        resource_type: str = "knowledge_library",
    ) -> VerifiedPermissionTarget:
        del action
        record = await self._loader.load_permission_record(
            resource_type,
            resource_id,
        )
        return self._target(record, actor, resource_type, resource_id)

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
        records: tuple[KnowledgeContainerPermissionRecord, ...],
        actor: PermissionActor,
        action: str,
    ) -> tuple[bool, ...]:
        targets = tuple(
            self._target(
                record,
                actor,
                record.resource_type,
                record.resource_id,
            )
            for record in records
        )
        return await self._permission.batch_check_actions(
            actor,
            targets,
            action,
        )

    async def authorize_created(
        self,
        *,
        record: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._lifecycle_target(
            record,
            actor,
            record.resource_type,
            record.resource_id,
        )
        return await self._permission.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=record.owner_user_id,
            mode="CUSTOM",
            protected=True,
        )

    async def project_copy(
        self,
        *,
        source: KnowledgeContainerPermissionRecord,
        target: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
        new_owner_user_id: int,
    ):
        source_target = self._lifecycle_target(
            source,
            actor,
            source.resource_type,
            source.resource_id,
        )
        target_target = self._lifecycle_target(
            target,
            actor,
            target.resource_type,
            target.resource_id,
        )
        return await self._permission.project_copy(
            actor=actor,
            source=source_target,
            target=target_target,
            owner_user_id=new_owner_user_id,
            mode="CUSTOM",
        )

    async def project_delete(
        self,
        *,
        record: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
    ):
        target = self._lifecycle_target(
            record,
            actor,
            record.resource_type,
            record.resource_id,
        )
        return await self._permission.project_delete(
            actor=actor,
            target=target,
        )

    async def sync_membership(
        self,
        *,
        resource_id: str,
        operator_user_id: int,
        subject_user_id: int,
        model_key: str | None,
    ):
        record = await self._loader.load_permission_record(
            "knowledge_space",
            resource_id,
        )
        if record is None:
            raise PermissionInvalidResourceError()
        actor = PermissionActor(
            user_id=operator_user_id,
            current_tenant_id=record.tenant_id,
        )
        target = self._target(
            record,
            actor,
            "knowledge_space",
            resource_id,
        )
        if model_key is not None:
            tenant_rows = await UserTenantDao.aget_user_tenants(subject_user_id)
            if not any(
                row.tenant_id == record.tenant_id and row.status == "active" and row.is_active == 1
                for row in tenant_rows
            ):
                raise PermissionInvalidResourceError()
        source = self._source_service.canonicalize_source(
            source_id=1,
            subject_type="user",
            subject_id=str(subject_user_id),
            source_type="SPACE_MEMBERSHIP",
            source_ref=f"{resource_id}:user:{subject_user_id}",
        )
        return await self._permission.sync_business_source_model(
            actor=actor,
            target=target,
            source=source,
            model_key=model_key,
            idempotency_key=(
                f"space-membership:{resource_id}:{subject_user_id}:{model_key or 'remove'}:{record.permission_version}"
            ),
        )

    async def sync_department(
        self,
        *,
        resource_id: str,
        operator_user_id: int,
        department_id: int,
        model_key: str | None,
        include_children: bool = False,
    ):
        record = await self._loader.load_permission_record(
            "knowledge_space",
            resource_id,
        )
        if record is None:
            raise PermissionInvalidResourceError()
        departments = await DepartmentDao.aget_by_ids([department_id])
        if (
            len(departments) != 1
            or departments[0].tenant_id != record.tenant_id
            or getattr(departments[0], "status", "active") != "active"
        ):
            raise PermissionInvalidResourceError()
        actor = PermissionActor(
            user_id=operator_user_id,
            current_tenant_id=record.tenant_id,
        )
        source = self._source_service.canonicalize_source(
            source_id=1,
            subject_type="department",
            subject_id=str(department_id),
            source_type="DEPARTMENT",
            include_children=include_children,
        )
        return await self._permission.sync_business_source_model(
            actor=actor,
            target=self._target(
                record,
                actor,
                "knowledge_space",
                resource_id,
            ),
            source=source,
            model_key=model_key,
            idempotency_key=(
                f"space-department:{resource_id}:{department_id}:"
                f"{int(include_children)}:{model_key or 'remove'}:"
                f"{record.permission_version}"
            ),
        )

    async def remove_ordinary_sources(
        self,
        *,
        record: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.remove_ordinary_sources(
            actor=actor,
            target=self._target(
                record,
                actor,
                record.resource_type,
                record.resource_id,
            ),
            idempotency_key=(f"space-private:{record.resource_id}:{record.permission_version}"),
        )

    async def sync_public_reader(
        self,
        *,
        record: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
        enabled: bool,
    ):
        return await self._permission.sync_public_reader(
            actor=actor,
            target=self._target(
                record,
                actor,
                record.resource_type,
                record.resource_id,
            ),
            enabled=enabled,
            idempotency_key=(f"space-public:{record.resource_id}:{int(enabled)}:{record.permission_version}"),
        )

    async def switch_mode(
        self,
        *,
        record: KnowledgeContainerPermissionRecord,
        actor: PermissionActor,
        target_mode: str,
    ) -> None:
        del record, actor, target_mode
        raise InvalidPermissionModeError(msg="Knowledge spaces and libraries use fixed CUSTOM mode")

    @staticmethod
    def _target(
        record: KnowledgeContainerPermissionRecord | None,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
    ) -> VerifiedPermissionTarget:
        expected_kinds = {
            "knowledge_space": {"SPACE"},
            "knowledge_library": {"NORMAL", "QA"},
        }
        if (
            record is None
            or resource_type not in expected_kinds
            or record.resource_type != resource_type
            or record.resource_id != resource_id
            or record.status != "PUBLISHED"
            or record.kind not in expected_kinds[resource_type]
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )

    @staticmethod
    def _lifecycle_target(
        record: KnowledgeContainerPermissionRecord | None,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
    ) -> VerifiedPermissionTarget:
        expected_kinds = {
            "knowledge_space": {"SPACE"},
            "knowledge_library": {"NORMAL", "QA"},
        }
        if (
            record is None
            or resource_type not in expected_kinds
            or record.resource_type != resource_type
            or record.resource_id != resource_id
            or record.status not in {state.name for state in KnowledgeState}
            or record.kind not in expected_kinds[resource_type]
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeFilePermissionRecord:
    """Business-verified canonical tree facts for one folder or file."""

    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    owner_user_id: int
    permission_version: int
    context_version: str
    parent_type: str
    parent_id: str
    mode: str
    ancestor_ids: tuple[str, ...] = ()


class KnowledgeFilePermissionLoader(Protocol):
    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeFilePermissionRecord | None: ...


class KnowledgeFileDaoPermissionLoader:
    """Resolve canonical file/folder tree facts through Knowledge DAOs."""

    def __init__(self, version_port: KnowledgePermissionVersionPort) -> None:
        self._versions = version_port

    async def load_permission_record(
        self,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeFilePermissionRecord | None:
        if resource_type not in {"folder", "knowledge_file"} or not resource_id.isdigit():
            return None
        row = await KnowledgeFileDao.query_by_id(int(resource_id))
        if row is None or row.id is None:
            return None
        actual_type = "folder" if row.file_type == FileType.DIR.value else "knowledge_file"
        if actual_type != resource_type:
            return None
        knowledge = await KnowledgeDao.aquery_by_id(row.knowledge_id)
        if knowledge is None or knowledge.type not in {
            KnowledgeTypeEnum.SPACE.value,
            KnowledgeTypeEnum.NORMAL.value,
            KnowledgeTypeEnum.QA.value,
        }:
            return None
        ancestors = tuple(part for part in (row.file_level_path or "").split("/") if part)
        if ancestors:
            parent_type = "folder"
            parent_id = ancestors[-1]
        else:
            parent_type = "knowledge_space" if knowledge.type == KnowledgeTypeEnum.SPACE.value else "knowledge_library"
            parent_id = str(knowledge.id)
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=str(row.id),
        )
        mode_row = await self._versions.mode_for_target(
            VerifiedPermissionTarget.from_business_service(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=str(row.id),
                resource_version=version,
                context_version=permission_context,
                parent_type=parent_type,
                parent_id=parent_id,
            )
        )
        try:
            status = KnowledgeFileStatus(row.status).name
        except ValueError:
            return None
        if resource_type == "folder":
            status = "ACTIVE"
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        return KnowledgeFilePermissionRecord(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=str(row.id),
            status=status,
            owner_user_id=int(row.user_id or 0),
            permission_version=version,
            context_version=context_version,
            parent_type=parent_type,
            parent_id=parent_id,
            mode=mode_row.mode,
            ancestor_ids=ancestors,
        )


class KnowledgeFilePermissionPort(Protocol):
    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...

    async def authorize_created(self, **kwargs): ...

    async def project_parent_change(self, **kwargs): ...

    async def project_copy(self, **kwargs): ...

    async def project_delete(self, **kwargs): ...

    async def create_mode_draft(self, **kwargs): ...

    async def apply_mode_draft(self, **kwargs): ...


class KnowledgeFileDeliveryAuthorizationPort:
    """Keep preview action-free while downloads and RAG use exact actions."""

    def __init__(
        self,
        *,
        file_permissions,
        library_permissions,
    ) -> None:
        self._files = file_permissions
        self._libraries = library_permissions

    async def preview(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
    ) -> None:
        del resource_id, actor

    async def require_download(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> None:
        if resource_type not in {"folder", "knowledge_file"}:
            raise PermissionInvalidResourceError()
        allowed = await self._files.check_action(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            action="download",
        )
        if not allowed:
            from bisheng.common.errcode.permission import PermissionDeniedError

            raise PermissionDeniedError()

    async def require_batch_download(
        self,
        *,
        resources: tuple[tuple[str, str], ...],
        actor: PermissionActor,
    ) -> None:
        for resource_type, resource_id in dict.fromkeys(resources):
            await self.require_download(
                resource_type=resource_type,
                resource_id=resource_id,
                actor=actor,
            )

    async def require_rag_use(
        self,
        *,
        library_id: str,
        actor: PermissionActor,
    ) -> None:
        allowed = await self._libraries.check_action(
            resource_type="knowledge_library",
            resource_id=library_id,
            actor=actor,
            action="use",
        )
        if not allowed:
            from bisheng.common.errcode.permission import PermissionDeniedError

            raise PermissionDeniedError()


class F048KnowledgeFilePermissionAdapter:
    """Validate the business tree before any file/folder permission call."""

    def __init__(
        self,
        *,
        loader: KnowledgeFilePermissionLoader,
        permission: KnowledgeFilePermissionPort,
    ) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> KnowledgeFilePermissionRecord | None:
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

    async def authorize_created(
        self,
        *,
        record: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
    ):
        target = self._record_target(record, actor)
        return await self._permission.authorize_created(
            actor=actor,
            target=target,
            owner_user_id=record.owner_user_id,
            mode="INHERIT",
            protected=True,
        )

    async def project_move(
        self,
        *,
        source: KnowledgeFilePermissionRecord,
        target: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
    ):
        old_target = self._record_target(source, actor)
        new_target = self._record_target(target, actor)
        if (
            source.resource_type != target.resource_type
            or source.resource_id != target.resource_id
            or source.tenant_id != target.tenant_id
            or (source.parent_type == target.parent_type and source.parent_id == target.parent_id)
        ):
            raise PermissionInvalidResourceError()
        return await self._permission.project_parent_change(
            actor=actor,
            old_target=old_target,
            target=new_target,
            mode=source.mode,
        )

    async def project_copy(
        self,
        *,
        source: KnowledgeFilePermissionRecord,
        target: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
    ):
        source_target = self._record_target(source, actor)
        target_target = self._record_target(target, actor)
        if (
            source.resource_type != target.resource_type
            or source.resource_id == target.resource_id
            or source.tenant_id != target.tenant_id
        ):
            raise PermissionInvalidResourceError()
        return await self._permission.project_copy(
            actor=actor,
            source=source_target,
            target=target_target,
            owner_user_id=target.owner_user_id,
            mode=source.mode,
        )

    async def project_delete(
        self,
        *,
        record: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._record_target(record, actor),
        )

    async def create_mode_draft(
        self,
        *,
        record: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
        target_mode: str,
    ):
        return await self._permission.create_mode_draft(
            actor=actor,
            target=self._record_target(record, actor),
            target_mode=target_mode,
        )

    async def apply_mode_draft(
        self,
        *,
        record: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
        draft_id: str,
        request,
    ):
        return await self._permission.apply_mode_draft(
            actor=actor,
            target=self._record_target(record, actor),
            draft_id=draft_id,
            request=request,
        )

    def _record_target(
        self,
        record: KnowledgeFilePermissionRecord,
        actor: PermissionActor,
    ) -> VerifiedPermissionTarget:
        return self._lifecycle_target(
            record,
            actor,
            record.resource_type,
            record.resource_id,
        )

    @staticmethod
    def _target(
        record: KnowledgeFilePermissionRecord | None,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
        *,
        action: str,
    ) -> VerifiedPermissionTarget:
        file_statuses = {status.name for status in KnowledgeFileStatus} if action == "delete" else {"SUCCESS"}
        valid_statuses = {
            "folder": {"ACTIVE", "SUCCESS"},
            "knowledge_file": file_statuses,
        }
        valid_parents = {"knowledge_space", "knowledge_library", "folder"}
        if (
            record is None
            or record.resource_type != resource_type
            or record.resource_id != resource_id
            or resource_type not in valid_statuses
            or record.status not in valid_statuses[resource_type]
            or record.parent_type not in valid_parents
            or not record.parent_id
            or record.parent_id == record.resource_id
            or record.resource_id in record.ancestor_ids
            or record.mode not in {"INHERIT", "CUSTOM"}
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
            parent_type=record.parent_type,
            parent_id=record.parent_id,
        )

    @staticmethod
    def _lifecycle_target(
        record: KnowledgeFilePermissionRecord | None,
        actor: PermissionActor,
        resource_type: str,
        resource_id: str,
    ) -> VerifiedPermissionTarget:
        valid_statuses = {
            "folder": {"ACTIVE", "SUCCESS"},
            "knowledge_file": {status.name for status in KnowledgeFileStatus},
        }
        valid_parents = {"knowledge_space", "knowledge_library", "folder"}
        if (
            record is None
            or record.resource_type != resource_type
            or record.resource_id != resource_id
            or resource_type not in valid_statuses
            or record.status not in valid_statuses[resource_type]
            or record.parent_type not in valid_parents
            or not record.parent_id
            or record.parent_id == record.resource_id
            or record.resource_id in record.ancestor_ids
            or record.mode not in {"INHERIT", "CUSTOM"}
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
            parent_type=record.parent_type,
            parent_id=record.parent_id,
        )
