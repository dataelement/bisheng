from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from loguru import logger

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
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
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    FILE_CHANGE_SCENARIO_CODE,
    FileChangeRequestReadRow,
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    BatchApprovalItemResult,
    BatchApprovalResp,
    BatchApprovalResult,
    FileChangeActionDetail,
    FileChangeApprovalStatus,
    KnowledgeSpaceFileChangeDetailResp,
    KnowledgeSpacePendingUploadCursorResp,
    KnowledgeSpacePendingUploadItemResp,
)

FileChangeRequestView = FileChangeRequestReadRow
CurrentApproverChecker = Callable[..., Awaitable[bool]]
ProjectionLoader = Callable[[FileChangeRequestView], Awaitable[dict[str, Any]]]
BatchProjectionLoader = Callable[
    [Sequence[FileChangeRequestView]],
    Awaitable[dict[int, dict[str, Any]]],
]
PreviewLoader = Callable[..., Awaitable[Any]]
CleanupLoader = Callable[..., Awaitable[Any]]


class KnowledgeSpaceFileChangeApplicationService:
    """Application API for F046 views and commands.

    Knowledge repositories own tenant-bound reads. Approval mutations are
    delegated exclusively to F025 Center/Exception public services.
    """

    _CURSOR_CONTEXT = "knowledge-space-file-change-uploads:v1"
    _MAX_UPLOAD_SCAN_BATCHES = 5
    _STATUS_TO_INSTANCE = {
        "pending": (ApprovalInstanceStatus.PENDING,),
        "approver_empty": (ApprovalInstanceStatus.EXCEPTION,),
        "exception": (ApprovalInstanceStatus.EXCEPTION,),
        "approved": (ApprovalInstanceStatus.APPROVED,),
        "executing": (ApprovalInstanceStatus.EXECUTING,),
        "parsing": (ApprovalInstanceStatus.EXECUTING,),
        "parse_failed": (ApprovalInstanceStatus.EXECUTE_FAILED,),
        "execute_failed": (ApprovalInstanceStatus.EXECUTE_FAILED,),
        "rejected": (ApprovalInstanceStatus.REJECTED,),
        "withdrawn": (ApprovalInstanceStatus.WITHDRAWN,),
        "cancelled": (ApprovalInstanceStatus.CANCELLED,),
        "published": (ApprovalInstanceStatus.EXECUTED,),
        "executed": (ApprovalInstanceStatus.EXECUTED,),
    }

    def __init__(
        self,
        *,
        repository_factory: Callable[[], Any] = get_async_db_session,
        current_approver_checker: CurrentApproverChecker,
        projection_loader: ProjectionLoader | None,
        batch_projection_loader: BatchProjectionLoader | None = None,
        stage_preview: PreviewLoader,
        formal_preview: PreviewLoader,
        approval_center: Any,
        approval_exception: Any,
        terminal_cleanup: CleanupLoader,
        failed_upload_cleanup: CleanupLoader,
    ) -> None:
        self.repository_factory = repository_factory
        self.current_approver_checker = current_approver_checker
        self.projection_loader = projection_loader or self._default_projection
        self.batch_projection_loader = batch_projection_loader or self._default_batch_projection
        self.stage_preview = stage_preview
        self.formal_preview = formal_preview
        self.approval_center = approval_center
        self.approval_exception = approval_exception
        self.terminal_cleanup = terminal_cleanup
        self.failed_upload_cleanup = failed_upload_cleanup

    @asynccontextmanager
    async def _repository(self):
        candidate = self.repository_factory()
        if isinstance(candidate, KnowledgeSpaceFileChangeRequestRepository):
            yield candidate
            return
        if not hasattr(candidate, "__aenter__"):
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

    @staticmethod
    def _normalize_projection(
        view: FileChangeRequestView,
        projection: dict[str, Any] | None,
    ) -> dict[str, Any]:
        projection = dict(projection or {})
        instance_status = str(view.instance.status)
        # Before execution starts, F025 remains the status authority. The
        # coordinator projection is only needed for the executing/failed/
        # executed business phase and must not turn reject/withdraw/cancel or
        # approver_empty into a generic pending label.
        if instance_status == ApprovalInstanceStatus.EXCEPTION:
            projection["status"] = (
                FileChangeApprovalStatus.APPROVER_EMPTY
                if view.open_exception_type == "approver_empty"
                else FileChangeApprovalStatus.EXCEPTION
            )
        elif instance_status in {
            ApprovalInstanceStatus.PENDING,
            ApprovalInstanceStatus.APPROVED,
            ApprovalInstanceStatus.REJECTED,
            ApprovalInstanceStatus.WITHDRAWN,
            ApprovalInstanceStatus.CANCELLED,
        }:
            projection["status"] = instance_status
        elif (
            instance_status == ApprovalInstanceStatus.EXECUTED
            and view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            and projection.get("status") == FileChangeApprovalStatus.PUBLISHED
        ):
            projection["status"] = FileChangeApprovalStatus.EXECUTED
        return projection

    async def _projection(self, view: FileChangeRequestView) -> dict[str, Any]:
        return self._normalize_projection(view, await self.projection_loader(view))

    async def _require_visible(
        self,
        *,
        tenant_id: int,
        space_id: int,
        request_id: int,
        viewer,
    ) -> tuple[FileChangeRequestView, bool]:
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
    def _decode_upload_cursor(cls, cursor: str | None) -> tuple[datetime | None, int]:
        try:
            decoded = decode_cursor(
                cursor,
                expected_key_len=2,
                expected_context=cls._CURSOR_CONTEXT,
            )
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
        viewer,
        statuses: Sequence[str] | None = None,
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> KnowledgeSpacePendingUploadCursorResp:
        tenant_id = self._tenant_id(viewer)
        requested_statuses = [str(value) for value in (statuses or ()) if value]
        if status:
            requested_statuses.append(str(status))
        normalized_statuses = tuple(dict.fromkeys(requested_statuses))
        if any(value not in self._STATUS_TO_INSTANCE for value in normalized_statuses):
            raise SpaceFileChangeInvalidStateError()
        instance_statuses = tuple(
            dict.fromkeys(
                instance_status
                for projected_status in normalized_statuses
                for instance_status in self._STATUS_TO_INSTANCE[projected_status]
            )
        )
        after_create_time, after_request_id = self._decode_upload_cursor(cursor)
        # One strict owner/manager check per page; former tasks never influence visibility.
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
            for _batch_index in range(self._MAX_UPLOAD_SCAN_BATCHES):
                rows, repository_has_more = await repository.list_upload_request_views(
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    applicant_user_id=None if can_manage_space else int(viewer.user_id),
                    instance_statuses=instance_statuses or None,
                    after_create_time=cursor_create_time,
                    after_request_id=cursor_request_id,
                    limit=int(page_size),
                )
                if not rows:
                    raw_has_more = bool(repository_has_more)
                    break
                projections = await self.batch_projection_loader(rows)
                consumed_count = 0
                for view in rows:
                    consumed_count += 1
                    request = view.request
                    cursor_create_time = request.create_time
                    cursor_request_id = int(request.id)
                    projection = self._normalize_projection(
                        view,
                        projections.get(int(request.id)),
                    )
                    projected_status = str(projection.get("status") or view.instance.status)
                    # Instance-level SQL only narrows candidates. Durable business
                    # projection remains authoritative for parsing/execute_failed.
                    if normalized_statuses and projected_status not in normalized_statuses:
                        continue
                    items.append(
                        KnowledgeSpacePendingUploadItemResp(
                            request_id=int(request.id),
                            approval_instance_id=int(view.instance.id),
                            upload_id=str(view.upload_id),
                            file_name=str(request.file_name or view.instance.business_name),
                            file_size=int(request.file_size or 0),
                            content_hash=request.content_hash,
                            applicant_user_id=int(request.applicant_user_id),
                            applicant_user_name=view.instance.applicant_user_name,
                            status=projected_status,
                            can_approve=(can_manage_space and int(request.applicant_user_id) != int(viewer.user_id)),
                            failure_reason=projection.get("failure_reason") or view.outbox_error,
                            create_time=request.create_time,
                            update_time=request.update_time,
                        )
                    )
                    if len(items) >= int(page_size):
                        break
                unconsumed_rows = consumed_count < len(rows)
                raw_has_more = bool(unconsumed_rows or repository_has_more)
                if len(items) >= int(page_size) or not repository_has_more:
                    break
        next_cursor = None
        if raw_has_more and cursor_create_time is not None:
            next_cursor = encode_cursor(
                (cursor_create_time, int(cursor_request_id)),
                context=self._CURSOR_CONTEXT,
            )
        return KnowledgeSpacePendingUploadCursorResp(
            data=items,
            page_size=int(page_size),
            has_more=raw_has_more,
            next_cursor=next_cursor,
        )

    async def get_detail(self, *, space_id: int, request_id: int, viewer) -> KnowledgeSpaceFileChangeDetailResp:
        view, can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer),
            space_id=space_id,
            request_id=request_id,
            viewer=viewer,
        )
        return await self._build_detail(view=view, can_approve=can_approve)

    async def _build_detail(
        self,
        *,
        view: FileChangeRequestView,
        can_approve: bool,
        status_override: str | None = None,
    ) -> KnowledgeSpaceFileChangeDetailResp:
        projection = await self._projection(view)
        status = status_override or str(projection.get("status") or view.instance.status)
        snapshot = dict(view.request.action_snapshot or {})
        return KnowledgeSpaceFileChangeDetailResp(
            request_id=int(view.request.id),
            space_id=int(view.request.space_id),
            action=str(view.request.action),
            resource_type=str(view.request.resource_type),
            resource_id=view.request.resource_id,
            upload_id=view.upload_id,
            resource_name=str(view.request.file_name or view.instance.business_name),
            file_size=view.request.file_size,
            content_hash=view.request.content_hash,
            applicant_user_id=int(view.request.applicant_user_id),
            applicant_user_name=view.instance.applicant_user_name,
            approval_instance_id=int(view.instance.id),
            status=status,
            action_detail=FileChangeActionDetail(
                old_name=snapshot.get("old_name"),
                new_name=snapshot.get("new_name"),
                source_path=snapshot.get("source_path"),
                target_path=snapshot.get("target_path"),
                source_parent_id=view.request.source_parent_id,
                target_space_id=view.request.target_space_id,
                target_parent_id=view.request.target_parent_id,
                relative_path=snapshot.get("relative_path"),
            ),
            can_approve=can_approve,
            failure_reason=projection.get("failure_reason") or view.outbox_error,
            create_time=view.request.create_time,
            update_time=view.request.update_time,
        )

    async def create_preview(self, *, space_id: int, request_id: int, viewer) -> dict[str, Any]:
        view, can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer),
            space_id=space_id,
            request_id=request_id,
            viewer=viewer,
        )
        if view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD:
            raise SpaceFileChangeInvalidStateError()
        if view.request.executed_resource_id is not None:
            result = await self.formal_preview(int(view.request.executed_resource_id))
            return result if isinstance(result, dict) else {"preview_url": str(result)}
        if not view.upload_id:
            raise SpaceFileChangeRequestNotFoundError()
        url = await self.stage_preview(
            str(view.upload_id),
            requester_user_id=int(viewer.user_id),
            can_manage_space=can_approve,
        )
        return {"preview_url": str(url)}

    async def cleanup_upload(
        self,
        *,
        space_id: int,
        request_id: int,
        viewer,
    ) -> KnowledgeSpaceFileChangeDetailResp:
        view, _can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer),
            space_id=space_id,
            request_id=request_id,
            viewer=viewer,
        )
        if (
            view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            or int(view.request.applicant_user_id) != int(viewer.user_id)
            or not view.upload_id
        ):
            raise SpaceFileChangeInvalidStateError()
        status = str(view.instance.status)
        terminal_status = status
        if status == ApprovalInstanceStatus.PENDING:
            await self.approval_center.withdraw_instance(
                instance_id=int(view.instance.id),
                operator_user_id=int(viewer.user_id),
                operator_user_name=getattr(viewer, "user_name", None),
                reason="upload stage cleanup",
            )
            terminal_status = FileChangeApprovalStatus.WITHDRAWN
        elif status == ApprovalInstanceStatus.EXCEPTION:
            if view.open_exception_id is None:
                raise SpaceFileChangeInvalidStateError()
            await self.approval_exception.cancel_exception_api(
                exception_id=int(view.open_exception_id),
                operator_user_id=int(viewer.user_id),
                reason="upload stage cleanup",
            )
            terminal_status = FileChangeApprovalStatus.CANCELLED
        elif status == ApprovalInstanceStatus.EXECUTE_FAILED:
            if view.open_exception_id is None or view.open_exception_type != "execute_failed":
                raise SpaceFileChangeInvalidStateError()
            if view.request.executed_resource_id is not None:
                await self.failed_upload_cleanup(
                    tenant_id=self._tenant_id(viewer),
                    space_id=int(space_id),
                    request_id=int(request_id),
                    executed_resource_id=int(view.request.executed_resource_id),
                )
            await self.approval_exception.cancel_exception_api(
                exception_id=int(view.open_exception_id),
                operator_user_id=int(viewer.user_id),
                reason="upload stage cleanup",
            )
            terminal_status = FileChangeApprovalStatus.CANCELLED
        elif status not in {
            ApprovalInstanceStatus.REJECTED,
            ApprovalInstanceStatus.WITHDRAWN,
            ApprovalInstanceStatus.CANCELLED,
        }:
            raise SpaceFileChangeInvalidStateError()
        await self.terminal_cleanup(
            tenant_id=self._tenant_id(viewer),
            request_id=int(request_id),
            upload_id=str(view.upload_id),
            terminal_action=str(terminal_status),
            reason="upload stage cleanup",
        )
        return await self._build_detail(
            view=view,
            can_approve=False,
            status_override=str(terminal_status),
        )

    async def retry_ingest(
        self,
        *,
        space_id: int,
        request_id: int,
        viewer,
    ) -> KnowledgeSpaceFileChangeDetailResp:
        view, _can_approve = await self._require_visible(
            tenant_id=self._tenant_id(viewer),
            space_id=space_id,
            request_id=request_id,
            viewer=viewer,
        )
        if (
            view.request.action != KnowledgeSpaceFileChangeAction.UPLOAD
            or int(view.request.applicant_user_id) != int(viewer.user_id)
            or view.instance.status != ApprovalInstanceStatus.EXECUTE_FAILED
            or view.outbox_status != "failed"
            or view.open_exception_id is None
            or view.open_exception_type != "execute_failed"
        ):
            raise SpaceFileChangeInvalidStateError()
        resumed = await self.approval_exception.retry_execute_failed_api(
            exception_id=int(view.open_exception_id),
            resolved_by_user_id=int(viewer.user_id),
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
        )
        if not resumed:
            raise SpaceFileChangeInvalidStateError()
        return await self._build_detail(
            view=view,
            can_approve=False,
            status_override=FileChangeApprovalStatus.PARSING,
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
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    instance_ids=requested_ids,
                )
                by_id = {int(row.instance.id): row for row in rows}
            else:
                rows = await repository.get_request_views_by_request_ids(
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    request_ids=requested_ids,
                )
                by_id = {int(row.request.id): row for row in rows}
        items: list[BatchApprovalItemResult] = []
        success_count = 0
        for selected_id in requested_ids:
            row = by_id.get(int(selected_id))
            if row is None:
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
            try:
                currently_authorized = await self._can_approve(view=row, viewer=viewer)
            except BaseErrorCode as exc:
                items.append(
                    BatchApprovalItemResult(
                        change_request_id=int(row.request.id),
                        approval_instance_id=int(row.instance.id),
                        result=BatchApprovalResult.FAILED,
                        latest_status="unavailable",
                        error_code=int(exc.code),
                        error_message=str(exc.message),
                        retryable=isinstance(exc, SpaceFileChangeApproverUnavailableError),
                    )
                )
                continue
            if not currently_authorized:
                # A former approver may know a historical id but must not learn
                # whether the request still exists or what its latest status is.
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
            error_code = None
            error_message = None
            result = BatchApprovalResult.APPROVED
            retryable = False
            try:
                await self.approval_center.decide_instance_for_current_approver(
                    instance_id=int(row.instance.id),
                    action="approve",
                    operator_user_id=int(viewer.user_id),
                    operator_user_name=str(getattr(viewer, "user_name", "")),
                    operator_tenant_id=tenant_id,
                )
                success_count += 1
            except BaseErrorCode as exc:
                if isinstance(exc, ApprovalRequestPermissionDeniedError):
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
                result = BatchApprovalResult.FAILED
                error_code = int(exc.code)
                error_message = str(exc.message)
                retryable = isinstance(
                    exc,
                    (SpaceFileChangeApproverUnavailableError, SpaceFileChangeInvalidStateError),
                )
            except (LookupError, PermissionError, ValueError) as exc:
                result = BatchApprovalResult.FAILED
                error_message = str(exc)
            except Exception:
                logger.exception(
                    "F046 batch approval failed: tenant_id={} space_id={} request_id={} instance_id={}",
                    tenant_id,
                    space_id,
                    row.request.id,
                    row.instance.id,
                )
                result = BatchApprovalResult.FAILED
                error_message = "Approval processing failed"
                retryable = True
            async with self._repository() as repository:
                latest = await repository.get_request_view(
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    request_id=int(row.request.id),
                )
            latest = latest or row
            projection = await self._projection(latest)
            latest_status = str(projection.get("status") or latest.instance.status)
            if result != BatchApprovalResult.APPROVED and latest_status in {
                "pending",
                "exception",
                "approver_empty",
                "execute_failed",
                "parse_failed",
            }:
                retryable = True
            items.append(
                BatchApprovalItemResult(
                    change_request_id=int(row.request.id),
                    approval_instance_id=int(row.instance.id),
                    result=result,
                    latest_status=latest_status,
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
        from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
            KnowledgeSpaceFileChangeExecutionCoordinator,
        )

        return await KnowledgeSpaceFileChangeExecutionCoordinator().get_business_status_projection(
            instance=view.instance,
            request=view.request,
        )

    async def _default_batch_projection(
        self,
        views: Sequence[FileChangeRequestView],
    ) -> dict[int, dict[str, Any]]:
        if not views:
            return {}
        tenant_ids = {int(view.request.tenant_id) for view in views}
        if len(tenant_ids) != 1:
            raise RuntimeError("F046 batch projection cannot mix tenants")
        tenant_id = tenant_ids.pop()
        async with self._repository() as repository:
            file_statuses, steps_by_request = await repository.load_business_projection_facts(
                tenant_id=tenant_id,
                requests=[view.request for view in views],
            )
        from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
            KnowledgeSpaceFileChangeExecutionCoordinator,
        )

        return {
            int(view.request.id): KnowledgeSpaceFileChangeExecutionCoordinator.project_business_status(
                instance_status=str(view.instance.status),
                request=view.request,
                file_status=file_statuses.get(int(view.request.id)),
                steps=steps_by_request.get(int(view.request.id), ()),
            )
            for view in views
        }
