from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from inspect import isawaitable
from typing import Generic, TypeVar

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.ports.scenario_policy import ApprovalPostCommitCallback
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
    post_commit_effects: list[ApprovalPostCommitCallback]


class FileChangeRequestUnitOfWork:
    """Own one request, footprint, stage, and approval submission transaction."""

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def execute(
        self,
        operation: Callable[
            [FileChangeRequestUowContext, list[ApprovalPostCommitCallback]],
            Awaitable[T],
        ],
    ) -> FileChangeRequestUowResult[T]:
        effects: list[ApprovalPostCommitCallback] = []
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
    async def run_post_commit_effects(effects: list[ApprovalPostCommitCallback]) -> None:
        """Run best-effort effects only after the database transaction closed."""
        for effect in effects:
            try:
                result = effect()
                if isawaitable(result):
                    await result
            except Exception:
                logger.exception("file change post-commit effect failed")


def build_file_change_post_commit_effect(
    callback: Callable[..., Awaitable[None] | None],
    *args,
    **kwargs,
) -> ApprovalPostCommitCallback:
    """Bind a callback without coupling Knowledge to Approval implementation types."""

    async def run() -> None:
        result = callback(*args, **kwargs)
        if isawaitable(result):
            await result

    return run
