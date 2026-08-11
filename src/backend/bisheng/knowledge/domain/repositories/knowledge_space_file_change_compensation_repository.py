from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import (
    KnowledgeSpaceUploadStage,
    KnowledgeSpaceUploadStageState,
)


@dataclass(frozen=True, slots=True)
class DeferredWatchdogCandidate:
    outbox_id: int
    request_id: int
    execution_token: str


@dataclass(frozen=True, slots=True)
class ExecutionStepRecoveryCandidate:
    step_id: int
    request_id: int
    instance_id: int
    outbox_id: int
    execution_token: str
    execution_state: str


@dataclass(frozen=True, slots=True)
class FileChangeCleanupCandidate:
    request_id: int
    kind: str
    upload_id: str | None = None
    terminal_action: str | None = None
    execution_token: str | None = None


@dataclass(frozen=True, slots=True)
class ExpiredOrphanStageCandidate:
    stage_id: int
    upload_id: str


class KnowledgeSpaceFileChangeCompensationRepository:
    """Tenant-bound, bounded read model for F046 Beat compensation."""

    MAX_BATCH_SIZE = 500
    ACTIVE_STEP_STATES = (
        KnowledgeSpaceFileChangeExecutionStepState.PENDING,
        KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
        KnowledgeSpaceFileChangeExecutionStepState.FAILED,
        KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING,
    )
    TERMINAL_UPLOAD_INSTANCE_STATES = (
        ApprovalInstanceStatus.REJECTED,
        ApprovalInstanceStatus.WITHDRAWN,
        ApprovalInstanceStatus.CANCELLED,
    )
    DELETE_PURGE_STEP_CODES = (
        "delete.fga_purge",
        "delete.minio_purge",
        "delete.es_purge",
        "delete.milvus_purge",
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @classmethod
    def _bounded_limit(cls, limit: int) -> int:
        return max(1, min(int(limit), cls.MAX_BATCH_SIZE))

    async def list_deferred_watchdog_candidates(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_outbox_id: int,
        now: datetime,
        heartbeat_before: datetime,
        limit: int,
    ) -> tuple[list[DeferredWatchdogCandidate], bool]:
        """Return expired current Deferred generations using an outbox-id keyset."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        heartbeat_expired = or_(
            ApprovalOutbox.heartbeat_at <= heartbeat_before,
            and_(
                ApprovalOutbox.heartbeat_at.is_(None),
                ApprovalOutbox.update_time <= heartbeat_before,
            ),
        )
        statement = (
            select(
                ApprovalOutbox.id,
                KnowledgeSpaceFileChangeRequest.id,
                ApprovalOutbox.execution_token,
            )
            .join(
                ApprovalInstance,
                and_(
                    ApprovalInstance.tenant_id == tenant_id,
                    ApprovalInstance.id == ApprovalOutbox.instance_id,
                ),
            )
            .join(
                KnowledgeSpaceFileChangeRequest,
                and_(
                    KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                    KnowledgeSpaceFileChangeRequest.approval_instance_id == ApprovalInstance.id,
                ),
            )
            .where(
                ApprovalOutbox.tenant_id == tenant_id,
                ApprovalOutbox.id > int(after_outbox_id),
                ApprovalOutbox.handler_key == str(scenario_code),
                ApprovalOutbox.status == ApprovalOutboxStatus.DEFERRED,
                ApprovalOutbox.execution_token.is_not(None),
                ApprovalOutbox.execution_token != "",
                ApprovalInstance.scenario_code == str(scenario_code),
                ApprovalInstance.status == ApprovalInstanceStatus.EXECUTING,
                KnowledgeSpaceFileChangeRequest.execution_token == ApprovalOutbox.execution_token,
                KnowledgeSpaceFileChangeRequest.execution_state.in_(
                    (
                        KnowledgeSpaceFileChangeExecutionState.APPLYING,
                        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                    )
                ),
                or_(ApprovalOutbox.deferred_deadline <= now, heartbeat_expired),
            )
            .order_by(ApprovalOutbox.id.asc())
            .limit(bounded_limit + 1)
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        candidates = [
            DeferredWatchdogCandidate(
                outbox_id=int(outbox_id),
                request_id=int(request_id),
                execution_token=str(execution_token),
            )
            for outbox_id, request_id, execution_token in rows[:bounded_limit]
        ]
        return candidates, has_more

    async def list_step_recovery_candidates(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_step_id: int,
        now: datetime,
        limit: int,
    ) -> tuple[list[ExecutionStepRecoveryCandidate], bool]:
        """Return due durable steps bound to the current Deferred token."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        statement = (
            select(
                KnowledgeSpaceFileChangeExecutionStep.id,
                KnowledgeSpaceFileChangeRequest.id,
                ApprovalInstance.id,
                ApprovalOutbox.id,
                KnowledgeSpaceFileChangeRequest.execution_token,
                KnowledgeSpaceFileChangeRequest.execution_state,
            )
            .join(
                KnowledgeSpaceFileChangeRequest,
                and_(
                    KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                    KnowledgeSpaceFileChangeRequest.id == KnowledgeSpaceFileChangeExecutionStep.request_id,
                ),
            )
            .join(
                ApprovalInstance,
                and_(
                    ApprovalInstance.tenant_id == tenant_id,
                    ApprovalInstance.id == KnowledgeSpaceFileChangeRequest.approval_instance_id,
                ),
            )
            .join(
                ApprovalOutbox,
                and_(
                    ApprovalOutbox.tenant_id == tenant_id,
                    ApprovalOutbox.instance_id == ApprovalInstance.id,
                    ApprovalOutbox.execution_token == KnowledgeSpaceFileChangeRequest.execution_token,
                ),
            )
            .where(
                KnowledgeSpaceFileChangeExecutionStep.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeExecutionStep.id > int(after_step_id),
                KnowledgeSpaceFileChangeExecutionStep.state.in_(self.ACTIVE_STEP_STATES),
                or_(
                    KnowledgeSpaceFileChangeExecutionStep.next_retry_at.is_(None),
                    KnowledgeSpaceFileChangeExecutionStep.next_retry_at <= now,
                ),
                KnowledgeSpaceFileChangeExecutionStep.attempt_token == KnowledgeSpaceFileChangeRequest.execution_token,
                KnowledgeSpaceFileChangeRequest.execution_token.is_not(None),
                KnowledgeSpaceFileChangeRequest.execution_token != "",
                KnowledgeSpaceFileChangeRequest.execution_state.in_(
                    (
                        KnowledgeSpaceFileChangeExecutionState.APPLYING,
                        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                    )
                ),
                ApprovalInstance.scenario_code == str(scenario_code),
                ApprovalInstance.status == ApprovalInstanceStatus.EXECUTING,
                ApprovalOutbox.handler_key == str(scenario_code),
                ApprovalOutbox.status == ApprovalOutboxStatus.DEFERRED,
            )
            .order_by(KnowledgeSpaceFileChangeExecutionStep.id.asc())
            .limit(bounded_limit + 1)
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        candidates = [
            ExecutionStepRecoveryCandidate(
                step_id=int(step_id),
                request_id=int(request_id),
                instance_id=int(instance_id),
                outbox_id=int(outbox_id),
                execution_token=str(execution_token),
                execution_state=str(execution_state),
            )
            for step_id, request_id, instance_id, outbox_id, execution_token, execution_state in rows[:bounded_limit]
        ]
        return candidates, has_more

    async def list_cleanup_candidates(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_request_id: int,
        now: datetime,
        limit: int,
    ) -> tuple[list[FileChangeCleanupCandidate], bool, int]:
        """Return terminal stage cleanup or post-cutover delete purge work."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        upload_stage_table = KnowledgeSpaceUploadStage.__table__
        tenant_upload_stages = (
            select(
                upload_stage_table.c.id.label("stage_id"),
                upload_stage_table.c.upload_id.label("upload_id"),
            )
            .where(upload_stage_table.c.tenant_id == tenant_id)
            .subquery("tenant_upload_stages")
        )
        active_delete_purge = exists(
            select(KnowledgeSpaceFileChangeExecutionStep.id).where(
                KnowledgeSpaceFileChangeExecutionStep.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeExecutionStep.request_id == KnowledgeSpaceFileChangeRequest.id,
                KnowledgeSpaceFileChangeExecutionStep.step_code.in_(self.DELETE_PURGE_STEP_CODES),
                KnowledgeSpaceFileChangeExecutionStep.state.in_(self.ACTIVE_STEP_STATES),
                or_(
                    KnowledgeSpaceFileChangeExecutionStep.next_retry_at.is_(None),
                    KnowledgeSpaceFileChangeExecutionStep.next_retry_at <= now,
                ),
            )
        )
        active_delete_deferred = exists(
            select(ApprovalOutbox.id).where(
                ApprovalOutbox.tenant_id == tenant_id,
                ApprovalOutbox.instance_id == ApprovalInstance.id,
                ApprovalOutbox.execution_token == KnowledgeSpaceFileChangeRequest.execution_token,
                ApprovalOutbox.status == ApprovalOutboxStatus.DEFERRED,
            )
        )
        cleanup_retry_requested = KnowledgeSpaceFileChangeRequest.cleanup_state.in_(
            (
                KnowledgeSpaceFileChangeCleanupState.PENDING,
                KnowledgeSpaceFileChangeCleanupState.FAILED,
            )
        )
        terminal_hook_missed = and_(
            KnowledgeSpaceFileChangeRequest.cleanup_state == KnowledgeSpaceFileChangeCleanupState.NONE,
            ApprovalInstance.status.in_(self.TERMINAL_UPLOAD_INSTANCE_STATES),
        )
        terminal_upload = and_(
            KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.UPLOAD,
            KnowledgeSpaceFileChangeRequest.upload_stage_id.is_not(None),
            tenant_upload_stages.c.stage_id.is_not(None),
            or_(cleanup_retry_requested, terminal_hook_missed),
        )
        delete_purge = and_(
            KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.DELETE,
            KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING,
            KnowledgeSpaceFileChangeRequest.execution_token.is_not(None),
            KnowledgeSpaceFileChangeRequest.execution_token != "",
            ApprovalInstance.status == ApprovalInstanceStatus.EXECUTING,
            active_delete_purge,
            active_delete_deferred,
        )
        active_mutation_projection = exists(
            select(KnowledgeSpaceFileChangeFootprint.id).where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeFootprint.request_id == KnowledgeSpaceFileChangeRequest.id,
            )
        )
        mutation_cleanup = and_(
            KnowledgeSpaceFileChangeRequest.action.in_(
                (
                    KnowledgeSpaceFileChangeAction.RENAME,
                    KnowledgeSpaceFileChangeAction.MOVE,
                )
            ),
            KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED,
            KnowledgeSpaceFileChangeRequest.execution_token.is_not(None),
            KnowledgeSpaceFileChangeRequest.execution_token != "",
            ApprovalInstance.status == ApprovalInstanceStatus.EXECUTED,
            active_mutation_projection,
        )
        statement = (
            select(
                KnowledgeSpaceFileChangeRequest.id,
                KnowledgeSpaceFileChangeRequest.action,
                tenant_upload_stages.c.upload_id,
                ApprovalInstance.status,
                KnowledgeSpaceFileChangeRequest.execution_token,
                KnowledgeSpaceFileChangeRequest.execution_checkpoint,
            )
            .join(
                ApprovalInstance,
                and_(
                    ApprovalInstance.tenant_id == tenant_id,
                    ApprovalInstance.id == KnowledgeSpaceFileChangeRequest.approval_instance_id,
                ),
            )
            .outerjoin(
                tenant_upload_stages,
                tenant_upload_stages.c.stage_id == KnowledgeSpaceFileChangeRequest.upload_stage_id,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.id > int(after_request_id),
                ApprovalInstance.scenario_code == str(scenario_code),
                or_(terminal_upload, delete_purge, mutation_cleanup),
            )
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
            .limit(bounded_limit + 1)
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        page_rows = rows[:bounded_limit]
        next_after_request_id = int(page_rows[-1][0]) if page_rows else int(after_request_id)
        candidates: list[FileChangeCleanupCandidate] = []
        for request_id, action, upload_id, instance_status, execution_token, checkpoint in page_rows:
            if action == KnowledgeSpaceFileChangeAction.UPLOAD:
                if upload_id is None:
                    continue
                candidates.append(
                    FileChangeCleanupCandidate(
                        request_id=int(request_id),
                        kind="stage",
                        upload_id=str(upload_id),
                        terminal_action=str(instance_status),
                    )
                )
            elif action == KnowledgeSpaceFileChangeAction.DELETE:
                candidates.append(
                    FileChangeCleanupCandidate(
                        request_id=int(request_id),
                        kind="delete_purge",
                        execution_token=str(execution_token),
                    )
                )
            elif isinstance(checkpoint, dict) and checkpoint.get("mutation_transition_active") is True:
                candidates.append(
                    FileChangeCleanupCandidate(
                        request_id=int(request_id),
                        kind="mutation_cleanup",
                        execution_token=str(execution_token),
                    )
                )
        return candidates, has_more, next_after_request_id

    async def list_expired_orphan_stage_candidates(
        self,
        *,
        tenant_id: int,
        after_stage_id: int,
        now: datetime,
        limit: int,
    ) -> tuple[list[ExpiredOrphanStageCandidate], bool]:
        """Return stage lifecycle work without performing object deletion."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        bound_request_exists = exists(
            select(KnowledgeSpaceFileChangeRequest.id).where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.upload_stage_id == KnowledgeSpaceUploadStage.id,
            )
        )
        statement = (
            select(KnowledgeSpaceUploadStage.id, KnowledgeSpaceUploadStage.upload_id)
            .where(
                KnowledgeSpaceUploadStage.tenant_id == tenant_id,
                KnowledgeSpaceUploadStage.id > int(after_stage_id),
                or_(
                    and_(
                        KnowledgeSpaceUploadStage.state == KnowledgeSpaceUploadStageState.ATTACHING,
                        bound_request_exists,
                    ),
                    and_(
                        KnowledgeSpaceUploadStage.state.in_(
                            (
                                KnowledgeSpaceUploadStageState.UPLOADED,
                                KnowledgeSpaceUploadStageState.CLEANUP_PENDING,
                            )
                        ),
                        KnowledgeSpaceUploadStage.expire_at <= now,
                        ~bound_request_exists,
                    ),
                ),
            )
            .order_by(KnowledgeSpaceUploadStage.id.asc())
            .limit(bounded_limit + 1)
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        return (
            [
                ExpiredOrphanStageCandidate(stage_id=int(stage_id), upload_id=str(upload_id))
                for stage_id, upload_id in rows[:bounded_limit]
            ],
            has_more,
        )
