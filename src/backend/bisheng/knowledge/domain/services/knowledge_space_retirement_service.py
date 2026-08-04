"""知识空间退役状态机。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)


class KnowledgeSpaceRetirementError(RuntimeError):
    """知识空间已不允许进入或继续分发生命周期。"""


@dataclass(frozen=True)
class KnowledgeSpaceRetirementResult:
    space_id: int
    tenant_id: int
    entry_ids: list[int]
    document_ids: list[int]
    idempotent: bool = False


class KnowledgeSpaceRetirementService:
    """在短事务中关闭空间，并把相关分发入口转成不可逆清理态。"""

    def __init__(self, *, session: AsyncSession):
        self.session = session

    @staticmethod
    def _mark_entry(entry: KnowledgeFile, status: KnowledgeFileEntryStatus) -> None:
        entry.entry_status = status.value
        entry.desired_entry_generation = int(entry.desired_entry_generation or 0) + 1
        entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        entry.projection_next_retry_at = None
        entry.projection_lease_owner = None
        entry.projection_lease_until = None

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
                entry_ids=[],
                document_ids=[],
                idempotent=True,
            )
        if space.state != KnowledgeState.PUBLISHED.value:
            await self.session.rollback()
            raise KnowledgeSpaceRetirementError("knowledge space is not published")

        local_result = await self.session.execute(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == space_id,
                KnowledgeFile.reference_document_id.is_not(None),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        local_entries = list(local_result.scalars().all())
        owned_result = await self.session.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.knowledge_id == space_id,
            )
        )
        document_ids = sorted(
            {
                *(int(item.reference_document_id) for item in local_entries),
                *(int(item) for item in owned_result.scalars().all()),
            }
        )
        document_result = await self.session.execute(
            select(KnowledgeDocument)
            .where(col(KnowledgeDocument.id).in_(document_ids))
            .order_by(KnowledgeDocument.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        documents = {int(item.id): item for item in document_result.scalars().all()}
        entry_ids: set[int] = set()

        for document_id in document_ids:
            document = documents.get(document_id)
            if document is None or int(document.tenant_id or 0) != int(tenant_id):
                continue
            entries_result = await self.session.execute(
                select(KnowledgeFile)
                .where(KnowledgeFile.reference_document_id == document_id)
                .order_by(KnowledgeFile.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            entries = list(entries_result.scalars().all())
            manager_is_retiring = int(document.knowledge_id) == int(space_id)
            if manager_is_retiring:
                document.lifecycle_status = KnowledgeDocumentLifecycleStatus.DELETING.value
            for entry in entries:
                if int(entry.knowledge_id) == int(space_id):
                    self._mark_entry(entry, KnowledgeFileEntryStatus.DELETING)
                elif (
                    manager_is_retiring
                    and entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
                    and entry.entry_type
                    in {
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    }
                ):
                    self._mark_entry(entry, KnowledgeFileEntryStatus.INVALID)
                elif manager_is_retiring and entry.entry_status in {
                    KnowledgeFileEntryStatus.PREPARING.value,
                    KnowledgeFileEntryStatus.DELETING.value,
                }:
                    self._mark_entry(entry, KnowledgeFileEntryStatus.DELETING)
                else:
                    continue
                entry_ids.add(int(entry.id))

        space.state = KnowledgeState.DELETING.value
        await self.session.commit()
        return KnowledgeSpaceRetirementResult(
            space_id=space_id,
            tenant_id=tenant_id,
            entry_ids=sorted(entry_ids),
            document_ids=document_ids,
        )
