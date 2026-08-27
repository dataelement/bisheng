"""知识空间退役状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    request_knowledge_intent,
)


class KnowledgeSpaceRetirementError(RuntimeError):
    """知识空间已不允许进入或继续分发生命周期。"""


@dataclass(frozen=True)
class KnowledgeSpaceRetirementResult:
    space_id: int
    tenant_id: int
    entry_ids: list[int] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)
    idempotent: bool = False


class KnowledgeSpaceRetirementService:
    """Flip the space to retiring; distribution entries are swept asynchronously.

    Only the space's own state changes here. Retirement used to decide every
    entry's fate inside this same short transaction, which does not work: a
    manager rollback needs cross-space locks and a permission pre-write, and it
    marked shortcuts for deletion without first relinking the chain — so once
    the projection worker removed those rows, documents were left pointing at
    ids that no longer existed and could never be deleted again. F098's
    container cleanup now walks the entries one by one under exactly the same
    rules a single-file delete follows.
    """

    def __init__(self, *, session: AsyncSession):
        self.session = session

    async def retire(self, *, tenant_id: int, space_id: int) -> KnowledgeSpaceRetirementResult:
        space_result = await self.session.execute(
            select(Knowledge)
            .where(Knowledge.id == space_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        space = space_result.scalars().first()
        if space is None or int(space.tenant_id or 0) != int(tenant_id):
            raise KnowledgeSpaceRetirementError("knowledge space does not exist")
        if space.state == KnowledgeState.DELETING.value:
            await self.session.rollback()
            return KnowledgeSpaceRetirementResult(
                space_id=space_id,
                tenant_id=tenant_id,
                idempotent=True,
            )
        if space.state != KnowledgeState.PUBLISHED.value:
            await self.session.rollback()
            raise KnowledgeSpaceRetirementError("knowledge space is not published")

        space.state = KnowledgeState.DELETING.value
        await request_knowledge_intent(
            self.session,
            knowledge_id=space_id,
            tenant_id=tenant_id,
            trigger_type="knowledge_space_retired",
            delete_scope=True,
        )
        await self.session.commit()
        return KnowledgeSpaceRetirementResult(
            space_id=space_id,
            tenant_id=tenant_id,
        )
