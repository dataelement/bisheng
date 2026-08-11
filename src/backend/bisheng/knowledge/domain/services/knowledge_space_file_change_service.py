from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from loguru import logger

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_registry import (
    SYSTEM_FILE_CHANGE_SCENARIO_CODE,
    ensure_system_file_change_scenario,
)
from bisheng.approval.domain.services.approval_uow import build_post_commit_effect
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeConflictError,
    SpaceFileChangeInvalidStateError,
    SpaceNotFoundError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStageState
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import FootprintEntry
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_repository import (
    KnowledgeSpaceFileChangeRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
    KnowledgeSpaceFileChangeApproverResolver,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_policy_service import (
    KnowledgeSpaceFileChangePolicyService,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_uow import (
    FileChangeRequestUnitOfWork,
    FileChangeRequestUowContext,
    SessionFactory,
)


@dataclass(frozen=True, slots=True)
class FileChangeRequestCommand:
    """Immutable owner-service input used to create one root change request."""

    action: str
    space_id: int
    applicant_user_id: int
    applicant_user_name: str
    resource_type: str
    resource_name: str
    resource_id: int | None = None
    upload_id: str | None = None
    source_parent_id: int | None = None
    target_space_id: int | None = None
    target_parent_id: int | None = None
    applicant_department_id: int | None = None
    reason: str | None = None
    action_snapshot: dict[str, Any] = field(default_factory=dict)
    login_user: Any | None = field(default=None, compare=False, repr=False)
    ip_address: str | None = None


@dataclass(frozen=True, slots=True)
class FileChangeMutationResult:
    decision: str
    approval_instance_id: int | None = None
    change_request_id: int | None = None
    approval_status: str | None = None
    resource: Any | None = None
    error_code: int | None = None
    error_message: str | None = None


class FootprintResolver(Protocol):
    """Knowledge owner API for subtree, version-chain and destination expansion."""

    async def __call__(self, command: FileChangeRequestCommand) -> Sequence[FootprintEntry]: ...


MutationAuthorizer = Callable[[FileChangeRequestCommand], Awaitable[None]]
OwnerManagerChecker = Callable[[FileChangeRequestCommand], Awaitable[bool]]
DirectMutationExecutor = Callable[[FileChangeRequestCommand], Awaitable[Any]]
PendingTaskNotifier = Callable[[Any], Awaitable[None]]
StageRetainer = Callable[[str], Awaitable[Any]]
ScenarioEnsurer = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class _PendingBundle:
    request_id: int
    instance_id: int
    approval_status: str
    duplicate: bool = False


class KnowledgeSpaceFileChangeService:
    """Permission-first orchestration for direct or F025-backed file changes.

    Mutation authorization, footprint expansion and the authoritative mutation
    body remain owner APIs supplied by ``KnowledgeSpaceService`` composition.
    This service never reads KnowledgeFile/Document/Version tables directly.
    """

    _VALID_ACTIONS = {
        KnowledgeSpaceFileChangeAction.UPLOAD,
        KnowledgeSpaceFileChangeAction.RENAME,
        KnowledgeSpaceFileChangeAction.MOVE,
        KnowledgeSpaceFileChangeAction.DELETE,
    }
    _VALID_RESOURCE_TYPES = {
        KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        KnowledgeSpaceFileChangeResourceType.FOLDER,
    }
    _FORBIDDEN_SNAPSHOT_KEYS = frozenset(
        {
            "object_name",
            "storage_object_name",
            "minio_object_name",
            "storage_path",
            "object_path",
        }
    )

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        approval_gate: Any,
        mutation_authorizer: MutationAuthorizer,
        footprint_resolver: FootprintResolver,
        direct_executor: DirectMutationExecutor,
        pending_task_notifier: PendingTaskNotifier,
        stage_retainer: StageRetainer,
        owner_manager_checker: OwnerManagerChecker | None = None,
        policy_service: KnowledgeSpaceFileChangePolicyService | None = None,
        ensure_scenario: ScenarioEnsurer = ensure_system_file_change_scenario,
    ) -> None:
        self.session_factory = session_factory
        self.approval_gate = approval_gate
        self.mutation_authorizer = mutation_authorizer
        self.owner_manager_checker = owner_manager_checker or self._is_current_owner_or_manager
        self.footprint_resolver = footprint_resolver
        self.direct_executor = direct_executor
        self.pending_task_notifier = pending_task_notifier
        self.stage_retainer = stage_retainer
        self.policy_service = policy_service or KnowledgeSpaceFileChangePolicyService(session_factory=session_factory)
        self.ensure_scenario = ensure_scenario
        self.uow = FileChangeRequestUnitOfWork(session_factory=session_factory)

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise RuntimeError("tenant context is required for file change request")
        return int(tenant_id)

    async def request_change(self, command: FileChangeRequestCommand) -> FileChangeMutationResult:
        tenant_id = self._tenant_id()

        # This must be the first externally observable operation. It delegates
        # exact action permissions to the Knowledge owner service, whose public
        # authorization API is backed by PermissionService.
        await self.mutation_authorizer(command)
        self._validate_command(command)

        space = await self._get_space(tenant_id=tenant_id, space_id=command.space_id)
        if space.auth_type == AuthTypeEnum.PRIVATE:
            return await self._execute_direct(command)

        if await self.owner_manager_checker(command):
            return await self._execute_direct(command)

        approval_required = await self.policy_service.is_approval_required(space_id=command.space_id)
        if not approval_required:
            return await self._execute_direct(command)

        uow_result = await self.uow.execute(
            lambda context, effects: self._create_pending_bundle(
                context=context,
                effects=effects,
                tenant_id=tenant_id,
                command=command,
            )
        )
        await self.uow.run_post_commit_effects(uow_result.post_commit_effects)
        bundle = uow_result.value
        return FileChangeMutationResult(
            decision="pending",
            approval_instance_id=bundle.instance_id,
            change_request_id=bundle.request_id,
            approval_status=bundle.approval_status,
        )

    async def request_changes(self, commands: Sequence[FileChangeRequestCommand]) -> list[FileChangeMutationResult]:
        """Process a batch item by item; every successful item owns its commit."""
        results: list[FileChangeMutationResult] = []
        for command in commands:
            try:
                results.append(await self.request_change(command))
            except BaseErrorCode as exc:
                results.append(
                    FileChangeMutationResult(
                        decision="invalid",
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
            except (LookupError, TypeError, ValueError) as exc:
                results.append(FileChangeMutationResult(decision="invalid", error_message=str(exc)))
            except Exception:
                logger.exception(
                    "file change batch item failed: tenant_id={}, space_id={}, action={}, resource_id={}",
                    self._tenant_id(),
                    command.space_id,
                    command.action,
                    command.resource_id,
                )
                results.append(
                    FileChangeMutationResult(
                        decision="invalid",
                        error_message="Internal file change operation failed",
                    )
                )
        return results

    async def _get_space(self, *, tenant_id: int, space_id: int):
        async with self.session_factory() as session:
            space = await KnowledgeSpaceFileChangeRepository(session).get_space(
                tenant_id=tenant_id,
                space_id=space_id,
            )
        if space is None:
            raise SpaceNotFoundError()
        return space

    async def _is_current_owner_or_manager(self, command: FileChangeRequestCommand) -> bool:
        """Use the strict PermissionService-backed resolver for direct bypass."""
        return await KnowledgeSpaceFileChangeApproverResolver.is_current_approver(
            tenant_id=self._tenant_id(),
            space_id=int(command.space_id),
            user_id=int(command.applicant_user_id),
        )

    async def _execute_direct(self, command: FileChangeRequestCommand) -> FileChangeMutationResult:
        # No request transaction is open here. The owner executor remains the
        # authority for its own DB/FGA/storage saga and must be idempotent.
        resource = await self.direct_executor(command)
        return FileChangeMutationResult(decision="direct", resource=resource)

    async def _create_pending_bundle(
        self,
        *,
        context: FileChangeRequestUowContext,
        effects: list,
        tenant_id: int,
        command: FileChangeRequestCommand,
    ) -> _PendingBundle:
        lock_space_ids = sorted(
            {
                int(command.space_id),
                *([int(command.target_space_id)] if command.target_space_id is not None else []),
            }
        )
        locked_spaces = await context.requests.lock_spaces(
            tenant_id=tenant_id,
            space_ids=lock_space_ids,
        )
        if [int(space.id) for space in locked_spaces] != lock_space_ids:
            raise SpaceNotFoundError()

        stage = None
        if command.action == KnowledgeSpaceFileChangeAction.UPLOAD:
            stage = await self._lock_valid_upload_stage(
                context=context,
                tenant_id=tenant_id,
                command=command,
            )
            existing = await context.requests.get_by_upload_stage_id(
                tenant_id=tenant_id,
                upload_stage_id=stage.id,
                for_update=True,
            )
            if existing is not None:
                if existing.approval_instance_id is None:
                    raise RuntimeError("attached upload request has no approval instance")
                instance_status = await context.requests.get_approval_instance_status(
                    tenant_id=tenant_id,
                    approval_instance_id=int(existing.approval_instance_id),
                    for_update=True,
                )
                if instance_status not in {
                    ApprovalInstanceStatus.PENDING,
                    ApprovalInstanceStatus.EXCEPTION,
                    ApprovalInstanceStatus.APPROVED,
                    ApprovalInstanceStatus.EXECUTING,
                    ApprovalInstanceStatus.EXECUTE_FAILED,
                }:
                    raise SpaceFileChangeInvalidStateError()
                if stage.state == KnowledgeSpaceUploadStageState.ATTACHING:
                    effects.append(
                        build_post_commit_effect(
                            "retain_bound_upload_stage",
                            self.stage_retainer,
                            str(stage.upload_id),
                        )
                    )
                return _PendingBundle(
                    request_id=int(existing.id),
                    instance_id=int(existing.approval_instance_id),
                    approval_status=str(instance_status),
                    duplicate=True,
                )
            if stage.state != KnowledgeSpaceUploadStageState.UPLOADED:
                raise SpaceFileChangeInvalidStateError()

        footprints = list(await self.footprint_resolver(command))
        if stage is not None:
            footprints = self._bind_stage_footprint(footprints, stage_id=int(stage.id), space_id=command.space_id)
        if not footprints:
            raise ValueError("authoritative footprint resolver returned no entries")
        if not {entry.space_id for entry in footprints}.issubset(set(lock_space_ids)):
            raise ValueError("footprint contains an unlocked knowledge space")

        blocking = await context.footprints.find_blocking_request_ids(
            tenant_id=tenant_id,
            footprints=footprints,
        )
        if blocking:
            raise SpaceFileChangeConflictError()

        # Existing tenants may predate the bootstrap. Ensure the immutable F046
        # bundle before Gate reads it, while remaining inside this transaction.
        await self.ensure_scenario(tenant_id=tenant_id, session=context.session)

        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=tenant_id,
            space_id=int(command.space_id),
            action=command.action,
            resource_type=command.resource_type,
            resource_id=command.resource_id,
            applicant_user_id=int(command.applicant_user_id),
            upload_stage_id=int(stage.id) if stage is not None else None,
            file_name=stage.file_name if stage is not None else command.resource_name,
            file_size=int(stage.file_size) if stage is not None else None,
            content_hash=stage.content_hash if stage is not None else None,
            source_parent_id=command.source_parent_id,
            target_space_id=command.target_space_id,
            target_parent_id=command.target_parent_id,
            action_snapshot=dict(command.action_snapshot),
        )
        await context.requests.add(tenant_id=tenant_id, request=request)
        await context.footprints.add_many(
            tenant_id=tenant_id,
            request_id=int(request.id),
            footprints=footprints,
        )
        if stage is not None:
            stage.state = KnowledgeSpaceUploadStageState.ATTACHING
            await context.upload_stages.save(stage)
            effects.append(
                build_post_commit_effect(
                    "retain_bound_upload_stage",
                    self.stage_retainer,
                    str(stage.upload_id),
                )
            )

        gate_uow_result = await self.approval_gate.request_or_pass_in_uow(
            self._build_gate_request(tenant_id=tenant_id, request=request, command=command),
            session=context.session,
        )
        if gate_uow_result.result.decision == ApprovalGateDecision.PASS:
            raise RuntimeError("fixed file-change approval scenario cannot use a PASS route")
        await context.requests.attach_approval_instance(
            tenant_id=tenant_id,
            request_id=int(request.id),
            approval_instance_id=int(gate_uow_result.result.instance_id),
        )
        effects.extend(gate_uow_result.post_commit_effects)
        if gate_uow_result.result.task_ids:
            effects.append(
                build_post_commit_effect(
                    "notify_file_change_pending_tasks",
                    self.pending_task_notifier,
                    gate_uow_result.result,
                )
            )
        return _PendingBundle(
            request_id=int(request.id),
            instance_id=int(gate_uow_result.result.instance_id),
            approval_status=str(gate_uow_result.result.decision.value),
        )

    async def _lock_valid_upload_stage(
        self,
        *,
        context: FileChangeRequestUowContext,
        tenant_id: int,
        command: FileChangeRequestCommand,
    ):
        if not command.upload_id:
            raise ValueError("upload_id is required for upload changes")
        stage = await context.upload_stages.get_by_upload_id(
            tenant_id=tenant_id,
            upload_id=command.upload_id,
            for_update=True,
        )
        if stage is None:
            raise SpaceFileChangeInvalidStateError()
        if int(stage.space_id) != int(command.space_id) or int(stage.uploader_user_id) != int(
            command.applicant_user_id
        ):
            raise SpaceFileChangeInvalidStateError()
        expire_at = stage.expire_at
        if expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=UTC)
        if expire_at <= datetime.now(UTC):
            raise SpaceFileChangeInvalidStateError()
        if stage.state not in {
            KnowledgeSpaceUploadStageState.UPLOADED,
            KnowledgeSpaceUploadStageState.ATTACHING,
            KnowledgeSpaceUploadStageState.ATTACHED,
            KnowledgeSpaceUploadStageState.CONSUMED,
        }:
            raise SpaceFileChangeInvalidStateError()
        return stage

    @staticmethod
    def _bind_stage_footprint(
        footprints: Sequence[FootprintEntry],
        *,
        stage_id: int,
        space_id: int,
    ) -> list[FootprintEntry]:
        bound: list[FootprintEntry] = []
        stage_bound = False
        for entry in footprints:
            if entry.resource_type == KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD:
                bound.append(replace(entry, resource_id=stage_id))
                stage_bound = True
            else:
                bound.append(entry)
        if not stage_bound:
            bound.append(
                FootprintEntry(
                    space_id=int(space_id),
                    resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                    resource_id=int(stage_id),
                )
            )
        return bound

    @classmethod
    def _validate_command(cls, command: FileChangeRequestCommand) -> None:
        if command.action not in cls._VALID_ACTIONS:
            raise ValueError(f"unsupported file change action: {command.action}")
        if command.resource_type not in cls._VALID_RESOURCE_TYPES:
            raise ValueError(f"unsupported file change resource type: {command.resource_type}")
        if cls._contains_forbidden_snapshot_key(command.action_snapshot):
            raise ValueError("storage object names cannot be included in an approval snapshot")
        if command.action == KnowledgeSpaceFileChangeAction.UPLOAD:
            if command.resource_type != KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD:
                raise ValueError("upload changes must reference a staged upload")
            if command.resource_id is not None:
                raise ValueError("pending uploads cannot reference a formal resource")
        elif command.resource_id is None:
            raise ValueError("resource_id is required for formal resource changes")
        if command.action == KnowledgeSpaceFileChangeAction.MOVE and command.target_space_id is None:
            raise ValueError("target_space_id is required for move changes")

    @classmethod
    def _contains_forbidden_snapshot_key(cls, value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).lower() in cls._FORBIDDEN_SNAPSHOT_KEYS or cls._contains_forbidden_snapshot_key(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(cls._contains_forbidden_snapshot_key(item) for item in value)
        return False

    @staticmethod
    def _build_gate_request(
        *,
        tenant_id: int,
        request: KnowledgeSpaceFileChangeRequest,
        command: FileChangeRequestCommand,
    ) -> ApprovalGateRequest:
        payload = {
            "change_request_id": int(request.id),
            "space_id": int(command.space_id),
            "action": command.action,
            "resource_type": command.resource_type,
            "resource_id": command.resource_id,
            # This is the public opaque stage handle, never a MinIO object key.
            "upload_id": command.upload_id,
            "source_parent_id": command.source_parent_id,
            "target_space_id": command.target_space_id,
            "target_parent_id": command.target_parent_id,
        }
        return ApprovalGateRequest(
            tenant_id=tenant_id,
            scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
            business_key=f"knowledge-space-change:{request.id}",
            business_resource_type="knowledge_space_file_change",
            business_resource_id=str(request.id),
            business_name=command.resource_name,
            applicant_user_id=int(command.applicant_user_id),
            applicant_user_name=command.applicant_user_name,
            applicant_department_id=command.applicant_department_id,
            reason=command.reason,
            payload_snapshot=payload,
            detail_snapshot=dict(command.action_snapshot),
            ip_address=command.ip_address,
        )
