"""全文 Outbox 周期分发的可测试领域协作逻辑。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_outbox_repository import (
    KnowledgeFulltextOutboxRepository,
)


async def dispatch_knowledge_fulltext_outbox_async(
    *,
    multi_tenant_enabled: bool,
    repository: KnowledgeFulltextOutboxRepository,
    sender: Callable[..., object],
    now: datetime | None = None,
) -> int:
    constants.ensure_runtime_compatible(multi_tenant_enabled=multi_tenant_enabled)
    rows = await repository.list_dispatchable(
        now=now or datetime.now(),
        limit=constants.KNOWLEDGE_FULLTEXT_DISPATCH_BATCH_SIZE,
    )
    dispatched = 0
    for row in rows:
        sender(
            outbox_id=int(row.id),
            revision=int(row.desired_revision),
        )
        dispatched += 1
    return dispatched
