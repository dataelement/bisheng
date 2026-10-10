from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    FolderDescendantStatusFlags,
    KnowledgeFileRepository,
)


class KnowledgeFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)

    async def find_by_ids(self, entity_ids: list[int]) -> Sequence[KnowledgeFile]:
        """Fetch multiple KnowledgeFile rows by id list.

        Overrides the base class to use session.execute() so this impl works
        with both SQLModel AsyncSession and plain SQLAlchemy AsyncSession (tests).
        """
        if not entity_ids:
            return []
        query = select(KnowledgeFile).where(col(KnowledgeFile.id).in_(entity_ids))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_by_id(self, entity_id: int):
        """Fetch a single KnowledgeFile by id.

        Override: bypass SQLAlchemy identity map so reads after bulk UPDATE
        statements return fresh data (matches KnowledgeDocumentRepositoryImpl pattern).
        """
        stmt = select(KnowledgeFile).where(KnowledgeFile.id == entity_id)
        result = await self.session.execute(stmt.execution_options(populate_existing=True))
        return result.scalars().first()

    async def find_main_version_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS files in a space that are the primary version of their logical document.

        Joins KnowledgeDocumentVersion to filter only rows where is_primary=True,
        then applies the SUCCESS status filter. Optionally excludes a single file
        (used to skip the file currently being scanned from its own results).
        """
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

        stmt = (
            select(KnowledgeFile)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFile.file_type == 1,  # FILE
                KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
            )
        )
        if exclude_file_id is not None:
            stmt = stmt.where(KnowledgeFile.id != exclude_file_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_folder_descendant_status_flags(
        self,
        knowledge_id: int,
        folder_prefixes: dict[int, str],
    ) -> dict[int, FolderDescendantStatusFlags]:
        if not folder_prefixes:
            return {}

        abnormal_statuses = KnowledgeFileStatus.abnormal_values()
        processing_statuses = {
            KnowledgeFileStatus.PROCESSING.value,
            KnowledgeFileStatus.WAITING.value,
            KnowledgeFileStatus.REBUILDING.value,
        }
        tracked_statuses = abnormal_statuses | processing_statuses
        prefix_conditions = {
            folder_id: or_(
                KnowledgeFile.file_level_path == prefix,
                KnowledgeFile.file_level_path.like(f"{prefix}/%"),
            )
            for folder_id, prefix in folder_prefixes.items()
        }
        folder_id_expression = case(
            *((prefix_condition, folder_id) for folder_id, prefix_condition in prefix_conditions.items()),
            else_=None,
        )
        statement = (
            select(
                folder_id_expression.label("folder_id"),
                func.max(case((col(KnowledgeFile.status).in_(sorted(abnormal_statuses)), 1), else_=0)),
                func.max(case((col(KnowledgeFile.status).in_(sorted(processing_statuses)), 1), else_=0)),
            )
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                col(KnowledgeFile.status).in_(sorted(tracked_statuses)),
                or_(*prefix_conditions.values()),
            )
            .group_by(folder_id_expression)
        )
        rows = (await self.session.execute(statement)).all()
        return {
            int(folder_id): FolderDescendantStatusFlags(
                has_abnormal_files=bool(has_abnormal),
                has_processing_files=bool(has_processing),
            )
            for folder_id, has_abnormal, has_processing in rows
        }

    # according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field
    async def get_user_metadata_by_knowledge_file_ids(
        self, knowledge_id: int, knowledge_file_ids: list[int]
    ) -> dict[int | None, list[dict[str, Any]] | None]:
        query = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id, col(KnowledgeFile.id).in_(knowledge_file_ids)
        )

        result = await self.session.exec(query)

        knowledge_files = result.all()

        user_metadata_dict = {}

        for knowledge_file in knowledge_files:
            if knowledge_file.user_metadata:
                # Sort by newness
                sorted_user_metadata = dict(
                    sorted(
                        knowledge_file.user_metadata.items(),
                        key=lambda item: item[1].get("updated_at", 0),
                        reverse=False,
                    )
                )
                user_metadata_dict[knowledge_file.id] = sorted_user_metadata
            else:
                user_metadata_dict[knowledge_file.id] = {}

        return user_metadata_dict
