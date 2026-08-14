"""解析最终状态与全文同步意图的同步事务 owner。"""

from __future__ import annotations

from collections.abc import Callable

from sqlmodel import Session

from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextDesiredAction
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_sync_repository_impl import (
    KnowledgeFulltextOutboxSyncRepositoryImpl,
)

FINAL_DELETE_STATUSES = frozenset(
    {
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
        KnowledgeFileStatus.VIOLATION.value,
    }
)


def fulltext_action_for_parse_status(status: int | None) -> KnowledgeFulltextDesiredAction | None:
    if status == KnowledgeFileStatus.SUCCESS.value:
        return KnowledgeFulltextDesiredAction.SYNC_CURRENT
    if status in FINAL_DELETE_STATUSES:
        return KnowledgeFulltextDesiredAction.DELETE_CURRENT
    return None


def persist_parse_result_with_fulltext_intent(
    file: KnowledgeFile,
    *,
    trigger_type: str = "parse_finalized",
    multi_tenant_enabled: bool | None = None,
    session_factory: Callable[[], Session] = get_sync_db_session,
) -> None:
    from bisheng.common.services.config_service import settings

    resolved_multi_tenant = settings.multi_tenant.enabled if multi_tenant_enabled is None else multi_tenant_enabled
    constants.ensure_runtime_compatible(multi_tenant_enabled=resolved_multi_tenant)
    action = fulltext_action_for_parse_status(file.status)
    with session_factory() as session:
        session.add(file)
        if action is not None:
            KnowledgeFulltextOutboxSyncRepositoryImpl(session).request_file_sync(
                file_id=int(file.id),
                knowledge_id=int(file.knowledge_id),
                desired_action=action,
                trigger_type=trigger_type,
                tenant_id=int(file.tenant_id or 1),
                max_retries=constants.KNOWLEDGE_FULLTEXT_MAX_RETRIES,
            )
        session.commit()
        session.refresh(file)
