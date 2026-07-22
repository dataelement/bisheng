from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository


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

    async def find_success_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS physical files in a space, including files without a version document."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

        stmt = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            KnowledgeFile.file_type == 1,
        )
        if exclude_file_id is not None:
            stmt = stmt.where(KnowledgeFile.id != exclude_file_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_file_sync_folders_by_ids(
        self,
        folder_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not folder_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                col(KnowledgeFile.id).in_(folder_ids),
                KnowledgeFile.file_type == FileType.DIR.value,
            )
        )
        return list(result.scalars().all())

    async def list_file_sync_direct_children(
        self,
        *,
        knowledge_id: int,
        parent_path: str,
        visible_folder_ids: set[int] | None,
        after: tuple[str, int] | None,
        limit: int,
    ) -> list[KnowledgeFile]:
        if visible_folder_ids is not None and not visible_folder_ids:
            return []
        stmt = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == FileType.DIR.value,
            KnowledgeFile.file_level_path == parent_path,
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        if after is not None:
            after_name, after_id = after
            stmt = stmt.where(
                or_(
                    KnowledgeFile.file_name > after_name,
                    and_(
                        KnowledgeFile.file_name == after_name,
                        KnowledgeFile.id > after_id,
                    ),
                )
            )
        result = await self.session.execute(
            stmt.order_by(KnowledgeFile.file_name.asc(), KnowledgeFile.id.asc()).limit(limit)
        )
        return list(result.scalars().all())

    async def find_file_sync_space_ids_with_folders(
        self,
        *,
        space_ids: set[int],
        visible_folder_ids: set[int] | None,
    ) -> set[int]:
        if not space_ids or (visible_folder_ids is not None and not visible_folder_ids):
            return set()
        stmt = select(KnowledgeFile.knowledge_id).where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.DIR.value,
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        result = await self.session.execute(stmt.distinct())
        return {int(value) for value in result.scalars().all()}

    async def find_file_sync_parent_paths_with_children(
        self,
        *,
        knowledge_id: int,
        parent_paths: set[str],
        visible_folder_ids: set[int] | None,
    ) -> set[str]:
        if not parent_paths or (visible_folder_ids is not None and not visible_folder_ids):
            return set()
        stmt = select(KnowledgeFile.file_level_path).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == FileType.DIR.value,
            col(KnowledgeFile.file_level_path).in_(parent_paths),
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        result = await self.session.execute(stmt.distinct())
        return {str(value or "") for value in result.scalars().all()}

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
