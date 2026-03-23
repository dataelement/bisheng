from typing import Optional, List

from sqlalchemy import func, or_, text
from sqlmodel import select, col

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, KnowledgeFileStatus


class SpaceFileDao(KnowledgeFileDao):
    """ DAO for space folder and file operations in the knowledge_file table """

    @classmethod
    async def count_folder_by_name(cls, knowledge_id: int, folder_name: str, file_level_path: str,
                                   exclude_id: Optional[int] = None) -> int:
        """ Count folders with the same name in the same directory level """
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == 0,
            KnowledgeFile.file_name == folder_name,
            KnowledgeFile.file_level_path == file_level_path
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def count_file_by_name(cls, knowledge_id: int, file_name: str,
                                 exclude_id: Optional[int] = None) -> int:
        """ Count files with the same name in the space (duplicate check on rename) """
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == 1,
            KnowledgeFile.file_name == file_name
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def get_children_by_prefix(cls, knowledge_id: int, prefix: str) -> List[KnowledgeFile]:
        """ Get all files/folders whose file_level_path starts with the given prefix """
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            or_(
                col(KnowledgeFile.file_level_path) == prefix,
                col(KnowledgeFile.file_level_path).like(f"{prefix}/%")
            )
        )
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def async_list_children(
            cls,
            knowledge_id: int,
            parent_id: Optional[int],
            order_field: str = "file_type",
            order_sort: str = "desc",
            file_status: KnowledgeFileStatus = None,
            page: int = 1,
            page_size: int = 20,
    ) -> List[KnowledgeFile]:
        """
        Async: List direct children (folders first, then files) under a given parent.
        When parent_id is None, returns root-level items (file_level_path == '').
        Paginated: page is 1-indexed.
        """
        if parent_id is None:
            exact_path = ''
        else:
            parent = await KnowledgeFileDao.query_by_id(parent_id)
            if parent:
                exact_path = f"{parent.file_level_path}/{parent_id}" if parent.file_level_path else f"/{parent_id}"
            else:
                exact_path = f"/{parent_id}"

        path_filter = KnowledgeFile.file_level_path == exact_path
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter]

        if file_status is not None:
            from sqlalchemy.orm import aliased
            from sqlalchemy import exists, and_
            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, '/', KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == 1,
                Descendant.status == file_status.value,
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, '/%'))
                )
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == 1, KnowledgeFile.status == file_status.value),
                and_(KnowledgeFile.file_type == 0, descendant_exists)
            )
            filters.append(status_filter)

        statement = (
            select(KnowledgeFile)
            .where(*filters)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if order_field and order_sort:
            statement = statement.order_by(text(f"{order_field} {order_sort}"))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_count_children(
            cls,
            knowledge_id: int,
            parent_id: Optional[int],
            file_status: KnowledgeFileStatus = None,
    ) -> int:
        """
        Async: Count direct children under a given parent.
        When parent_id is None, counts root-level items.
        """
        if parent_id is None:
            exact_path = ''
        else:
            parent = await KnowledgeFileDao.query_by_id(parent_id)
            if parent:
                exact_path = f"{parent.file_level_path}/{parent_id}" if parent.file_level_path else f"/{parent_id}"
            else:
                exact_path = f"/{parent_id}"

        path_filter = KnowledgeFile.file_level_path == exact_path
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter]

        if file_status is not None:
            from sqlalchemy.orm import aliased
            from sqlalchemy import exists, and_
            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, '/', KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == 1,
                Descendant.status == file_status.value,
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, '/%'))
                )
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == 1, KnowledgeFile.status == file_status.value),
                and_(KnowledgeFile.file_type == 0, descendant_exists)
            )
            filters.append(status_filter)

        statement = select(func.count(KnowledgeFile.id)).where(*filters)
        async with get_async_db_session() as session:
            return await session.scalar(statement)
