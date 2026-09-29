"""与文档生命周期共用事务的回收存取。"""

from collections.abc import Iterable

from sqlmodel import col, delete, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.config import Config
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_recycle_repository import (
    DocumentRecycleContext,
    KnowledgeDocumentRecycleRepository,
    RecycleSnapshotContext,
)


class KnowledgeDocumentRecycleRepositoryImpl(
    BaseRepositoryImpl[KnowledgeRecycleItem, int], KnowledgeDocumentRecycleRepository
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeRecycleItem)

    async def load_document(self, document_id: int) -> DocumentRecycleContext:
        document = await KnowledgeDocumentRepositoryImpl(self.session).find_by_id_for_update(document_id)
        files = KnowledgeFileRepositoryImpl(self.session)
        entries = await files.find_distribution_entries_by_document_id(document_id, for_update=True)
        versions = await KnowledgeDocumentVersionRepositoryImpl(self.session).find_by_document_id(document_id)
        physical = await files.find_by_ids_for_update([int(version.knowledge_file_id) for version in versions])
        return document, entries, versions, physical

    async def snapshot_context(self, files: Iterable[KnowledgeFile]) -> RecycleSnapshotContext:
        files = list(files)
        config = (
            (await self.session.execute(select(Config).where(Config.key == "knowledge_recycle_bin.retention_days")))
            .scalars()
            .first()
        )
        try:
            days = max(1, min(365, int(config.value))) if config else 7
        except (ValueError, TypeError):
            days = 7
        space_ids = sorted({int(file.knowledge_id) for file in files})
        spaces = (
            (
                await self.session.execute(
                    select(Knowledge).where(col(Knowledge.id).in_(space_ids)).order_by(Knowledge.id).with_for_update()
                )
            )
            .scalars()
            .all()
        )
        scopes = (
            await self.session.execute(
                select(KnowledgeSpaceScope.space_id, KnowledgeSpaceScope.level).where(
                    col(KnowledgeSpaceScope.space_id).in_(space_ids)
                )
            )
        ).all()
        folder_ids = sorted(
            {int(part) for file in files for part in str(file.file_level_path or "").split("/") if part.isdigit()}
        )
        folders = await KnowledgeFileRepositoryImpl(self.session).find_by_ids_for_update(folder_ids)
        return (
            days,
            {int(space.id): space for space in spaces},
            {int(scope.space_id): scope.level for scope in scopes},
            {int(folder.id): folder for folder in folders},
        )

    async def document_items(self, document_id: int) -> list[KnowledgeRecycleItem]:
        return list(
            (
                await self.session.execute(
                    select(KnowledgeRecycleItem).where(KnowledgeRecycleItem.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )

    async def remove_document_items(self, document_id: int) -> None:
        await self.session.execute(delete(KnowledgeRecycleItem).where(KnowledgeRecycleItem.document_id == document_id))

    async def restore_conflicts(self, manager: KnowledgeFile, knowledge_id: int) -> list[int]:
        predicates = [KnowledgeFile.file_name == manager.file_name]
        if manager.md5:
            predicates.append(KnowledgeFile.md5 == manager.md5)
        return list(
            (
                await self.session.execute(
                    select(KnowledgeFile.id)
                    .where(
                        KnowledgeFile.knowledge_id == knowledge_id,
                        KnowledgeFile.file_type == 1,
                        KnowledgeFile.id != manager.id,
                        col(KnowledgeFile.deleted_at).is_(None),
                        or_(*predicates),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
