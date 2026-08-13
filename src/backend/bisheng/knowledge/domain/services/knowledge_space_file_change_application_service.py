from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol

from loguru import logger

from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusReadPort
from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    KnowledgeSpaceInvalidCursorError,
    SpaceFileChangeApproverUnavailableError,
    SpaceFileChangeInvalidStateError,
    SpaceFileChangeRequestNotFoundError,
)
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    FileChangeRequestReadRow,
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    BatchApprovalItemResult,
    BatchApprovalResp,
    BatchApprovalResult,
    FileChangeActionDetail,
    KnowledgeSpaceFileChangeDetailResp,
    KnowledgeSpacePendingUploadCursorResp,
    KnowledgeSpacePendingUploadItemResp,
)

FileChangeRequestView = FileChangeRequestReadRow
CurrentApproverChecker = Callable[..., Awaitable[bool]]
ProjectionLoader = Callable[[FileChangeRequestView], Awaitable[dict[str, Any]]]
BatchProjectionLoader = Callable[[Sequence[FileChangeRequestView]], Awaitable[dict[int, dict[str, Any]]]]
PreviewLoader = Callable[..., Awaitable[Any]]
CleanupLoader = Callable[..., Awaitable[Any]]


class ApprovalDecisionApplicationPort(Protocol):
    async def decide_instance_for_current_approver(self, **kwargs: Any) -> object: ...

    async def withdraw_instance(self, **kwargs: Any) -> object: ...


class KnowledgeExecutionCoordinatorPort(Protocol):
    async def queue_retry(self, *, tenant_id: int, request_id: int) -> object: ...


class KnowledgeExecutionDispatcherPort(Protocol):
    async def dispatch(self, *, tenant_id: int, request_id: int) -> None: ...


class KnowledgeSpaceFileChangeApplicationService:
    """Knowledge-owned F046 query and command application service."""

    _CURSOR_CONTEXT = "knowledge-space-file-change-uploads:v3"
    _MAX_UPLOAD_SCAN_BATCHES = 5
    _BUSINESS_STATES = (
        KnowledgeSpaceFileChangeExecutionState.QUEUED,
        KnowledgeSpaceFileChangeExecutionState.APPLYING,
        KnowledgeSpaceFileChangeExecutionState.APPLIED,
        KnowledgeSpaceFileChangeExecutionState.FAILED,
        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
        KnowledgeSpaceFileChangeExecutionState.CLOSED,
    )

    def __init__(
        self,
        *,
        repository_factory: Callable[[], Any] = get_async_db_session,
        current_approver_checker: CurrentApproverChecker,
        projection_loader: ProjectionLoader | None,
        batch_projection_loader: BatchProjectionLoader | None = None,
        stage_preview: PreviewLoader,
        formal_preview: PreviewLoader,
        approval_center: ApprovalDecisionApplicationPort,
        terminal_cleanup: CleanupLoader,
        failed_upload_cleanup: CleanupLoader,
        approval_status_port: ApprovalStatusReadPort | None = None,
        execution_coordinator: KnowledgeExecutionCoordinatorPort | None = None,
        execution_dispatcher: KnowledgeExecutionDispatcherPort | None = None,
    ) -> None:
        self.repository_factory = repository_factory
        self.current_approver_checker = current_approver_checker
        self.projection_loader = projection_loader or self._default_projection
        self.batch_projection_loader = batch_projection_loader or self._default_batch_projection
        self.stage_preview = stage_preview
        self.formal_preview = formal_preview
        self.approval_center = approval_center
        self.terminal_cleanup = terminal_cleanup
        self.failed_upload_cleanup = failed_upload_cleanup
        self.approval_status_port = approval_status_port
        self.execution_coordinator = execution_coordinator
        self.execution_dispatcher = execution_dispatcher

    @staticmethod
    def _public_business_status(state: str) -> str:
        if state == KnowledgeSpaceFileChangeExecutionState.NOT_STARTED:
            return KnowledgeSpaceFileChangeExecutionState.QUEUED
        return str(state)

    @asynccontextmanager
    async def _repository(self):
        candidate = self.repository_factory()
        if isinstance(candidate, KnowledgeSpaceFileChangeRequestRepository) or not hasattr(candidate, "__aenter__"):
            yield candidate
            return
        async with candidate as session:
            yield KnowledgeSpaceFileChangeRequestRepository(session)

    @staticmethod
    def _tenant_id(viewer) -> int:
        tenant_id = getattr(viewer, "tenant_id", None)
        if tenant_id is None or int(tenant_id) <= 0:
            raise RuntimeError("tenant-bound F046 API requires a positive tenant")
        return int(tenant_id)

    @staticmethod
    def _instance_id(view: FileChangeRequestView) -> int:
        instance_id = view.request.approval_instance_id
        if instance_id is None or int(instance_id) <= 0:
            raise SpaceFileChangeInvalidStateError()
        return int(instance_id)

    async def _approval_statuses(
        self,
        *,
        tenant_id: int,
        views: Sequence[FileChangeRequestView],
    ) -> dict[int, str]:
        if self.approval_status_port is None:
            raise RuntimeError("F046 approval status read port is not configured")
        instance_ids = tuple(dict.fromkeys(self._instance_id(view) for view in views))
        snapshots = await self.approval_status_port.get_statuses(
            tenant_id=int(tenant_id),
            approval_instance_ids=instance_ids,
        )
        return {int(key): str(value.status) for key, value in snapshots.items()}

    async def _can_approve(self, *, view: FileChangeRequestView, viewer) -> bool:
        if int(view.request.applicant_user_id) == int(viewer.user_id):
            return False
        return bool(
            await self.current_approver_checker(
                tenant_id=self._tenant_id(viewer),
                space_id=int(view.request.space_id),
                user_id=int(viewer.user_id),
            )
        )

    async def _require_visible(self, *, tenant_id: int, space_id: int, request_id: int, viewer):
        async with self._repository() as repository:
            view = await repository.get_request_view(
                tenant_id=int(tenant_id),
                space_id=int(space_id),
                request_id=int(request_id),
            )
        if view is None:
            raise SpaceFileChangeRequestNotFoundError()
        applicant = int(view.request.applicant_user_id) == int(viewer.user_id)
        can_approve = await self._can_approve(view=view, viewer=viewer)
        if not applicant and not can_approve:
            raise SpaceFileChangeRequestNotFoundError()
        return view, can_approve

    @classmethod
    def _upload_cursor_context(cls, *, space_id: int, parent_id: int | None) -> str:
        directory = "root" if parent_id is None else str(int(parent_id))
        return f"{cls._CURSOR_CONTEXT}:{int(space_id)}:{directory}"

    @classmethod
    def _decode_upload_cursor(cls, cursor: str | None, *, context: str) -> tuple[datetime | None, int]:
        try:
            decoded = decode_cursor(cursor, expected_key_len=2, expected_context=context)
        except CursorDecodeError as exc:
            raise KnowledgeSpaceInvalidCursorError(exception=exc) from exc
        if decoded is None:
            return None, 0
        try:
            return datetime.fromisoformat(str(decoded[0])), int(decoded[1])
        except (TypeError, ValueError) as exc:
            raise KnowledgeSpaceInvalidCursorError(exception=exc) from exc

    async def list_uploads(
        self,
        *,
        space_id: int,
        parent_id: int | None = None,
        viewer,
        statuses: Sequence[str] | None = None,
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> KnowledgeSpacePendingUploadCursorResp:
        tenant_id = self._tenant_id(viewer)
        requested = tuple(dict.fromkeys([*(str(value) for value in statuses or () if value), *([str(status)] if status else [])]))
        public_states = requested or self._BUSINESS_STATES
        if any(value not in self._BUSINESS_STATES for value in public_states):
            raise SpaceFileChangeInvalidStateError()
        execution_states = tuple(
            dict.fromkeys(
                state
                for public_state in public_states
                for state in (
                    (KnowledgeSpaceFileChangeExecutionState.NOT_STARTED, KnowledgeSpaceFileChangeExecutionState.QUEUED)
                    if public_state == KnowledgeSpaceFileChangeExecutionState.QUEUED
                    else (public_state,)
                )
            )
        )
        cursor_context = self._upload_cursor_context(space_id=space_id, parent_id=parent_id)
        after_create_time, after_request_id = self._decode_upload_cursor(cursor, context=cursor_context)
        can_manage_space = bool(
            await self.current_approver_checker(
                tenant_id=tenant_id,
                space_id=int(space_id),
                user_id=int(viewer.user_id),
            )
        )
        items: list[KnowledgeSpacePendingUploadItemResp] = []
        raw_has_more = False
        cursor_create_time = after_create_time
        cursor_request_id = after_request_id
        async with self._repository() as repository:
            for _ in range(self._MAX_UPLOAD_SCAN_BATCHES):
                rows, repository_has_more = await repository.list_upload_request_views(
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    parent_id=parent_id,
                    applicant_user_id=None if can_manage_space else int(viewer.user_id),
                    execution_states=execution_states,
                    after_create_time=cursor_create_time,
                    after_request_id=cursor_request_id,
                    limit=int(page_size),
                )
                if not rows:
                    raw_has_more = bool(repository_has_more)
                    break
                projections = await self.batch_projection_loader(rows)
                approval_statuses = await self._approval_statuses(tenant_id=tenant_id, views=rows)
                consumed = 0
                for view in rows:
                    consumed += 1
                    request = view.request
                    cursor_create_time = request.create_time
                    cursor_request_id = int(request.id)
                    if request.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
                        continue
                    projection = projections.get(int(request.id), {})
                    business_status = self._public_business_status(
                        str(projection.get("status") or request.execution_state)
                    )
                    items.append(
                        KnowledgeSpacePendingUploadItemResp(
                            request_id=int(request.id),
                            approval_instance_id=self._instance_id(view),
                            upload_id=str(view.upload_id or ""),
                            file_name=str(request.file_name or view.resource_name),
                            file_size=int(request.file_size or 0),
                            content_hash=request.content_hash,
                            parent_id=request.source_parent_id,
                            applicant_user_id=int(request.applicant_user_id),
                            applicant_user_name=view.applicant_user_name,
                            status=business_status,
                            approval_status=approval_statuses.get(self._instance_id(view)),
                            can_approve=can_manage_space and int(request.applicant_user_id) != int(viewer.user_id),
                            failure_reason=projection.get("failure_reason"),
                            create_time=request.create_time,
                            update_time=request.update_time,
                        )
                    )
                    if len(items) >= int(page_size):
                        break
                raw_has_more = consumed < len(rows) or bool(repository_has_more)
                if len(items) >= int(page_size) or not repository_has_more:
                    break
        next_cursor = None
        if raw_has_more and cursor_create_time is not None:
            next_cursor = encode_cursor((cursor_create_time, int(cursor_request_id)), context=cursor_context)
        return KnowledgeSpacePendingUploadCursorResp(
            data=items,
            page_size=int(page_size),
            has_more=raw_has_more,
            next_cursor=next_cursor,
        )

    async def get_detail(self, *, space_id: int, request_id: int, viewer) -> KnowledgeSpaceFileChangeDetailResp:
        view, can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer), space_id=space_id, request_id=request_id, viewer=viewer
        )
        return await self._build_detail(view=view, can_approve=can_approve)

    async def _build_detail(
        self,
        *,
        view: FileChangeRequestView,
        can_approve: bool,
        status_override: str | None = None,
    ) -> KnowledgeSpaceFileChangeDetailResp:
        tenant_id = int(view.request.tenant_id)
        approval_statuses = await self._approval_statuses(tenant_id=tenant_id, views=(view,))
        projection = await self.projection_loader(view)
        request = view.request
        snapshot = dict(request.action_snapshot or {})
        instance_id = self._instance_id(view)
        return KnowledgeSpaceFileChangeDetailResp(
            request_id=int(request.id),
            space_id=int(request.space_id),
            action=str(request.action),
            resource_type=str(request.resource_type),
            resource_id=request.resource_id,
            upload_id=view.upload_id,
            resource_name=str(view.resource_name or request.file_name or ""),
            file_size=request.file_size,
            content_hash=request.content_hash,
            applicant_user_id=int(request.applicant_user_id),
            applicant_user_name=view.applicant_user_name,
            approval_instance_id=instance_id,
            status=self._public_business_status(
                status_override or str(projection.get("status") or request.execution_state)
            ),
            approval_status=approval_statuses.get(instance_id),
            action_detail=FileChangeActionDetail(
                old_name=snapshot.get("old_name"),
                new_name=snapshot.get("new_name"),
                source_path=snapshot.get("source_path"),
                target_path=snapshot.get("target_path"),
                source_parent_id=request.source_parent_id,
                target_space_id=request.target_space_id,
                target_parent_id=request.target_parent_id,
                relative_path=snapshot.get("relative_path"),
            ),
            can_approve=can_approve,
            failure_reason=projection.get("failure_reason"),
            create_time=request.create_time,
            update_time=request.update_time,
        )

    async def decide_upload(self, *, space_id: int, request_id: int, action: str, comment: str | None, viewer):
        view, can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer), space_id=space_id, request_id=request_id, viewer=viewer
        )
        statuses = await self._approval_statuses(tenant_id=self._tenant_id(viewer), views=(view,))
        if (
            view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            or not can_approve
            or statuses.get(self._instance_id(view)) != "pending"
            or action not in {"approve", "reject"}
        ):
            raise SpaceFileChangeInvalidStateError()
        await self.approval_center.decide_instance_for_current_approver(
            instance_id=self._instance_id(view),
            action=action,
            operator_user_id=int(viewer.user_id),
            operator_user_name=str(getattr(viewer, "user_name", "")),
            operator_tenant_id=self._tenant_id(viewer),
            comment=comment,
        )
        return await self.get_detail(space_id=space_id, request_id=request_id, viewer=viewer)

    async def create_preview(self, *, space_id: int, request_id: int, viewer) -> dict[str, Any]:
        view, can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer), space_id=space_id, request_id=request_id, viewer=viewer
        )
        if view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise SpaceFileChangeInvalidStateError()
        if view.request.executed_resource_id is not None:
            result = await self.formal_preview(int(view.request.executed_resource_id))
            return result if isinstance(result, dict) else {"preview_url": str(result)}
        if not view.upload_id:
            raise SpaceFileChangeRequestNotFoundError()
        url = await self.stage_preview(
            str(view.upload_id), requester_user_id=int(viewer.user_id), can_manage_space=can_approve
        )
        return {"preview_url": str(url)}

    async def cleanup_upload(self, *, space_id: int, request_id: int, viewer):
        view, _ = await self._require_visible(
            tenant_id=self._tenant_id(viewer), space_id=space_id, request_id=request_id, viewer=viewer
        )
        if (
            view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            or int(view.request.applicant_user_id) != int(viewer.user_id)
            or not view.upload_id
        ):
            raise SpaceFileChangeInvalidStateError()
        approval_status = (await self._approval_statuses(tenant_id=self._tenant_id(viewer), views=(view,))).get(
            self._instance_id(view)
        )
        if approval_status == "pending":
            await self.approval_center.withdraw_instance(
                instance_id=self._instance_id(view),
                operator_user_id=int(viewer.user_id),
                operator_user_name=getattr(viewer, "user_name", None),
                reason="upload stage cleanup",
            )
        elif approval_status not in {"rejected", "withdrawn", "cancelled"} and (
            view.request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED
        ):
            raise SpaceFileChangeInvalidStateError()
        if view.request.executed_resource_id is not None:
            await self.failed_upload_cleanup(
                tenant_id=self._tenant_id(viewer),
                space_id=int(space_id),
                request_id=int(request_id),
                executed_resource_id=int(view.request.executed_resource_id),
            )
        await self.terminal_cleanup(
            tenant_id=self._tenant_id(viewer),
            request_id=int(request_id),
            upload_id=str(view.upload_id),
            terminal_action="closed",
            reason="upload stage cleanup",
        )
        async with self._repository() as repository:
            closed_view = await repository.get_request_view(
                tenant_id=self._tenant_id(viewer),
                space_id=int(space_id),
                request_id=int(request_id),
            )
        if closed_view is None or closed_view.request.execution_state != KnowledgeSpaceFileChangeExecutionState.CLOSED:
            raise RuntimeError("F046 terminal cleanup did not persist the closed business state")
        return await self._build_detail(view=closed_view, can_approve=False)

    async def retry_ingest(self, *, space_id: int, request_id: int, viewer):
        view, _ = await self._require_visible(
            tenant_id=self._tenant_id(viewer), space_id=space_id, request_id=request_id, viewer=viewer
        )
        tenant_id = self._tenant_id(viewer)
        approval_status = (await self._approval_statuses(tenant_id=tenant_id, views=(view,))).get(
            self._instance_id(view)
        )
        if (
            view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            or int(view.request.applicant_user_id) != int(viewer.user_id)
            or view.request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED
            or approval_status != "approved"
            or self.execution_coordinator is None
            or self.execution_dispatcher is None
        ):
            raise SpaceFileChangeInvalidStateError()
        await self.execution_coordinator.queue_retry(tenant_id=tenant_id, request_id=int(request_id))
        await self.execution_dispatcher.dispatch(tenant_id=tenant_id, request_id=int(request_id))
        return await self._build_detail(
            view=view, can_approve=False, status_override=KnowledgeSpaceFileChangeExecutionState.QUEUED
        )

    async def batch_approve(
        self,
        *,
        space_id: int,
        viewer,
        approval_instance_ids: Sequence[int] | None,
        change_request_ids: Sequence[int] | None,
    ) -> BatchApprovalResp:
        tenant_id = self._tenant_id(viewer)
        requested_ids = list(approval_instance_ids or change_request_ids or [])
        async with self._repository() as repository:
            if approval_instance_ids:
                rows = await repository.get_request_views_by_instance_ids(
                    tenant_id=tenant_id, space_id=int(space_id), instance_ids=requested_ids
                )
                by_id = {self._instance_id(row): row for row in rows}
            else:
                rows = await repository.get_request_views_by_request_ids(
                    tenant_id=tenant_id, space_id=int(space_id), request_ids=requested_ids
                )
                by_id = {int(row.request.id): row for row in rows}
        approval_statuses = await self._approval_statuses(tenant_id=tenant_id, views=rows) if rows else {}
        items: list[BatchApprovalItemResult] = []
        success_count = 0
        for selected_id in requested_ids:
            row = by_id.get(int(selected_id))
            if row is None or not await self._can_approve(view=row, viewer=viewer):
                items.append(
                    BatchApprovalItemResult(
                        change_request_id=int(selected_id) if change_request_ids else 0,
                        approval_instance_id=int(selected_id) if approval_instance_ids else 0,
                        result=BatchApprovalResult.INVALID,
                        latest_status="not_found",
                        error_code=18073,
                        error_message=SpaceFileChangeRequestNotFoundError().message,
                        retryable=False,
                    )
                )
                continue
            instance_id = self._instance_id(row)
            result = BatchApprovalResult.APPROVED
            error_code = None
            error_message = None
            retryable = False
            if approval_statuses.get(instance_id) != "pending":
                result = BatchApprovalResult.FAILED
                error_message = "Approval request is not pending"
            else:
                try:
                    await self.approval_center.decide_instance_for_current_approver(
                        instance_id=instance_id,
                        action="approve",
                        operator_user_id=int(viewer.user_id),
                        operator_user_name=str(getattr(viewer, "user_name", "")),
                        operator_tenant_id=tenant_id,
                    )
                    success_count += 1
                except BaseErrorCode as exc:
                    result = BatchApprovalResult.FAILED
                    error_code = int(exc.code)
                    error_message = str(exc.message)
                    retryable = isinstance(exc, (SpaceFileChangeApproverUnavailableError, SpaceFileChangeInvalidStateError))
                except Exception:
                    logger.exception(
                        "F046 batch approval failed: tenant_id={} request_id={} instance_id={}",
                        tenant_id,
                        row.request.id,
                        instance_id,
                    )
                    result = BatchApprovalResult.FAILED
                    error_message = "Approval processing failed"
                    retryable = True
            items.append(
                BatchApprovalItemResult(
                    change_request_id=int(row.request.id),
                    approval_instance_id=instance_id,
                    result=result,
                    latest_status=approval_statuses.get(instance_id, "not_found"),
                    error_code=error_code,
                    error_message=error_message,
                    retryable=retryable,
                )
            )
        return BatchApprovalResp(
            success_count=success_count,
            failure_count=len(items) - success_count,
            items=items,
        )

    @staticmethod
    async def _default_projection(view: FileChangeRequestView) -> dict[str, Any]:
        return {
            "status": KnowledgeSpaceFileChangeApplicationService._public_business_status(
                str(view.request.execution_state)
            ),
            "execution_state": str(view.request.execution_state),
            "failure_reason": dict(view.request.execution_checkpoint or {}).get("failure_reason"),
            "cleanup_state": str(view.request.cleanup_state),
        }

    async def _default_batch_projection(self, views: Sequence[FileChangeRequestView]) -> dict[int, dict[str, Any]]:
        return {int(view.request.id): await self._default_projection(view) for view in views}
