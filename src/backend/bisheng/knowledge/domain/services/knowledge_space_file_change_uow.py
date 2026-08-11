from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Generic, TypeVar

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.services.approval_uow import ApprovalPostCommitEffect
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    KnowledgeSpaceFileChangeFootprintRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)

T = TypeVar("T")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(slots=True)
class FileChangeRequestUowContext:
    """Repositories bound to the one transaction that owns a request bundle."""

    session: AsyncSession
    requests: KnowledgeSpaceFileChangeRequestRepository
    footprints: KnowledgeSpaceFileChangeFootprintRepository
    upload_stages: KnowledgeSpaceUploadStageRepository


@dataclass(slots=True)
class FileChangeRequestUowResult(Generic[T]):
    value: T
    post_commit_effects: list[ApprovalPostCommitEffect]


class FileChangeRequestUnitOfWork:
    """Own the request + footprint + ApprovalGate atomic commit boundary."""

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def execute(
        self,
        operation: Callable[
            [FileChangeRequestUowContext, list[ApprovalPostCommitEffect]],
            Awaitable[T],
        ],
    ) -> FileChangeRequestUowResult[T]:
        effects: list[ApprovalPostCommitEffect] = []
        async with self.session_factory() as session:
            async with session.begin():
                context = FileChangeRequestUowContext(
                    session=session,
                    requests=KnowledgeSpaceFileChangeRequestRepository(session),
                    footprints=KnowledgeSpaceFileChangeFootprintRepository(session),
                    upload_stages=KnowledgeSpaceUploadStageRepository(session),
                )
                value = await operation(context, effects)
        return FileChangeRequestUowResult(value=value, post_commit_effects=effects)

    @staticmethod
    async def run_post_commit_effects(effects: list[ApprovalPostCommitEffect]) -> None:
        """Run best-effort effects only after the database transaction closed."""
        for effect in effects:
            try:
                await effect.run()
            except Exception:
                logger.exception("file change post-commit effect failed: {}", effect.name)
