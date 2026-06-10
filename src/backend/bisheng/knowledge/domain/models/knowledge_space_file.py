from collections.abc import Sequence

from sqlalchemy import case, func, or_, text, update
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)

# F027 AD-14: file extension priority for "file_type" sort order.
# Same 15-WHEN ranking used by `SpaceFileDao.order_field_text`'s SQL CASE.
# Files not matching any of these (folders, unknown extensions) get rank 999.
_EXT_PRIORITIES: list[tuple] = [
    ("pdf", 1),
    ("docx", 2),
    ("doc", 3),
    ("xlsx", 4),
    ("xls", 5),
    ("csv", 6),
    ("pptx", 7),
    ("ppt", 8),
    ("jpg", 9),
    ("jpeg", 10),
    ("png", 11),
    ("bmp", 12),
    ("md", 13),
    ("txt", 14),
    ("html", 15),
    ("ofd", 16),
]
_EXT_RANK_FALLBACK = 999


def _compute_ext_rank_python(file_name: str | None) -> int:
    """Python mirror of the SQL CASE WHEN ext_rank ladder (F027 AD-14).

    Must agree exactly with ``_compute_ext_rank_case_when()`` so cursor
    values computed in Python compare correctly against SQL-side keyset
    expressions.
    """
    if not file_name:
        return _EXT_RANK_FALLBACK
    lowered = file_name.lower()
    for ext, rank in _EXT_PRIORITIES:
        if lowered.endswith("." + ext):
            return rank
    return _EXT_RANK_FALLBACK


def _compute_ext_rank_case_when():
    """SQL-side ext_rank: SQLAlchemy ``case()`` matching ``_EXT_PRIORITIES``.

    Returns a Case expression that resolves to the same integer as
    ``_compute_ext_rank_python()`` for any given ``KnowledgeFile.file_name``.
    """
    whens = [(func.lower(KnowledgeFile.file_name).like(f"%.{ext}"), rank) for ext, rank in _EXT_PRIORITIES]
    return case(*whens, else_=_EXT_RANK_FALLBACK)


class SpaceFileDao(KnowledgeFileDao):
    """DAO for space folder and file operations in the knowledge_file table"""

    @staticmethod
    def _root_path_filter():
        # Treat both empty string and NULL as root-level items. Some historical
        # rows and upload paths persist NULL, while newer writes use "".
        return or_(
            KnowledgeFile.file_level_path == "",
            KnowledgeFile.file_level_path.is_(None),
        )

    @classmethod
    async def count_folder_by_name(
        cls, knowledge_id: int, folder_name: str, file_level_path: str, exclude_id: int | None = None
    ) -> int:
        """Count folders with the same name in the same directory level"""
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == 0,
            KnowledgeFile.file_name == folder_name,
            KnowledgeFile.file_level_path == file_level_path,
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def count_file_by_name(cls, knowledge_id: int, file_name: str, exclude_id: int | None = None) -> int:
        """Count files with the same name in the space (duplicate check on rename)"""
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == 1,
            KnowledgeFile.file_name == file_name,
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def get_children_by_prefix(
        cls, knowledge_id: int, prefix: str, file_status: KnowledgeFileStatus = None
    ) -> list[KnowledgeFile]:
        """Get all files/folders whose file_level_path starts with the given prefix"""
        statement = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            or_(col(KnowledgeFile.file_level_path) == prefix, col(KnowledgeFile.file_level_path).like(f"{prefix}/%")),
        )
        if file_status is not None:
            statement = statement.where(KnowledgeFile.status == file_status.value)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def get_max_level_in_subtree(cls, knowledge_id: int, folder_id: int, folder_level_path: str) -> int:
        """Deepest ``level`` within a folder's own subtree (the folder itself + all
        descendants). F034 depth check (AC-11): a folder move is allowed only if
        ``target_level + (max_subtree_level - folder_level) <= 10``; this returns the
        ``max_subtree_level`` term. Subtree prefix = ``{folder_level_path}/{folder_id}``;
        the folder itself (``file_level_path == folder_level_path``) is included so a
        leaf folder still reports its own level.
        """
        subtree_prefix = f"{folder_level_path}/{folder_id}"
        statement = select(func.max(KnowledgeFile.level)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            or_(
                KnowledgeFile.id == folder_id,
                col(KnowledgeFile.file_level_path) == subtree_prefix,
                col(KnowledgeFile.file_level_path).like(f"{subtree_prefix}/%"),
            ),
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def async_list_children(
        cls,
        knowledge_id: int,
        parent_id: int | None,
        file_ids: list[int] | None = None,
        order_field: str = "file_type",
        order_sort: str = "desc",
        file_status: list[int] = None,
        page: int = 1,
        page_size: int = 20,
        file_type: int | None = None,
        exclude_file_ids: list[int] | None = None,
        cursor: Sequence | None = None,
    ) -> list[KnowledgeFile]:
        """
        Async: List direct children (folders first, then files) under a given parent.
        When parent_id is None, returns root-level items (file_level_path == '').

        F027: when ``cursor`` is provided (4-tuple ``(file_type, ext_rank,
        update_time, id)``), keyset WHERE is injected and the offset path is
        skipped. ``order_field`` must be ``"file_type"`` in cursor mode
        (other order_fields keep using OFFSET).
        """
        if parent_id is None:
            exact_path = ""
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
        if file_type is not None:
            filters.append(KnowledgeFile.file_type == file_type)
        if exclude_file_ids:
            filters.append(col(KnowledgeFile.id).notin_(exclude_file_ids))

        if file_status:
            from sqlalchemy import and_, exists
            from sqlalchemy.orm import aliased

            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, "/", KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == 1,
                Descendant.status.in_(file_status),
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, "/%")),
                ),
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == 1, KnowledgeFile.status.in_(file_status)),
                and_(
                    KnowledgeFile.file_type == 0,
                    or_(KnowledgeFile.status.in_(file_status), descendant_exists),
                ),
            )
            filters.append(status_filter)

        statement = select(KnowledgeFile).where(*filters)

        # F027: cursor-based keyset takes precedence over OFFSET.
        if cursor is not None and order_field == "file_type":
            from bisheng.database.utils.keyset import build_keyset_where

            order_dir_asc = (order_sort or "asc").lower() == "asc"
            sort_cols = (
                KnowledgeFile.file_type,
                _compute_ext_rank_case_when(),
                KnowledgeFile.update_time,
                KnowledgeFile.id,
            )
            # Mixed direction: file_type + ext_rank follow ``order_sort``;
            # update_time + id are always DESC (newest first within same ext).
            descending = (
                not order_dir_asc,
                not order_dir_asc,
                True,
                True,
            )
            statement = statement.where(build_keyset_where(sort_cols, tuple(cursor), descending=descending))
            if page_size:
                statement = statement.limit(page_size)
            statement = statement.order_by(text(cls.order_field_text(order_field, order_sort)))
        else:
            if page and page_size:
                statement = statement.offset((page - 1) * page_size).limit(page_size)
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
            # pdf>docx>doc>xlsx>xls>csv>pptx>ppt>jpg>jpeg>png>bmp>md>txt>html.
            # Use LOWER(file_name) LIKE '%.<ext>' instead of SUBSTRING_INDEX —
            # the latter is MySQL-specific and not supported on DM8.
            ext_priorities = [
                ("pdf", 1),
                ("docx", 2),
                ("doc", 3),
                ("xlsx", 4),
                ("xls", 5),
                ("csv", 6),
                ("pptx", 7),
                ("ppt", 8),
                ("jpg", 9),
                ("jpeg", 10),
                ("png", 11),
                ("bmp", 12),
                ("md", 13),
                ("txt", 14),
                ("html", 15),
                ("ofd", 16),
            ]
            when_clauses = "\n                ".join(
                f"WHEN LOWER(file_name) LIKE '%.{ext}' THEN {rank}" for ext, rank in ext_priorities
            )
            order_text += f"""
            file_type {order_sort},
            CASE
                {when_clauses}
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
        parent_id: int | None,
        file_ids: list[int] | None = None,
        file_status: list[int] = None,
    ) -> int:
        """
        Async: Count direct children under a given parent.
        When parent_id is None, counts root-level items.
        """
        if parent_id is None:
            exact_path = ""
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
            from sqlalchemy import and_, exists
            from sqlalchemy.orm import aliased

            Descendant = aliased(KnowledgeFile)
            folder_prefix = func.concat(exact_path, "/", KnowledgeFile.id)
            descendant_exists = exists().where(
                Descendant.knowledge_id == knowledge_id,
                Descendant.file_type == FileType.FILE.value,
                Descendant.status.in_(file_status),
                or_(
                    Descendant.file_level_path == folder_prefix,
                    Descendant.file_level_path.like(func.concat(folder_prefix, "/%")),
                ),
            )
            status_filter = or_(
                and_(KnowledgeFile.file_type == FileType.FILE.value, KnowledgeFile.status.in_(file_status)),
                and_(
                    KnowledgeFile.file_type == FileType.DIR.value,
                    or_(KnowledgeFile.status.in_(file_status), descendant_exists),
                ),
            )
            filters.append(status_filter)

        statement = select(func.count(KnowledgeFile.id)).where(*filters)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def get_user_total_file_size(cls, user_id: int) -> int:
        """Get total file size for all files in the knowledge space (excluding folders)"""
        statement = select(func.sum(KnowledgeFile.file_size)).where(
            KnowledgeFile.user_id == user_id,
            KnowledgeFile.file_type == 1,
            col(KnowledgeFile.file_source).in_([FileSource.SPACE_UPLOAD.value, FileSource.CHANNEL.value]),
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def update_records_update_time(cls, ids: list[int]):
        if not ids:
            return
        statement = (
            update(KnowledgeFile)
            .where(
                col(KnowledgeFile.id).in_(ids),
            )
            .values(update_time=text("NOW()"))
        )
        async with get_async_db_session() as session:
            await session.execute(statement)
            await session.commit()

    @classmethod
    def update_records_update_time_sync(cls, ids: list[int]):
        if not ids:
            return
        statement = (
            update(KnowledgeFile)
            .where(
                col(KnowledgeFile.id).in_(ids),
            )
            .values(update_time=text("NOW()"))
        )
        with get_sync_db_session() as session:
            session.execute(statement)
            session.commit()
