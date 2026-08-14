"""业务生命周期事务中的全文同步意图写入器。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import event
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.services.config_service import settings
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextDesiredAction,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (
    KnowledgeFulltextOutboxRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_sync_repository_impl import (
    KnowledgeFulltextOutboxSyncRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_event_service import (
    KnowledgeFulltextEventService,
)


@dataclass(frozen=True)
class KnowledgeFulltextFileRef:
    file_id: int
    knowledge_id: int | None
    tenant_id: int = 1


_TRACKED_REFS_KEY = "knowledge_fulltext_tracked_file_refs"
_TRACKER_INSTALLED_KEY = "knowledge_fulltext_tracker_installed"


async def _event_service(
    session: AsyncSession,
    *,
    multi_tenant_enabled: bool | None,
) -> KnowledgeFulltextEventService:
    resolved_multi_tenant = settings.multi_tenant.enabled if multi_tenant_enabled is None else multi_tenant_enabled
    return KnowledgeFulltextEventService(
        KnowledgeFulltextOutboxRepositoryImpl(session),
        multi_tenant_enabled=resolved_multi_tenant,
        max_retries=constants.KNOWLEDGE_FULLTEXT_MAX_RETRIES,
    )


async def request_file_sync_intents(
    session: AsyncSession,
    files: Iterable[KnowledgeFulltextFileRef],
    *,
    trigger_type: str,
    multi_tenant_enabled: bool | None = None,
) -> None:
    service = await _event_service(
        session,
        multi_tenant_enabled=multi_tenant_enabled,
    )
    for item in _dedupe_file_refs(files):
        if item.knowledge_id is None:
            raise ValueError("knowledge_id is required for file sync intent")
        await service.request_file_sync(
            file_id=item.file_id,
            knowledge_id=item.knowledge_id,
            trigger_type=trigger_type,
            tenant_id=item.tenant_id,
        )


async def request_file_delete_intents(
    session: AsyncSession,
    files: Iterable[KnowledgeFulltextFileRef],
    *,
    trigger_type: str,
    multi_tenant_enabled: bool | None = None,
) -> None:
    service = await _event_service(
        session,
        multi_tenant_enabled=multi_tenant_enabled,
    )
    for item in _dedupe_file_refs(files):
        await service.request_file_delete(
            file_id=item.file_id,
            knowledge_id=item.knowledge_id,
            trigger_type=trigger_type,
            tenant_id=item.tenant_id,
        )


async def request_knowledge_intent(
    session: AsyncSession,
    *,
    knowledge_id: int,
    tenant_id: int,
    trigger_type: str,
    delete_scope: bool = False,
    multi_tenant_enabled: bool | None = None,
) -> None:
    service = await _event_service(
        session,
        multi_tenant_enabled=multi_tenant_enabled,
    )
    if delete_scope:
        await service.request_knowledge_delete(
            knowledge_id=knowledge_id,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )
    else:
        await service.request_knowledge_fanout(
            knowledge_id=knowledge_id,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )


def _dedupe_file_refs(
    files: Iterable[KnowledgeFulltextFileRef],
) -> list[KnowledgeFulltextFileRef]:
    by_id: dict[int, KnowledgeFulltextFileRef] = {}
    for item in files:
        if item.file_id <= 0 or item.tenant_id <= 0:
            raise ValueError("file_id and tenant_id must be positive")
        by_id[item.file_id] = item
    return [by_id[file_id] for file_id in sorted(by_id)]


def request_file_sync_intents_sync(
    session: Session,
    files: Iterable[KnowledgeFulltextFileRef],
    *,
    trigger_type: str,
    multi_tenant_enabled: bool | None = None,
) -> None:
    resolved_multi_tenant = settings.multi_tenant.enabled if multi_tenant_enabled is None else multi_tenant_enabled
    constants.ensure_runtime_compatible(multi_tenant_enabled=resolved_multi_tenant)
    repository = KnowledgeFulltextOutboxSyncRepositoryImpl(session)
    for item in _dedupe_file_refs(files):
        if item.knowledge_id is None:
            raise ValueError("knowledge_id is required for file sync intent")
        repository.request_file_sync(
            file_id=item.file_id,
            knowledge_id=item.knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type=trigger_type,
            tenant_id=item.tenant_id,
            max_retries=constants.KNOWLEDGE_FULLTEXT_MAX_RETRIES,
        )


def track_fulltext_file_changes(session: AsyncSession) -> None:
    """记录该 AsyncSession 中经过 flush 的文件变化，供事务 owner 提交前收敛。"""
    sync_session = session.sync_session
    if sync_session.info.get(_TRACKER_INSTALLED_KEY):
        return
    sync_session.info[_TRACKER_INSTALLED_KEY] = True

    def after_flush(tracked_session, _flush_context) -> None:
        from bisheng.knowledge.domain.models.knowledge_file import (
            FileType,
            KnowledgeFile,
        )

        refs: dict[int, KnowledgeFulltextFileRef] = tracked_session.info.setdefault(
            _TRACKED_REFS_KEY,
            {},
        )
        for item in tracked_session.new | tracked_session.dirty | tracked_session.deleted:
            if not isinstance(item, KnowledgeFile) or item.file_type != FileType.FILE.value:
                continue
            if item.id is None:
                continue
            refs[int(item.id)] = KnowledgeFulltextFileRef(
                file_id=int(item.id),
                knowledge_id=int(item.knowledge_id),
                tenant_id=int(item.tenant_id or 1),
            )

    def after_rollback(tracked_session) -> None:
        tracked_session.info.pop(_TRACKED_REFS_KEY, None)

    event.listen(sync_session, "after_flush", after_flush)
    event.listen(sync_session, "after_rollback", after_rollback)


async def commit_tracked_fulltext_changes(
    session: AsyncSession,
    *,
    trigger_type: str,
    multi_tenant_enabled: bool | None = None,
) -> None:
    await session.flush()
    refs = list(session.sync_session.info.pop(_TRACKED_REFS_KEY, {}).values())
    await request_file_sync_intents(
        session,
        refs,
        trigger_type=trigger_type,
        multi_tenant_enabled=multi_tenant_enabled,
    )
    await session.commit()
