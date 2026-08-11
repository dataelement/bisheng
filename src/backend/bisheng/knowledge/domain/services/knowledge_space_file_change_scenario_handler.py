from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from inspect import isawaitable
from typing import Any

from loguru import logger

from bisheng.approval.domain.services.approval_outbox_service import Completed, Deferred
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeRequest,
)

FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request"

ApproverResolver = Callable[..., Awaitable[list[int]]]
CurrentApproverChecker = Callable[..., Awaitable[bool]]
ManagedSpaceLoader = Callable[..., Awaitable[list[int]]]
CandidateInstanceLoader = Callable[..., Awaitable[list[int]]]
TenantCandidateLoader = Callable[..., Awaitable[tuple[list[Any], bool]]]
RequestLoader = Callable[..., Awaitable[KnowledgeSpaceFileChangeRequest | None]]
MutationExecutor = Callable[..., Awaitable[Completed | Deferred]]
ResumePreparer = Callable[[Any, str], Awaitable[Deferred] | Deferred]
ResumeDispatcher = Callable[..., Awaitable[Any] | Any]
TerminalCleanup = Callable[..., Awaitable[Any]]


class KnowledgeSpaceFileChangeTerminalCleanupService:
    """Recoverably clean an upload stage after an approval terminal state.

    Request and stage binding is revalidated by tenant + request_id + opaque
    upload_id before every state transition. The request is durably marked
    ``pending`` before the owner upload-stage cleanup runs. A storage failure
    therefore remains retryable and is never laundered into ``success``.
    """

    def __init__(
        self,
        *,
        request_loader: RequestLoader | None = None,
        cleanup_state_saver: Callable[..., Awaitable[KnowledgeSpaceFileChangeRequest]] | None = None,
        upload_stage_cleanup: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.request_loader = request_loader or self._load_bound_request
        self.cleanup_state_saver = cleanup_state_saver or self._save_cleanup_state
        self.upload_stage_cleanup = upload_stage_cleanup or self._cleanup_upload_stage

    async def cleanup(
        self,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        terminal_action: str,
        reason: str | None,
    ) -> KnowledgeSpaceFileChangeRequest:
        del terminal_action, reason  # request state is the durable recovery fact
        request = await self.request_loader(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
        )
        if request is None:
            raise LookupError(f"upload change request or bound stage not found: {request_id}")
        if request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise ValueError(f"terminal upload cleanup cannot clean action={request.action}")
        if request.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
            return request

        request = await self.cleanup_state_saver(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
            cleanup_state=KnowledgeSpaceFileChangeCleanupState.PENDING,
        )
        await self.upload_stage_cleanup(str(upload_id))
        return await self.cleanup_state_saver(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            upload_id=str(upload_id),
            cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS,
        )

    @staticmethod
    async def _load_bound_request(
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        for_update: bool = False,
        session=None,
    ) -> KnowledgeSpaceFileChangeRequest | None:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )
        from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
            KnowledgeSpaceUploadStageRepository,
        )

        async def load(bound_session):
            request = await KnowledgeSpaceFileChangeRequestRepository(bound_session).get_by_id(
                tenant_id=tenant_id,
                request_id=request_id,
                for_update=for_update,
            )
            if request is None or request.upload_stage_id is None:
                return None
            stage = await KnowledgeSpaceUploadStageRepository(bound_session).get_by_upload_id(
                tenant_id=tenant_id,
                upload_id=upload_id,
                for_update=for_update,
            )
            if stage is None or int(stage.id) != int(request.upload_stage_id):
                return None
            return request

        if session is not None:
            return await load(session)
        async with get_async_db_session() as owned_session:
            return await load(owned_session)

    @classmethod
    async def _save_cleanup_state(
        cls,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        cleanup_state: str,
    ) -> KnowledgeSpaceFileChangeRequest:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        async with get_async_db_session() as session:
            async with session.begin():
                request = await cls._load_bound_request(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    upload_id=upload_id,
                    for_update=True,
                    session=session,
                )
                if request is None:
                    raise LookupError(f"upload change request or bound stage not found: {request_id}")
                if request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
                    raise ValueError(f"terminal upload cleanup cannot clean action={request.action}")
                # Never regress a completed cleanup when a duplicate hook races.
                if request.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
                    return request
                request.cleanup_state = cleanup_state
                return await KnowledgeSpaceFileChangeRequestRepository(session).save(request)

    @staticmethod
    async def _cleanup_upload_stage(upload_id: str):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage
        from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
            KnowledgeSpaceUploadStageService,
        )

        async def capacity_loader_not_used(_tenant_id: int, _user_id: int):
            raise RuntimeError("capacity loading is not used by upload-stage cleanup")

        storage = await get_minio_storage()
        service = KnowledgeSpaceUploadStageService(
            storage=storage,
            capacity_loader=capacity_loader_not_used,
        )
        return await service.cleanup(upload_id)


class KnowledgeSpaceFileChangeScenarioHandler:
    """F046 fixed scenario adapter over F025 atomic extension points."""

    scenario_code = FILE_CHANGE_SCENARIO_CODE
    _ALLOWED_EXCEPTION_ACTIONS = frozenset({"retry", "cancel"})
    _FIXED_APPROVER_SOURCES = frozenset({"knowledge_space_owner", "knowledge_space_manager"})
    _ACTION_LABELS = {
        KnowledgeSpaceFileChangeAction.UPLOAD: "上传",
        KnowledgeSpaceFileChangeAction.RENAME: "重命名",
        KnowledgeSpaceFileChangeAction.MOVE: "移动",
        KnowledgeSpaceFileChangeAction.DELETE: "删除",
    }
    _FORBIDDEN_DETAIL_KEYS = frozenset(
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
        approver_resolver: ApproverResolver | None = None,
        current_approver_checker: CurrentApproverChecker | None = None,
        managed_space_loader: ManagedSpaceLoader | None = None,
        candidate_instance_loader: CandidateInstanceLoader | None = None,
        tenant_candidate_loader: TenantCandidateLoader | None = None,
        reconcile_in_uow: Callable[..., Awaitable[Any]] | None = None,
        reconcile_instance: Callable[..., Awaitable[Any]] | None = None,
        request_loader: RequestLoader | None = None,
        mutation_executor: MutationExecutor | None = None,
        resume_preparer: ResumePreparer | None = None,
        resume_dispatcher: ResumeDispatcher | None = None,
        execution_coordinator=None,
        terminal_cleanup: TerminalCleanup | None = None,
    ) -> None:
        self.approver_resolver = approver_resolver or self._resolve_strict_approvers
        self.current_approver_checker = current_approver_checker or self._is_current_approver
        self.managed_space_loader = managed_space_loader
        self.candidate_instance_loader = candidate_instance_loader or self._load_candidate_instance_ids
        self.tenant_candidate_loader = tenant_candidate_loader or self._load_tenant_reconcile_candidates
        self.reconcile_in_uow = reconcile_in_uow or self._reconcile_in_uow
        self.reconcile_instance = reconcile_instance or self._reconcile_instance
        self.request_loader = request_loader or self._load_request
        self.mutation_executor = mutation_executor or self._execute_mutation
        self.resume_preparer = resume_preparer
        self.resume_dispatcher = resume_dispatcher or self._dispatch_resumed_execution
        self.execution_coordinator = execution_coordinator
        self._resume_request_id: int | None = None
        self.terminal_cleanup = terminal_cleanup or KnowledgeSpaceFileChangeTerminalCleanupService().cleanup

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        action = str((req.payload_snapshot or {}).get("action") or "")
        safe_detail = self._sanitize_detail(req.detail_snapshot or {})
        space_name = safe_detail.get("space_name") or f"空间 {self._space_id(req)}"
        return f"{self._action_label(action)} {space_name} / {req.business_name}"

    async def build_detail(self, req) -> dict:
        payload = req.payload_snapshot or {}
        action = str(payload.get("action") or "")
        change = self._sanitize_detail(req.detail_snapshot or {})
        return {
            "change_request_id": self._request_id(req),
            "space_id": self._space_id(req),
            "space_name": change.get("space_name"),
            "resource_type": self._public_resource_type(payload.get("resource_type")),
            "resource_id": payload.get("resource_id"),
            "resource_name": req.business_name,
            "action": action,
            "action_label": self._action_label(action),
            "target_space_id": payload.get("target_space_id"),
            "target_parent_id": payload.get("target_parent_id"),
            "change": change,
            "reason": req.reason,
        }

    async def build_business_link(self, req) -> dict:
        return {
            "space_id": self._space_id(req),
            "change_request_id": self._request_id(req),
        }

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get("sources") or []
        source_types = [str(source.get("type") or "") for source in sources]
        if len(source_types) != 2 or frozenset(source_types) != self._FIXED_APPROVER_SOURCES:
            return []
        return await self.approver_resolver(
            tenant_id=int(req.tenant_id),
            space_id=self._space_id(req),
            applicant_user_id=int(req.applicant_user_id),
        )

    async def _strict_approvers(self, instance) -> list[int]:
        return await self.approver_resolver(
            tenant_id=int(instance.tenant_id),
            space_id=self._space_id(instance),
            applicant_user_id=int(instance.applicant_user_id),
        )

    async def reconcile_pending_approvers(self, *, session, instance, trigger: str):
        return await self.reconcile_in_uow(
            session=session,
            instance_id=int(instance.id),
            resolver=self._strict_approvers,
            trigger=trigger,
        )

    async def reconcile_candidate_instance(self, *, instance_id: int, trigger: str):
        return await self.reconcile_instance(
            instance_id=int(instance_id),
            resolver=self._strict_approvers,
            trigger=trigger,
        )

    async def reconcile_space_pending_approvers(
        self,
        *,
        tenant_id: int,
        space_id: int,
        trigger: str,
        after_instance_id: int = 0,
        limit: int = 100,
    ) -> dict:
        """Reconcile one bounded instance page for a permission event."""

        self._require_matching_tenant(tenant_id)
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        bounded_limit = max(1, min(int(limit), KnowledgeSpaceFileChangeRequestRepository.MAX_RECONCILE_BATCH_SIZE))
        instance_ids = await self.candidate_instance_loader(
            tenant_id=int(tenant_id),
            space_ids=[int(space_id)],
            after_instance_id=int(after_instance_id),
            limit=bounded_limit + 1,
        )
        has_more = len(instance_ids) > bounded_limit
        page_ids = list(dict.fromkeys(int(instance_id) for instance_id in instance_ids[:bounded_limit]))
        processed, failed = await self._reconcile_instance_page(
            instance_ids=page_ids,
            trigger=trigger,
        )
        return {
            "processed": processed,
            "failed": failed,
            "has_more": has_more,
            "next_after_instance_id": page_ids[-1] if page_ids else int(after_instance_id),
        }

    async def reconcile_tenant_pending_approvers(
        self,
        *,
        tenant_id: int,
        trigger: str,
        after_update_time: str | datetime | None = None,
        after_request_id: int = 0,
        limit: int = 100,
    ) -> dict:
        """Reconcile one bounded tenant page using a durable keyset cursor."""

        self._require_matching_tenant(tenant_id)
        cursor_time = self._parse_cursor_time(after_update_time)
        candidates, has_more = await self.tenant_candidate_loader(
            tenant_id=int(tenant_id),
            after_update_time=cursor_time,
            after_request_id=int(after_request_id),
            limit=int(limit),
        )
        instance_ids = list(dict.fromkeys(int(candidate.instance_id) for candidate in candidates))
        processed, failed = await self._reconcile_instance_page(
            instance_ids=instance_ids,
            trigger=trigger,
        )
        if candidates:
            next_update_time = candidates[-1].update_time.isoformat()
            next_request_id = int(candidates[-1].request_id)
        else:
            next_update_time = cursor_time.isoformat() if cursor_time is not None else None
            next_request_id = int(after_request_id)
        return {
            "processed": processed,
            "failed": failed,
            "has_more": bool(has_more),
            "next_after_update_time": next_update_time,
            "next_after_request_id": next_request_id,
        }

    async def _reconcile_instance_page(self, *, instance_ids: list[int], trigger: str) -> tuple[int, int]:
        processed = 0
        failed = 0
        for instance_id in instance_ids:
            try:
                await self.reconcile_candidate_instance(
                    instance_id=int(instance_id),
                    trigger=trigger,
                )
                processed += 1
            except Exception:
                failed += 1
                logger.exception(
                    "F046 approver reconciliation failed: instance_id={} trigger={}",
                    instance_id,
                    trigger,
                )
        return processed, failed

    async def discover_candidate_instances(
        self,
        *,
        tenant_id: int,
        viewer_user_id: int,
        after_instance_id: int = 0,
        limit: int = 100,
    ) -> list[int]:
        managed_space_loader = self.managed_space_loader or self._current_managed_space_ids
        space_ids = await managed_space_loader(
            tenant_id=int(tenant_id),
            user_id=int(viewer_user_id),
        )
        if not space_ids:
            return []
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        bounded_limit = max(1, min(int(limit), KnowledgeSpaceFileChangeRequestRepository.MAX_RECONCILE_BATCH_SIZE))
        return await self.candidate_instance_loader(
            tenant_id=int(tenant_id),
            space_ids=space_ids,
            after_instance_id=int(after_instance_id),
            limit=bounded_limit,
            missing_pending_approver_user_id=int(viewer_user_id),
        )

    async def authorize_view(self, *, instance, viewer_user_id: int) -> bool:
        if int(instance.applicant_user_id) == int(viewer_user_id):
            return True
        return await self.current_approver_checker(
            tenant_id=int(instance.tenant_id),
            space_id=self._space_id(instance),
            user_id=int(viewer_user_id),
        )

    async def filter_visible_instances(self, *, instances: list, viewer_user_id: int, tenant_id: int) -> list:
        applicant_instances = [
            instance for instance in instances if int(instance.applicant_user_id) == int(viewer_user_id)
        ]
        candidates = [instance for instance in instances if int(instance.applicant_user_id) != int(viewer_user_id)]
        if not candidates:
            return applicant_instances

        managed_space_ids = set(
            await (self.managed_space_loader or self._current_managed_space_ids)(
                tenant_id=int(tenant_id),
                user_id=int(viewer_user_id),
            )
        )
        candidate_space_ids = sorted({self._space_id(row) for row in candidates}.intersection(managed_space_ids))
        semaphore = asyncio.Semaphore(8)

        async def resolve_space(space_id: int) -> tuple[int, bool]:
            async with semaphore:
                approvers = await self.approver_resolver(
                    tenant_id=int(tenant_id),
                    space_id=int(space_id),
                    applicant_user_id=None,
                )
            return space_id, int(viewer_user_id) in approvers

        allowed_space_ids = {
            space_id
            for space_id, allowed in await asyncio.gather(
                *(resolve_space(space_id) for space_id in candidate_space_ids)
            )
            if allowed
        }
        return applicant_instances + [row for row in candidates if self._space_id(row) in allowed_space_ids]

    async def authorize_decision(self, *, instance, operator_user_id: int) -> bool:
        return await self.current_approver_checker(
            tenant_id=int(instance.tenant_id),
            space_id=self._space_id(instance),
            user_id=int(operator_user_id),
        )

    async def validate_decision(self, *, instance, operator_user_id: int) -> bool:
        return await self.authorize_decision(instance=instance, operator_user_id=operator_user_id)

    async def exception_action_policy(self, *, action: str, exception=None, **_context) -> bool:
        if action == "cancel":
            return True
        if action != "retry" or exception is None:
            return False
        # The exception service routes these to different owner paths:
        # approver_empty -> strict dynamic reconciliation;
        # execute_failed -> token-bound Deferred resume.
        return str(exception.exception_type) in {"approver_empty", "execute_failed"}

    async def get_business_status_projection(self, *, instance) -> dict:
        request = await self.request_loader(
            tenant_id=int(instance.tenant_id),
            request_id=self._request_id(instance),
        )
        if request is None:
            return {}
        coordinator = self.execution_coordinator or self._build_execution_coordinator()
        return await coordinator.get_business_status_projection(instance=instance, request=request)

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> Completed | Deferred:
        result = await self.mutation_executor(
            instance_id=int(instance_id),
            request_id=self._request_id(payload_snapshot),
            payload_snapshot=payload_snapshot,
        )
        if not isinstance(result, (Completed, Deferred)):
            raise TypeError("F046 mutation executor must return Completed or Deferred")
        return result

    @staticmethod
    async def _execute_mutation(**kwargs) -> Completed | Deferred:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        return await KnowledgeSpaceMutationExecutor().execute(**kwargs)

    async def prepare_resume(self, session, new_token: str) -> Deferred:
        if self.resume_preparer is not None:
            result = self.resume_preparer(session, new_token)
        else:
            if self._resume_request_id is None:
                raise RuntimeError("F046 deferred instance must be bound before resume")
            coordinator = self.execution_coordinator or self._build_execution_coordinator()
            result = coordinator.prepare_resume_in_uow(
                session=session,
                request_id=self._resume_request_id,
                new_token=new_token,
            )
        if isawaitable(result):
            result = await result
        if not isinstance(result, Deferred) or result.execution_token != new_token:
            raise ValueError("F046 resume result must match the current execution token")
        return result

    def bind_deferred_execution(self, *, instance, outbox) -> None:
        """Bind the request selected under F025's instance/outbox locks."""
        if int(outbox.instance_id) != int(instance.id):
            raise ValueError("F046 deferred outbox does not belong to the locked instance")
        self._resume_request_id = self._request_id(instance)

    async def dispatch_resumed_execution(
        self,
        *,
        outbox_id: int,
        execution_token: str,
        tenant_id: int,
    ) -> None:
        await self.dispatch_deferred_execution(
            outbox_id=outbox_id,
            execution_token=execution_token,
            tenant_id=tenant_id,
        )

    async def dispatch_deferred_execution(
        self,
        *,
        outbox_id: int,
        execution_token: str,
        tenant_id: int,
    ) -> None:
        if min(int(outbox_id), int(tenant_id)) <= 0 or not execution_token:
            raise ValueError("F046 deferred dispatch requires outbox, token and tenant")
        effect = self.resume_dispatcher(
            outbox_id=int(outbox_id),
            execution_token=str(execution_token),
            tenant_id=int(tenant_id),
        )
        if isawaitable(effect):
            await effect

    @staticmethod
    def _dispatch_resumed_execution(
        *,
        outbox_id: int,
        execution_token: str,
        tenant_id: int,
    ) -> None:
        try:
            from bisheng.worker.approval.file_change_tasks import coordinate_file_change_execution
        except ImportError as exc:
            raise RuntimeError("F046 execution coordinator worker is not registered") from exc
        coordinate_file_change_execution.apply_async(
            kwargs={
                "outbox_id": int(outbox_id),
                "execution_token": str(execution_token),
            },
            headers={"tenant_id": int(tenant_id)},
        )

    @staticmethod
    def _build_execution_coordinator():
        from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
            KnowledgeSpaceFileChangeExecutionCoordinator,
        )

        return KnowledgeSpaceFileChangeExecutionCoordinator()

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        await self._cleanup_terminal_upload("rejected", instance_id, payload_snapshot, reason)

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        await self._cleanup_terminal_upload("withdrawn", instance_id, payload_snapshot, reason)

    async def on_cancelled(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        await self._cleanup_terminal_upload("cancelled", instance_id, payload_snapshot, reason)

    async def _cleanup_terminal_upload(
        self,
        terminal_action: str,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        del instance_id
        if payload_snapshot.get("action") != KnowledgeSpaceFileChangeAction.UPLOAD:
            return
        tenant_id = self._require_tenant_id()
        upload_id = payload_snapshot.get("upload_id")
        if not upload_id:
            raise ValueError("F046 upload terminal cleanup requires upload_id")
        await self.terminal_cleanup(
            tenant_id=tenant_id,
            request_id=self._request_id(payload_snapshot),
            upload_id=str(upload_id),
            terminal_action=terminal_action,
            reason=reason,
        )

    @classmethod
    def _sanitize_detail(cls, value):
        if isinstance(value, dict):
            return {
                key: cls._sanitize_detail(item)
                for key, item in value.items()
                if str(key).lower() not in cls._FORBIDDEN_DETAIL_KEYS
            }
        if isinstance(value, list):
            return [cls._sanitize_detail(item) for item in value]
        return value

    @classmethod
    def _action_label(cls, action: str) -> str:
        try:
            return cls._ACTION_LABELS[action]
        except KeyError as exc:
            raise ValueError(f"unsupported F046 action: {action}") from exc

    @staticmethod
    def _public_resource_type(resource_type: str | None) -> str | None:
        if resource_type == "knowledge_file":
            return "file"
        return resource_type

    @staticmethod
    def _space_id(value) -> int:
        payload = value if isinstance(value, dict) else value.payload_snapshot or {}
        space_id = payload.get("space_id")
        if space_id is None:
            raise ValueError("F046 snapshot has no space_id")
        return int(space_id)

    @staticmethod
    def _request_id(value) -> int:
        payload = value if isinstance(value, dict) else value.payload_snapshot or {}
        request_id = payload.get("change_request_id")
        if request_id is None and not isinstance(value, dict):
            request_id = getattr(value, "business_resource_id", None)
        if request_id is None:
            raise ValueError("F046 snapshot has no change_request_id")
        return int(request_id)

    @staticmethod
    def _require_tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise RuntimeError("tenant context is required for F046 runtime hooks")
        return int(tenant_id)

    @classmethod
    def _require_matching_tenant(cls, tenant_id: int) -> None:
        if cls._require_tenant_id() != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for F046 reconciliation")

    @staticmethod
    def _parse_cursor_time(value: str | datetime | None) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid F046 reconciliation update_time cursor") from exc

    @staticmethod
    async def _resolve_strict_approvers(**kwargs) -> list[int]:
        from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
            KnowledgeSpaceFileChangeApproverResolver,
        )

        return await KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids(**kwargs)

    @staticmethod
    async def _is_current_approver(**kwargs) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
            KnowledgeSpaceFileChangeApproverResolver,
        )

        return await KnowledgeSpaceFileChangeApproverResolver.is_current_approver(**kwargs)

    @staticmethod
    async def _current_managed_space_ids(*, tenant_id: int, user_id: int) -> list[int]:
        from bisheng.permission.domain.services.permission_service import PermissionService

        if KnowledgeSpaceFileChangeScenarioHandler._require_tenant_id() != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for F046 discovery")
        owner_ids = await PermissionService.list_accessible_ids(user_id, "owner", "knowledge_space")
        manager_ids = await PermissionService.list_accessible_ids(user_id, "manager", "knowledge_space")
        return sorted(
            {int(space_id) for space_id in (owner_ids or []) + (manager_ids or []) if str(space_id).isdigit()}
        )

    @staticmethod
    async def _load_candidate_instance_ids(**kwargs) -> list[int]:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        async with get_async_db_session() as session:
            return await KnowledgeSpaceFileChangeRequestRepository(session).list_reconcilable_instance_ids(**kwargs)

    @staticmethod
    async def _load_tenant_reconcile_candidates(**kwargs):
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        async with get_async_db_session() as session:
            return await KnowledgeSpaceFileChangeRequestRepository(session).list_reconcile_candidates(**kwargs)

    @staticmethod
    async def _reconcile_in_uow(**kwargs):
        from bisheng.approval.domain.services.approval_dynamic_assignee_service import (
            ApprovalDynamicAssigneeService,
        )

        return await ApprovalDynamicAssigneeService.resolve_and_reconcile_in_uow(**kwargs)

    @staticmethod
    async def _reconcile_instance(**kwargs):
        from bisheng.approval.domain.services.approval_dynamic_assignee_service import (
            ApprovalDynamicAssigneeService,
        )

        return await ApprovalDynamicAssigneeService.reconcile_instance(**kwargs)

    @staticmethod
    async def _load_request(**kwargs) -> KnowledgeSpaceFileChangeRequest | None:
        from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
            KnowledgeSpaceFileChangeRequestRepository,
        )

        async with get_async_db_session() as session:
            return await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(**kwargs)
