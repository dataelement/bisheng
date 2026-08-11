from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_compensation_repository import (
    DeferredWatchdogCandidate,
    ExecutionStepRecoveryCandidate,
    ExpiredOrphanStageCandidate,
    FileChangeCleanupCandidate,
    KnowledgeSpaceFileChangeCompensationRepository,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
CandidateT = TypeVar("CandidateT")


@dataclass(frozen=True, slots=True)
class CompensationPage(Generic[CandidateT]):
    items: list[CandidateT]
    has_more: bool
    next_after_id: int


class KnowledgeSpaceFileChangeCompensationService:
    """Expose bounded F046 recovery pages without leaking ORM into workers."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        now: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None),
        heartbeat_timeout: timedelta = timedelta(minutes=15),
    ) -> None:
        self.session_factory = session_factory
        self.now = now
        self.heartbeat_timeout = heartbeat_timeout

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        normalized = int(tenant_id)
        current = get_current_tenant_id()
        if normalized <= 0 or current is None or int(current) != normalized:
            raise ValueError("F046 compensation scan requires the matching tenant context")
        return normalized

    async def list_deferred_watchdog_page(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_outbox_id: int,
        limit: int,
    ) -> CompensationPage[DeferredWatchdogCandidate]:
        tenant_id = self._require_tenant(tenant_id)
        now = self.now()
        async with self.session_factory() as session:
            items, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
                session
            ).list_deferred_watchdog_candidates(
                tenant_id=tenant_id,
                scenario_code=str(scenario_code),
                after_outbox_id=int(after_outbox_id),
                now=now,
                heartbeat_before=now - self.heartbeat_timeout,
                limit=int(limit),
            )
        return CompensationPage(
            items=items,
            has_more=has_more,
            next_after_id=items[-1].outbox_id if items else int(after_outbox_id),
        )

    async def list_step_recovery_page(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_step_id: int,
        limit: int,
    ) -> CompensationPage[ExecutionStepRecoveryCandidate]:
        tenant_id = self._require_tenant(tenant_id)
        async with self.session_factory() as session:
            items, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
                session
            ).list_step_recovery_candidates(
                tenant_id=tenant_id,
                scenario_code=str(scenario_code),
                after_step_id=int(after_step_id),
                now=self.now(),
                limit=int(limit),
            )
        return CompensationPage(
            items=items,
            has_more=has_more,
            next_after_id=items[-1].step_id if items else int(after_step_id),
        )

    async def list_cleanup_page(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
        after_request_id: int,
        limit: int,
    ) -> CompensationPage[FileChangeCleanupCandidate]:
        tenant_id = self._require_tenant(tenant_id)
        async with self.session_factory() as session:
            items, has_more, next_after_id = await KnowledgeSpaceFileChangeCompensationRepository(
                session
            ).list_cleanup_candidates(
                tenant_id=tenant_id,
                scenario_code=str(scenario_code),
                after_request_id=int(after_request_id),
                now=self.now(),
                limit=int(limit),
            )
        return CompensationPage(
            items=items,
            has_more=has_more,
            next_after_id=next_after_id,
        )

    async def list_expired_orphan_stage_page(
        self,
        *,
        tenant_id: int,
        after_stage_id: int,
        limit: int,
    ) -> CompensationPage[ExpiredOrphanStageCandidate]:
        tenant_id = self._require_tenant(tenant_id)
        async with self.session_factory() as session:
            items, has_more = await KnowledgeSpaceFileChangeCompensationRepository(
                session
            ).list_expired_orphan_stage_candidates(
                tenant_id=tenant_id,
                after_stage_id=int(after_stage_id),
                now=self.now(),
                limit=int(limit),
            )
        return CompensationPage(
            items=items,
            has_more=has_more,
            next_after_id=items[-1].stage_id if items else int(after_stage_id),
        )
