"""KnowledgeDocumentVersionRepository implementation."""
from typing import List, Optional

from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_version_schema import CanonicalVersionLinkResult


class KnowledgeDocumentVersionRepositoryImpl(
    BaseRepositoryImpl[KnowledgeDocumentVersion, int],
    KnowledgeDocumentVersionRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeDocumentVersion)

    async def link_independent_managers(
        self,
        *,
        tenant_id: int,
        space_id: int,
        current_file_id: int,
        source_document_id: int,
        target_document_id: int,
        source_version_id: int,
        target_version_id: int,
        source_generation: int,
        target_generation: int,
    ) -> CanonicalVersionLinkResult:
        from bisheng.common.errcode.knowledge_space import (
            KnowledgeDocumentEntryConflictError,
            VersionLinkSourceMultiVersionError,
        )

        def refuse() -> None:
            raise KnowledgeDocumentEntryConflictError()

        space = (
            (
                await self.session.execute(
                    select(Knowledge)
                    .where(Knowledge.id == space_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .first()
        )
        if (
            space is None
            or space.tenant_id != tenant_id
            or space.type != KnowledgeTypeEnum.SPACE.value
            or space.state != KnowledgeState.PUBLISHED.value
        ):
            refuse()
        document_ids = sorted({source_document_id, target_document_id})
        documents = (
            (
                await self.session.execute(
                    select(KnowledgeDocument)
                    .where(col(KnowledgeDocument.id).in_(document_ids))
                    .order_by(KnowledgeDocument.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        doc_map = {int(doc.id): doc for doc in documents}
        target = doc_map.get(target_document_id)
        if (
            target is None
            or target.tenant_id != tenant_id
            or target.knowledge_id != space_id
            or target.lifecycle_status != "active"
        ):
            refuse()
        versions = (
            (
                await self.session.execute(
                    select(KnowledgeDocumentVersion)
                    .where(col(KnowledgeDocumentVersion.document_id).in_(document_ids))
                    .order_by(KnowledgeDocumentVersion.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        file_ids = {int(version.knowledge_file_id) for version in versions} | {current_file_id}
        files = (
            (
                await self.session.execute(
                    select(KnowledgeFile)
                    .where(
                        or_(
                            col(KnowledgeFile.id).in_(sorted(file_ids)),
                            col(KnowledgeFile.reference_document_id).in_(document_ids),
                        )
                    )
                    .order_by(KnowledgeFile.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        file_map = {int(file.id): file for file in files}
        current = file_map.get(current_file_id)
        current_version = next((v for v in versions if v.knowledge_file_id == current_file_id), None)
        if (
            current is None
            or current_version is None
            or current.tenant_id != tenant_id
            or current.knowledge_id != space_id
            or current.file_type != 1
            or current.status != 2
            or current.deleted_at is not None
            or current.entry_type != "manager"
            or current.entry_status != "active"
        ):
            refuse()
        # 重复请求只读返回, 不生成新版本、墓碑或代次。
        if (
            current.reference_document_id == target_document_id
            and current_version.document_id == target_document_id
            and current_version.is_primary
            and target.primary_version_id == current_version.id
        ):
            return CanonicalVersionLinkResult(
                document_id=target_document_id,
                new_version_no=current_version.version_no,
                previous_manager_file_id=current_file_id,
                idempotent=True,
            )
        source = doc_map.get(source_document_id)
        source_chain = [v for v in versions if v.document_id == source_document_id]
        target_chain = [v for v in versions if v.document_id == target_document_id]
        if len(source_chain) > 1:
            raise VersionLinkSourceMultiVersionError()
        if (
            source is None
            or source_document_id == target_document_id
            or source.tenant_id != tenant_id
            or source.knowledge_id != space_id
            or source.lifecycle_status != "active"
            or source.predecessor_logic_file_id is not None
            or target.predecessor_logic_file_id is not None
            or current.reference_document_id != source_document_id
            or current_version.document_id != source_document_id
            or len(source_chain) != 1
            or not current_version.is_primary
            or source.primary_version_id != current_version.id
            or current_version.id != source_version_id
            or target.primary_version_id != target_version_id
            or source.content_generation != source_generation
            or target.content_generation != target_generation
        ):
            refuse()
        primaries = [v for v in target_chain if v.is_primary]
        if len(primaries) != 1 or primaries[0].id != target.primary_version_id:
            refuse()
        previous = file_map.get(int(primaries[0].knowledge_file_id))
        if previous is None:
            refuse()
        for document, manager in ((source, current), (target, previous)):
            entries = [file for file in files if file.reference_document_id == document.id]
            if (
                len(entries) != 1
                or entries[0].id != manager.id
                or manager.tenant_id != tenant_id
                or manager.knowledge_id != space_id
                or manager.file_type != 1
                or manager.status != 2
                or manager.deleted_at is not None
                or manager.entry_type != "manager"
                or manager.entry_status != "active"
                or manager.projection_status != "ready"
                or manager.projection_lease_owner is not None
                or manager.projection_lease_until is not None
                or manager.desired_content_generation != document.content_generation
                or manager.applied_content_generation < manager.desired_content_generation
                or manager.applied_entry_generation < manager.desired_entry_generation
            ):
                refuse()
        target_files = [file_map.get(int(v.knowledge_file_id)) for v in target_chain]
        if any(file is None or file.tenant_id != tenant_id or file.knowledge_id != space_id for file in target_files):
            refuse()
        if current.md5 and any(file.md5 == current.md5 for file in target_files):
            refuse()

        origin_uploader = previous.original_uploader_id or previous.user_id
        origin_space = previous.original_knowledge_id or previous.knowledge_id
        previous.original_uploader_id = origin_uploader
        previous.original_knowledge_id = origin_space
        previous.reference_document_id = None
        previous.entry_type = previous.entry_status = None
        previous.projection_previous_file_id = None
        self.session.add(previous)
        # 先释放旧manager唯一键, 避免文件ID顺序不同导致同事务内唯一约束冲突。
        await self.session.flush()

        new_no = max(v.version_no for v in target_chain) + 1
        for version in target_chain:
            version.is_primary = False
            self.session.add(version)
        current_version.document_id = target_document_id
        current_version.version_no = new_no
        current_version.is_primary = True
        self.session.add(current_version)
        generation = max(int(source.content_generation), int(target.content_generation)) + 1
        target.primary_version_id = current_version.id
        target.content_generation = generation
        target.file_level_path = current.file_level_path
        target.level = current.level
        current.reference_document_id = target_document_id
        current.original_uploader_id = origin_uploader
        current.original_knowledge_id = origin_space
        current.belonging_organization_id = previous.belonging_organization_id
        current.similar_status = 2
        current.projection_previous_file_id = previous.id
        current.desired_content_generation = generation
        current.applied_content_generation = 0
        current.desired_entry_generation += 1
        current.applied_entry_generation = 0
        current.projection_status = "pending"
        current.projection_retry_count = 0
        current.projection_next_retry_at = current.projection_last_error = None

        source.primary_version_id = None
        source.lifecycle_status = "invalid"
        source.content_generation += 1
        cleanup = KnowledgeFile(
            tenant_id=tenant_id,
            knowledge_id=space_id,
            file_name=current.file_name,
            file_type=1,
            status=2,
            file_size=0,
            object_name=None,
            reference_document_id=source_document_id,
            entry_type="projection_tombstone",
            entry_status="deleting",
            projection_status="pending",
            projection_previous_file_id=current_file_id,
            desired_content_generation=source.content_generation,
            desired_entry_generation=1,
        )
        self.session.add_all([current, source, target, cleanup])
        await self.session.flush()
        return CanonicalVersionLinkResult(
            document_id=target_document_id,
            new_version_no=new_no,
            previous_manager_file_id=int(previous.id),
            cleanup_entry_id=int(cleanup.id),
        )

    async def find_by_document_id(self, document_id: int) -> List[KnowledgeDocumentVersion]:
        stmt = (
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_no)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_primary(self, document_id: int) -> Optional[KnowledgeDocumentVersion]:
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document_id,
            KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_knowledge_file_id(
        self, knowledge_file_id: int
    ) -> Optional[KnowledgeDocumentVersion]:
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.knowledge_file_id == knowledge_file_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def next_version_no(self, document_id: int) -> int:
        stmt = select(func.max(KnowledgeDocumentVersion.version_no)).where(
            KnowledgeDocumentVersion.document_id == document_id
        )
        result = await self.session.execute(stmt)
        current_max = result.scalar()
        if current_max is None:
            return 1
        return int(current_max) + 1

    async def find_non_primary_file_ids(
        self, document_ids: Optional[List[int]] = None
    ) -> List[int]:
        stmt = select(KnowledgeDocumentVersion.knowledge_file_id).where(
            KnowledgeDocumentVersion.is_primary == False,  # noqa: E712
        )
        if document_ids is not None:
            stmt = stmt.where(col(KnowledgeDocumentVersion.document_id).in_(document_ids))
        result = await self.session.execute(stmt)
        return [int(row) for row in result.scalars().all()]

    async def find_primary_versions_by_file_ids(
        self, file_ids: List[int]
    ) -> List[KnowledgeDocumentVersion]:
        """Return primary version rows for the given file ids.

        Each returned row corresponds to one visible page item.  We filter on
        is_primary=True so we only pull the row that is currently shown, and
        we can look up version_no for each file in O(1) after loading.
        """
        if not file_ids:
            return []
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
            col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_non_primary_file_ids_by_knowledge_ids(
        self, knowledge_ids: List[int]
    ) -> List[int]:
        """Return knowledge_file_id of all non-primary version rows whose
        parent document belongs to any of the given knowledge_ids.

        Empty knowledge_ids -> []. JOINs knowledge_document on document_id.
        """
        if not knowledge_ids:
            return []
        stmt = (
            select(KnowledgeDocumentVersion.knowledge_file_id)
            .join(
                KnowledgeDocument,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
            )
            .where(
                KnowledgeDocumentVersion.is_primary == False,  # noqa: E712
                col(KnowledgeDocument.knowledge_id).in_(knowledge_ids),
            )
        )
        result = await self.session.execute(stmt)
        return [int(row) for row in result.scalars().all()]
