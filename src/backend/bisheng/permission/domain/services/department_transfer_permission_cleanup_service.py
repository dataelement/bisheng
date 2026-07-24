from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
from bisheng.permission.domain.services.department_transfer_grant_guard import (
    _DepartmentTransferUserLock,
)
from bisheng.permission.domain.services.permission_relation_binding_service import (
    PermissionRelationBindingService,
)
from bisheng.permission.domain.services.permission_service import PermissionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupResult:
    event_id: int
    succeeded: bool
    processed_count: int
    failed_count: int


class DepartmentTransferPermissionCleanupService:
    BATCH_SIZE = 100

    def __init__(
        self,
        *,
        session,
        repository,
        snapshot_service=None,
        permission_service=PermissionService,
        binding_service=None,
        file_grant_repository=None,
        cache_invalidator=None,
        projection_refresher=None,
        audit_writer=None,
        lock_factory=None,
    ):
        self.session = session
        self.repository = repository
        self.snapshot_service = snapshot_service
        self.permission_service = permission_service
        self.binding_service = binding_service or PermissionRelationBindingService()
        self.file_grant_repository = file_grant_repository or DepartmentFileViewGrantRepositoryImpl(session)
        self.cache_invalidator = cache_invalidator or self._invalidate_user_cache
        self.projection_refresher = projection_refresher or self._refresh_projection
        self.audit_writer = audit_writer or DepartmentFileViewGrantAuditWriter(session)
        self.lock_factory = lock_factory or _DepartmentTransferUserLock

    async def process_event(self, event_id: int) -> CleanupResult:
        now = datetime.now()
        event = await self.repository.find_by_id(event_id)
        if event is None:
            return CleanupResult(event_id, False, 0, 0)
        if event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return CleanupResult(
                event_id,
                event.status == DepartmentTransferCleanupEventStatus.SUCCEEDED,
                0,
                0,
            )
        if not await self.repository.claim_event(event_id, now=now):
            return CleanupResult(event_id, False, 0, 0)
        await self.session.commit()

        event = await self.repository.find_by_id(event_id)
        if not event.snapshot_complete and self.snapshot_service is not None:
            try:
                await self.snapshot_service.capture(event)
                await self.session.commit()
            except Exception as exc:
                await self.session.rollback()
                await self._fail_event(event, exc)
                return CleanupResult(event_id, False, 0, 1)

        async with self.lock_factory(int(event.user_id)):
            items = await self.repository.list_processable_items(
                event_id=event_id,
                limit=self.BATCH_SIZE,
            )
            successful: list[tuple[object, str]] = []
            failed: list[tuple[object, Exception]] = []
            affected_resources: set[tuple[str, str]] = set()

            for item in items:
                try:
                    target_status = await self._apply_item(event, item)
                    successful.append((item, target_status))
                    if item.resource_type in {"knowledge_space", "folder", "knowledge_file"}:
                        affected_resources.add((item.resource_type, str(item.resource_id)))
                except Exception as exc:
                    logger.warning(
                        "department transfer cleanup item failed event_id=%s user_id=%s "
                        "old_department_id=%s new_department_id=%s source=%s "
                        "item_id=%s item_type=%s error_summary=%s",
                        event_id,
                        event.user_id,
                        event.old_department_id,
                        event.new_department_id,
                        event.trigger_source,
                        item.id,
                        item.item_type,
                        self._safe_error(exc),
                    )
                    failed.append((item, exc))

            try:
                if successful:
                    await self.cache_invalidator(int(event.user_id))
                    for resource_type, resource_id in sorted(affected_resources):
                        await self.projection_refresher(resource_type, resource_id)
            except Exception as exc:
                failed.extend((item, exc) for item, _ in successful)
                successful = []

            processed_at = datetime.now()
            for item, target_status in successful:
                await self.repository.transition_item(
                    int(item.id),
                    to_status=target_status,
                    processed_at=processed_at,
                )
            for item, exc in failed:
                await self.repository.transition_item(
                    int(item.id),
                    to_status=DepartmentTransferCleanupItemStatus.FAILED,
                    processed_at=None,
                    last_error=self._safe_error(exc),
                )
            await self.repository.refresh_event_counts(event_id)

            if failed:
                self._log_retryable_failure(event, failed[0][1])
                await self.repository.mark_event_failed(
                    event_id,
                    error_summary=self._safe_error(failed[0][1]),
                    next_retry_at=self._next_retry_at(int(event.retry_count or 0)),
                )
                await self.session.commit()
                return CleanupResult(event_id, False, len(successful), len(failed))

            if len(items) >= self.BATCH_SIZE:
                await self.repository.mark_event_failed(
                    event_id,
                    error_summary="batch_remaining",
                    next_retry_at=datetime.now(),
                )
                await self.session.commit()
                return CleanupResult(event_id, False, len(successful), 0)

            await self.repository.mark_event_succeeded(
                event_id,
                completed_at=datetime.now(),
            )
            await self.session.commit()
            return CleanupResult(event_id, True, len(successful), 0)

    async def _apply_item(self, event, item) -> str:
        if item.item_type == DepartmentTransferCleanupItemType.REBAC_TUPLE:
            await self.permission_service.authorize(
                object_type=item.resource_type,
                object_id=str(item.resource_id),
                grants=[],
                revokes=[
                    AuthorizeRevokeItem(
                        subject_type="user",
                        subject_id=int(item.user_id),
                        relation=str(item.relation),
                        include_children=False,
                    )
                ],
                enforce_fga_success=True,
            )
            binding_key = item.snapshot.get("binding_key") or item.source_ref
            if binding_key:
                await self.binding_service.remove_binding_if_matches(
                    str(binding_key),
                    model_id=item.snapshot.get("model_id"),
                )
            return DepartmentTransferCleanupItemStatus.REVOKED

        if item.item_type == DepartmentTransferCleanupItemType.SPACE_MEMBERSHIP:
            member_id = int(item.snapshot.get("member_id") or item.source_ref or 0)
            if not member_id:
                return DepartmentTransferCleanupItemStatus.SKIPPED
            return await self.repository.remove_membership_snapshot(
                member_id=member_id,
                user_id=int(item.user_id),
                space_id=int(item.resource_id),
                expected_source=str(item.snapshot.get("membership_source") or "manual"),
            )

        if item.item_type == DepartmentTransferCleanupItemType.DEPARTMENT_FILE_GRANT:
            granted_at_value = item.snapshot.get("granted_at")
            expected_granted_at = datetime.fromisoformat(granted_at_value) if granted_at_value else None
            grant = await self.file_grant_repository.invalidate_snapshot_grant(
                tenant_id=int(event.tenant_id or 1),
                grant_id=int(item.snapshot.get("grant_id") or item.source_ref),
                user_id=int(item.user_id),
                expected_approval_instance_id=int(item.snapshot["approval_instance_id"]),
                expected_granted_at=expected_granted_at,
                reason=f"primary_department_changed:{event.id}",
            )
            if grant is None:
                return DepartmentTransferCleanupItemStatus.SKIPPED
            audit_result = self.audit_writer.add_transition(
                grant=grant,
                operator_id=0,
                operator_name="system",
                action="permission.department_transfer.file_grant.invalidate",
                old_status="active",
                new_status=grant.status,
                reason=f"primary_department_changed:{event.id}",
            )
            if inspect.isawaitable(audit_result):
                await audit_result
            return DepartmentTransferCleanupItemStatus.REVOKED

        return DepartmentTransferCleanupItemStatus.SKIPPED

    async def _fail_event(self, event, exc: Exception) -> None:
        self._log_retryable_failure(event, exc)
        await self.repository.mark_event_failed(
            int(event.id),
            error_summary=self._safe_error(exc),
            next_retry_at=self._next_retry_at(int(event.retry_count or 0)),
        )
        await self.session.commit()

    @staticmethod
    async def _invalidate_user_cache(user_id: int) -> None:
        from bisheng.permission.domain.services.permission_cache import PermissionCache

        await PermissionCache.invalidate_user(user_id)

    @staticmethod
    async def _refresh_projection(resource_type: str, resource_id: str) -> None:
        from bisheng.worker.knowledge.portal_recommendation import (
            enqueue_portal_recommendation_resource_refresh,
        )

        enqueue_portal_recommendation_resource_refresh(
            resource_type=resource_type,
            resource_id=int(resource_id),
        )

    @staticmethod
    def _next_retry_at(retry_count: int) -> datetime:
        delay_seconds = min(300, 30 * (2 ** min(retry_count, 4)))
        return datetime.now() + timedelta(seconds=delay_seconds)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}:operation_failed"

    @classmethod
    def _log_retryable_failure(cls, event, exc: Exception) -> None:
        logger.warning(
            "department transfer cleanup retryable failure event_id=%s user_id=%s "
            "old_department_id=%s new_department_id=%s source=%s status=%s "
            "retry_count=%s error_summary=%s",
            event.id,
            event.user_id,
            event.old_department_id,
            event.new_department_id,
            event.trigger_source,
            DepartmentTransferCleanupEventStatus.FAILED,
            event.retry_count,
            cls._safe_error(exc),
        )
