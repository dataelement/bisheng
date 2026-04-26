from typing import Optional, List

from sqlalchemy import func, or_, text, update
from sqlmodel import select, col

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, KnowledgeFileStatus, \
    FileType, FileSource


class SpaceFileDao(KnowledgeFileDao):
    """ DAO for space folder and file operations in the knowledge_file table """

    @staticmethod
    def _root_path_filter():
        # Treat both empty string and NULL as root-level items. Some historical
        # rows and upload paths persist NULL, while newer writes use "".
        return or_(
            KnowledgeFile.file_level_path == '',
            KnowledgeFile.file_level_path.is_(None),
        )

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
    async def get_children_by_prefix(cls, knowledge_id: int, prefix: str, file_status: KnowledgeFileStatus = None) \
            -> List[KnowledgeFile]:
        """ Get all files/folders whose file_level_path starts with the given prefix """
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            or_(
                col(KnowledgeFile.file_level_path) == prefix,
                col(KnowledgeFile.file_level_path).like(f"{prefix}/%")
            )
        )
        if file_status is not None:
            statement = statement.where(KnowledgeFile.status == file_status.value)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def async_list_children(
            cls,
            knowledge_id: int,
            parent_id: Optional[int],
            file_ids: Optional[List[int]] = None,
            order_field: str = "file_type",
            order_sort: str = "desc",
            file_status: List[int] = None,
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
            path_filter = cls._root_path_filter()
        else:
            parent = await KnowledgeFileDao.query_by_id(parent_id)
            if parent:
                exact_path = f"{parent.file_level_path}/{parent_id}" if parent.file_level_path else f"/{parent_id}"
            else:
                exact_path = f"/{parent_id}"
            path_filter = KnowledgeFile.file_level_path == exact_path
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter]
        if file_ids:
            filters.append(KnowledgeFile.id.in_(file_ids))

        if file_status:
            from sqlalchemy.orm import aliased
            from sqlalchemy import exists, and_
            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, '/', KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == 1,
                Descendant.status.in_(file_status),
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, '/%'))
                )
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == 1, KnowledgeFile.status.in_(file_status)),
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
            statement = statement.order_by(text(cls.order_field_text(order_field, order_sort)))
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @staticmethod
    def order_field_text(order_field: str, order_sort: str) -> str:
        order_sort = order_sort.upper()
        order_text = ""

        if order_field == "file_type":
            # pdf>docx>doc>>xlsx>xls>csv>pptx>ppt>jpg>png>jpeg>bmp>md>txt>html
            order_text += f"""
            file_type {order_sort},
            CASE LOWER(SUBSTRING_INDEX(file_name, '.', -1))
                WHEN 'pdf' THEN 1
                WHEN 'docx' THEN 2
                WHEN 'doc' THEN 3
                WHEN 'xlsx' THEN 4
                WHEN 'xls' THEN 5
                WHEN 'csv' THEN 6
                WHEN 'pptx' THEN 7
                WHEN 'ppt' THEN 8
                WHEN 'jpg' THEN 9
                WHEN 'jpeg' THEN 10
                WHEN 'png' THEN 11
                WHEN 'bmp' THEN 12
                WHEN 'md' THEN 13
                WHEN 'txt' THEN 14
                WHEN 'html' THEN 15
                ELSE 999
            END {order_sort}
            """
        else:
            order_text += f"{order_field} {order_sort}"
        if order_field != "update_time":
            order_text += ", update_time desc"
        return order_text

    @classmethod
    async def async_count_children(
            cls,
            knowledge_id: int,
            parent_id: Optional[int],
            file_ids: Optional[List[int]] = None,
            file_status: List[int] = None,
    ) -> int:
        """
        Async: Count direct children under a given parent.
        When parent_id is None, counts root-level items.
        """
        if parent_id is None:
            exact_path = ''
            path_filter = cls._root_path_filter()
        else:
            parent = await KnowledgeFileDao.query_by_id(parent_id)
            if parent:
                exact_path = f"{parent.file_level_path}/{parent_id}" if parent.file_level_path else f"/{parent_id}"
            else:
                exact_path = f"/{parent_id}"
            path_filter = KnowledgeFile.file_level_path == exact_path
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter]
        if file_ids:
            filters.append(KnowledgeFile.id.in_(file_ids))

        if file_status:
            from sqlalchemy.orm import aliased
            from sqlalchemy import exists, and_
            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, '/', KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == FileType.FILE.value,
                Descendant.status.in_(file_status),
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, '/%'))
                )
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == FileType.FILE.value, KnowledgeFile.status.in_(file_status)),
                and_(KnowledgeFile.file_type == FileType.DIR.value, descendant_exists)
            )
            filters.append(status_filter)

        statement = select(func.count(KnowledgeFile.id)).where(*filters)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def get_user_total_file_size(cls, user_id: int) -> int:
        """ Get total file size for all files in the knowledge space (excluding folders) """
        statement = select(func.sum(KnowledgeFile.file_size)).where(
            KnowledgeFile.user_id == user_id,
            KnowledgeFile.file_type == 1,
            col(KnowledgeFile.file_source).in_([FileSource.SPACE_UPLOAD.value,
                                                FileSource.CHANNEL.value]),
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def update_records_update_time(cls, ids: List[int]):
        if not ids:
            return
        statement = update(KnowledgeFile).where(
            col(KnowledgeFile.id).in_(ids),
        ).values(update_time=text("NOW()"))
        async with get_async_db_session() as session:
            await session.execute(statement)
            await session.commit()

    @classmethod
    def update_records_update_time_sync(cls, ids: List[int]):
        if not ids:
            return
        statement = update(KnowledgeFile).where(
            col(KnowledgeFile.id).in_(ids),
        ).values(update_time=text("NOW()"))
        with get_sync_db_session() as session:
            session.execute(statement)
            session.commit()
