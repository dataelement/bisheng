from collections.abc import Sequence
from typing import Optional

from sqlalchemy import case, func, or_, text, update
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.domain.models.knowledge_file import (
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
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
]
_EXT_RANK_FALLBACK = 999
_CHILD_ORDER_FIELDS = {"file_type", "file_name", "update_time"}


def normalize_child_order_field(order_field: str | None) -> str:
    """Return a supported child-list order field.

    The value is later embedded in an ORDER BY text fragment, so keep the
    allowlist tight and default unknown client input to the historical order.
    """
    if order_field in _CHILD_ORDER_FIELDS:
        return order_field
    return "file_type"


def normalize_child_order_sort(order_sort: str | None) -> str:
    return "desc" if str(order_sort or "").lower() == "desc" else "asc"


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


def child_order_cursor_key_len(order_field: str | None) -> int:
    order_field = normalize_child_order_field(order_field)
    if order_field == "file_type":
        # file_type + manual-order flag + weight + ext_rank + update_time + id
        return 6
    if order_field == "file_name":
        return 3
    return 2


def build_child_order_cursor_key(item: KnowledgeFile, order_field: str | None) -> list:
    order_field = normalize_child_order_field(order_field)
    if order_field == "file_type":
        # Must mirror order_field_text()'s file_type branch column-for-column, including
        # the two manual-order terms: NULL weights sort last (1 > 0), and NULL itself is
        # never compared as a value because the flag term already separates the groups.
        weight = item.sort_weight
        return [
            item.file_type,
            1 if weight is None else 0,
            weight if weight is not None else 0,
            _compute_ext_rank_python(item.file_name),
            item.update_time,
            item.id,
        ]
    if order_field == "file_name":
        return [
            item.file_name or "",
            item.update_time,
            item.id,
        ]
    return [
        item.update_time,
        item.id,
    ]


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
    async def find_folder_by_name(
        cls,
        knowledge_id: int,
        folder_name: str,
        file_level_path: str,
    ) -> KnowledgeFile | None:
        if file_level_path:
            path_filter = KnowledgeFile.file_level_path == file_level_path
        else:
            path_filter = cls._root_path_filter()
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == 0,
                KnowledgeFile.file_name == folder_name,
                path_filter,
                col(KnowledgeFile.deleted_at).is_(None),
            )
            .limit(1)
        )
        async with get_async_db_session() as session:
            return (await session.execute(statement)).scalar_one_or_none()

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
            col(KnowledgeFile.deleted_at).is_(None),
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
            col(KnowledgeFile.deleted_at).is_(None),
        )
        if exclude_id is not None:
            statement = statement.where(KnowledgeFile.id != exclude_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def count_file_by_name_in_path(
        cls,
        knowledge_id: int,
        file_name: str,
        file_level_path: str,
        exclude_id: int | None = None,
    ) -> int:
        """Count files with the same name under the same parent folder."""
        if file_level_path:
            path_filter = KnowledgeFile.file_level_path == file_level_path
        else:
            path_filter = cls._root_path_filter()
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.file_name == file_name,
            path_filter,
            col(KnowledgeFile.deleted_at).is_(None),
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
            col(KnowledgeFile.deleted_at).is_(None),
            or_(col(KnowledgeFile.file_level_path) == prefix, col(KnowledgeFile.file_level_path).like(f"{prefix}/%")),
        )
        if file_status is not None:
            statement = statement.where(KnowledgeFile.status == file_status.value)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

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

        F027: when ``page == 0`` this method uses cursor scan mode. The first
        page still applies ORDER BY + LIMIT; subsequent calls add a keyset
        WHERE based on the requested sort field.
        """
        order_field = normalize_child_order_field(order_field)
        order_sort = normalize_child_order_sort(order_sort)
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
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter, col(KnowledgeFile.deleted_at).is_(None)]
        filters.extend(
            [
                or_(
                    KnowledgeFile.reference_document_id.is_(None),
                    KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFile.entry_status == KnowledgeFileEntryStatus.INVALID.value,
                ),
                or_(
                    KnowledgeFile.entry_type.is_(None),
                    KnowledgeFile.entry_type != KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
                ),
            ]
        )
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
                col(Descendant.deleted_at).is_(None),
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

        # F027: cursor-based keyset takes precedence over OFFSET. ``page == 0``
        # is the first cursor page and must still be bounded by ``page_size``.
        if cursor is not None or page == 0:
            from bisheng.database.utils.keyset import build_keyset_where

            sort_cols, descending = cls._keyset_sort_columns(order_field, order_sort)
            if cursor is not None:
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
    def _keyset_sort_columns(order_field: str, order_sort: str):
        order_field = normalize_child_order_field(order_field)
        order_sort = normalize_child_order_sort(order_sort)
        order_dir_asc = order_sort == "asc"
        if order_field == "file_type":
            # The two manual-order terms mirror order_field_text(): a NULL-flag that
            # sorts never-dragged rows last, then the weight itself (NULL coalesced to 0
            # so it never compares as NULL — the flag term already separated the groups).
            # Both always ascend, like the ORDER BY, regardless of order_sort.
            return (
                KnowledgeFile.file_type,
                case((KnowledgeFile.sort_weight.is_(None), 1), else_=0),
                func.coalesce(KnowledgeFile.sort_weight, 0),
                _compute_ext_rank_case_when(),
                KnowledgeFile.update_time,
                KnowledgeFile.id,
            ), (
                not order_dir_asc,
                False,
                False,
                not order_dir_asc,
                True,
                True,
            )
        if order_field == "file_name":
            return (
                KnowledgeFile.file_name,
                KnowledgeFile.update_time,
                KnowledgeFile.id,
            ), (
                not order_dir_asc,
                True,
                True,
            )
        return (
            KnowledgeFile.update_time,
            KnowledgeFile.id,
        ), (
            not order_dir_asc,
            not order_dir_asc,
        )

    @staticmethod
    def order_field_text(order_field: str, order_sort: str) -> str:
        order_field = normalize_child_order_field(order_field)
        order_sort = normalize_child_order_sort(order_sort).upper()
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
            ]
            when_clauses = "\n                ".join(
                f"WHEN LOWER(file_name) LIKE '%.{ext}' THEN {rank}" for ext, rank in ext_priorities
            )
            # Admin-dragged folder order applies only in this default mode; picking a
            # column header switches to the branches below, where sort_weight is absent
            # and the manual order intentionally stops applying. Never-dragged rows have
            # a NULL weight and sort behind the dragged ones (CASE keeps NULLS-LAST
            # portable across MySQL and DM8), so untouched directories keep their
            # existing order.
            order_text += f"""
            file_type {order_sort},
            CASE WHEN sort_weight IS NULL THEN 1 ELSE 0 END,
            sort_weight ASC,
            CASE
                {when_clauses}
                ELSE 999
            END {order_sort}
            """
        elif order_field == "update_time":
            order_text += f"update_time {order_sort}, id {order_sort}"
        else:
            order_text += f"file_name {order_sort}"
        if order_field != "update_time":
            order_text += ", update_time desc, id desc"
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
        filters = [KnowledgeFile.knowledge_id == knowledge_id, path_filter, col(KnowledgeFile.deleted_at).is_(None)]
        filters.append(KnowledgeFileDao.active_inventory_predicate())
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
                col(Descendant.deleted_at).is_(None),
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
            KnowledgeFileDao.physical_storage_predicate(),
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

    @classmethod
    @classmethod
    async def max_level_under_prefix(cls, space_id: int, prefix: str) -> int | None:
        """Return the maximum ``level`` among all rows whose path starts with ``prefix``."""
        statement = select(func.max(col(KnowledgeFile.level))).where(
            KnowledgeFile.knowledge_id == space_id,
            or_(
                col(KnowledgeFile.file_level_path) == prefix,
                col(KnowledgeFile.file_level_path).like(f"{prefix}/%"),
            ),
        )
        async with get_async_db_session() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    @classmethod
    async def update_descendants_path(
        cls,
        space_id: int,
        old_prefix: str,
        new_prefix: str,
        level_diff: int,
        folder: Optional["KnowledgeFile"] = None,
    ) -> None:
        """Bulk-update file_level_path and level for all descendants of a moved folder.

        Replaces the ``old_prefix`` portion of file_level_path with ``new_prefix``
        for every row whose path starts with ``old_prefix`` (exact match for direct
        children, prefix+/ match for deeper descendants).

        When ``folder`` is provided it is updated in the same transaction so that
        the folder record and its descendants are always consistent.
        """
        if old_prefix == new_prefix:
            if folder is not None:
                async with get_async_db_session() as session:
                    session.add(folder)
                    await session.commit()
                    await session.refresh(folder)
            return
        old_prefix_len = len(old_prefix)
        statement = (
            update(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == space_id,
                or_(
                    col(KnowledgeFile.file_level_path) == old_prefix,
                    col(KnowledgeFile.file_level_path).like(f"{old_prefix}/%"),
                ),
            )
            .values(
                file_level_path=func.concat(
                    new_prefix,
                    func.substring(col(KnowledgeFile.file_level_path), old_prefix_len + 1),
                ),
                level=col(KnowledgeFile.level) + level_diff,
            )
        )
        async with get_async_db_session() as session:
            affected_result = await session.execute(
                select(KnowledgeFile).where(
                    KnowledgeFile.knowledge_id == space_id,
                    or_(
                        col(KnowledgeFile.file_level_path) == old_prefix,
                        col(KnowledgeFile.file_level_path).like(f"{old_prefix}/%"),
                    ),
                    KnowledgeFile.file_type == FileType.FILE.value,
                )
            )
            affected_files = list(affected_result.scalars().all())
            await session.execute(statement)
            if folder is not None:
                session.add(folder)
            from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
                KnowledgeFulltextFileRef,
                request_file_sync_intents,
            )

            await request_file_sync_intents(
                session,
                [
                    KnowledgeFulltextFileRef(
                        file_id=int(item.id),
                        knowledge_id=int(item.knowledge_id),
                        tenant_id=int(item.tenant_id or 1),
                    )
                    for item in affected_files
                ],
                trigger_type="folder_moved",
            )
            await session.commit()
            if folder is not None:
                await session.refresh(folder)
