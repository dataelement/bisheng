from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

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
class ExecutionWatchdogCandidate:
    request_id: int
    execution_token: str


@dataclass(frozen=True, slots=True)
class ExecutionStepRecoveryCandidate:
    step_id: int
    request_id: int
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

    async def list_watchdog_candidates(
        self,
        *,
        tenant_id: int,
        after_request_id: int,
        heartbeat_before: datetime,
        limit: int,
    ) -> tuple[list[ExecutionWatchdogCandidate], bool]:
        """Return expired current Knowledge generations using a request-id keyset."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        statement = (
            select(
                KnowledgeSpaceFileChangeRequest.id,
                KnowledgeSpaceFileChangeRequest.execution_token,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.id > int(after_request_id),
                KnowledgeSpaceFileChangeRequest.execution_token.is_not(None),
                KnowledgeSpaceFileChangeRequest.execution_token != "",
                KnowledgeSpaceFileChangeRequest.execution_state.in_(
                    (
                        KnowledgeSpaceFileChangeExecutionState.APPLYING,
                        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                    )
                ),
                KnowledgeSpaceFileChangeRequest.update_time <= heartbeat_before,
            )
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
            .limit(bounded_limit + 1)
        )
        rows = list((await self.session.exec(statement)).all())
        has_more = len(rows) > bounded_limit
        candidates = [
            ExecutionWatchdogCandidate(
                request_id=int(request_id),
                execution_token=str(execution_token),
            )
            for request_id, execution_token in rows[:bounded_limit]
        ]
        return candidates, has_more

    async def list_step_recovery_candidates(
        self,
        *,
        tenant_id: int,
        after_step_id: int,
        now: datetime,
        limit: int,
    ) -> tuple[list[ExecutionStepRecoveryCandidate], bool]:
        """Return due durable steps bound to the current Knowledge token."""

        tenant_id = int(tenant_id)
        bounded_limit = self._bounded_limit(limit)
        statement = (
            select(
                KnowledgeSpaceFileChangeExecutionStep.id,
                KnowledgeSpaceFileChangeRequest.id,
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
                execution_token=str(execution_token),
                execution_state=str(execution_state),
            )
            for step_id, request_id, execution_token, execution_state in rows[:bounded_limit]
        ]
        return candidates, has_more

    async def list_cleanup_candidates(
        self,
        *,
        tenant_id: int,
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
        cleanup_retry_requested = KnowledgeSpaceFileChangeRequest.cleanup_state.in_(
            (
                KnowledgeSpaceFileChangeCleanupState.PENDING,
                KnowledgeSpaceFileChangeCleanupState.FAILED,
            )
        )
        terminal_upload = and_(
            KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.UPLOAD,
            KnowledgeSpaceFileChangeRequest.upload_stage_id.is_not(None),
            tenant_upload_stages.c.stage_id.is_not(None),
            KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.CLOSED,
            cleanup_retry_requested,
        )
        delete_purge = and_(
            KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.DELETE,
            KnowledgeSpaceFileChangeRequest.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING,
            KnowledgeSpaceFileChangeRequest.execution_token.is_not(None),
            KnowledgeSpaceFileChangeRequest.execution_token != "",
            active_delete_purge,
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
            active_mutation_projection,
        )
        statement = (
            select(
                KnowledgeSpaceFileChangeRequest.id,
                KnowledgeSpaceFileChangeRequest.action,
                tenant_upload_stages.c.upload_id,
                KnowledgeSpaceFileChangeRequest.result_snapshot,
                KnowledgeSpaceFileChangeRequest.execution_token,
                KnowledgeSpaceFileChangeRequest.execution_checkpoint,
            )
            .outerjoin(
                tenant_upload_stages,
                tenant_upload_stages.c.stage_id == KnowledgeSpaceFileChangeRequest.upload_stage_id,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.id > int(after_request_id),
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
        for request_id, action, upload_id, result_snapshot, execution_token, checkpoint in page_rows:
            if action == KnowledgeSpaceFileChangeAction.UPLOAD:
                if upload_id is None:
                    continue
                candidates.append(
                    FileChangeCleanupCandidate(
                        request_id=int(request_id),
                        kind="stage",
                        upload_id=str(upload_id),
                        terminal_action=str((result_snapshot or {}).get("decision_action") or "closed"),
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
