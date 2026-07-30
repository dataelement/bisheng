from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_source_repository import (
    KnowledgeMigrationSourceRepository,
    MigrationChildRecord,
    MigrationSpaceRecord,
)
from bisheng.user.domain.models.user import User


class KnowledgeMigrationSourceRepositoryImpl(KnowledgeMigrationSourceRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _space_filters():
        return (
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.state == KnowledgeState.PUBLISHED.value,
            Knowledge.is_favorite.is_(False),
        )

    async def list_spaces(
        self,
        *,
        keyword: str | None,
        level: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[MigrationSpaceRecord], int]:
        filters = list(self._space_filters())
        if keyword:
            filters.append(Knowledge.name.contains(keyword, autoescape=True))
        if level:
            filters.append(KnowledgeSpaceScope.level == level)
        total = int(
            (
                await self.session.exec(
                    select(func.count())
                    .select_from(Knowledge)
                    .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                    .where(*filters)
                )
            ).one()
        )
        rows = (
            await self.session.execute(
                select(
                    Knowledge,
                    KnowledgeSpaceScope.level,
                    KnowledgeSpaceScope.owner_type,
                    User.user_id,
                    User.delete,
                )
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .outerjoin(User, User.user_id == Knowledge.user_id)
                .where(*filters)
                .order_by(Knowledge.name, Knowledge.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return (
            [
                MigrationSpaceRecord(
                    space=row[0],
                    level=getattr(row[1], "value", row[1]),
                    owner_type=getattr(row[2], "value", row[2]),
                    owner_id=(
                        int(row[3])
                        if row[3] is not None and int(row[4] or 0) == 0
                        else 0
                    ),
                )
                for row in rows
            ],
            total,
        )

    async def find_spaces_by_ids(
        self,
        space_ids: set[int],
    ) -> list[MigrationSpaceRecord]:
        if not space_ids:
            return []
        rows = (
            await self.session.execute(
                select(
                    Knowledge,
                    KnowledgeSpaceScope.level,
                    KnowledgeSpaceScope.owner_type,
                    User.user_id,
                    User.delete,
                )
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .outerjoin(User, User.user_id == Knowledge.user_id)
                .where(col(Knowledge.id).in_(space_ids), *self._space_filters())
            )
        ).all()
        return [
            MigrationSpaceRecord(
                space=row[0],
                level=getattr(row[1], "value", row[1]),
                owner_type=getattr(row[2], "value", row[2]),
                owner_id=(
                    int(row[3])
                    if row[3] is not None and int(row[4] or 0) == 0
                    else 0
                ),
            )
            for row in rows
        ]

    async def list_children(
        self,
        *,
        space_id: int,
        parent_id: int | None,
        after: tuple[str, int] | None,
        limit: int,
        folders_only: bool,
    ) -> list[MigrationChildRecord]:
        parent_path = ""
        if parent_id is not None:
            parent = (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.id == parent_id,
                        KnowledgeFile.knowledge_id == space_id,
                        KnowledgeFile.file_type == FileType.DIR.value,
                        KnowledgeFile.deleted_at.is_(None),
                    )
                )
            ).first()
            if parent is None:
                return []
            parent_path = f"{parent.file_level_path or ''}/{parent_id}"
        filters = [
            KnowledgeFile.knowledge_id == space_id,
            KnowledgeFile.file_level_path == parent_path,
            KnowledgeFile.deleted_at.is_(None),
        ]
        if folders_only:
            filters.append(KnowledgeFile.file_type == FileType.DIR.value)
        if after is not None:
            after_name, after_id = after
            filters.append(
                or_(
                    KnowledgeFile.file_name > after_name,
                    and_(
                        KnowledgeFile.file_name == after_name,
                        KnowledgeFile.id > after_id,
                    ),
                )
            )
        files = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(*filters)
                    .order_by(KnowledgeFile.file_name, KnowledgeFile.id)
                    .limit(limit)
                )
            ).all()
        )
        folder_paths = {
            f"{item.file_level_path or ''}/{item.id}"
            for item in files
            if item.file_type == FileType.DIR.value
        }
        paths_with_children: set[str] = set()
        if folder_paths:
            paths_with_children = set(
                (
                    await self.session.exec(
                        select(KnowledgeFile.file_level_path)
                        .where(
                            KnowledgeFile.knowledge_id == space_id,
                            col(KnowledgeFile.file_level_path).in_(folder_paths),
                            KnowledgeFile.deleted_at.is_(None),
                        )
                        .distinct()
                    )
                ).all()
            )
        return [
            MigrationChildRecord(
                file=item,
                has_children=f"{item.file_level_path or ''}/{item.id}" in paths_with_children,
            )
            for item in files
        ]

    async def find_nodes(
        self,
        *,
        space_id: int,
        node_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not node_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == space_id,
                        col(KnowledgeFile.id).in_(node_ids),
                        KnowledgeFile.deleted_at.is_(None),
                    )
                )
            ).all()
        )

    async def expand_selection(
        self,
        selection_snapshot: Sequence[dict],
    ) -> list[KnowledgeFile]:
        results: dict[int, KnowledgeFile] = {}
        for selection in selection_snapshot:
            space_id = int(selection["space_id"])
            file_ids = {
                int(node["node_id"])
                for node in selection["nodes"]
                if node["node_type"] == "file"
            }
            folder_ids = {
                int(node["node_id"])
                for node in selection["nodes"]
                if node["node_type"] == "folder"
            }
            folders = await self.find_nodes(space_id=space_id, node_ids=folder_ids)
            descendants = []
            for folder in folders:
                if folder.file_type != FileType.DIR.value:
                    continue
                prefix = f"{folder.file_level_path or ''}/{folder.id}"
                descendants.append(
                    or_(
                        KnowledgeFile.file_level_path == prefix,
                        KnowledgeFile.file_level_path.like(f"{prefix}/%"),
                    )
                )
            selection_filter = []
            if file_ids:
                selection_filter.append(col(KnowledgeFile.id).in_(file_ids))
            selection_filter.extend(descendants)
            if not selection_filter:
                continue
            rows = (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == space_id,
                        KnowledgeFile.file_type == FileType.FILE.value,
                        KnowledgeFile.deleted_at.is_(None),
                        or_(*selection_filter),
                    )
                )
            ).all()
            results.update({int(row.id): row for row in rows})
        return sorted(results.values(), key=lambda item: int(item.id))

    async def find_versions_by_file_ids(
        self,
        file_ids: set[int],
    ) -> list[KnowledgeDocumentVersion]:
        if not file_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeDocumentVersion).where(
                        col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids)
                    )
                )
            ).all()
        )

    async def find_documents_by_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeDocument]:
        if not document_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeDocument).where(
                        col(KnowledgeDocument.id).in_(document_ids)
                    )
                )
            ).all()
        )

    async def find_versions_by_document_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeDocumentVersion]:
        if not document_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeDocumentVersion)
                    .where(col(KnowledgeDocumentVersion.document_id).in_(document_ids))
                    .order_by(
                        KnowledgeDocumentVersion.document_id,
                        KnowledgeDocumentVersion.version_no,
                    )
                )
            ).all()
        )

    async def find_files_by_ids(
        self,
        file_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not file_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids))
                )
            ).all()
        )

    async def find_entries_by_document_ids(
        self,
        document_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not document_ids:
            return []
        return list(
            (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        col(KnowledgeFile.reference_document_id).in_(document_ids)
                    )
                )
            ).all()
        )

    async def list_target_files(
        self,
        target_space_id: int,
    ) -> list[KnowledgeFile]:
        return list(
            (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == target_space_id,
                        KnowledgeFile.file_type == FileType.FILE.value,
                        KnowledgeFile.deleted_at.is_(None),
                        or_(
                            KnowledgeFile.entry_type.is_(None),
                            KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                        ),
                    )
                )
            ).all()
        )

    async def list_target_folders(
        self,
        target_space_id: int,
    ) -> list[KnowledgeFile]:
        return list(
            (
                await self.session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == target_space_id,
                        KnowledgeFile.file_type == FileType.DIR.value,
                        KnowledgeFile.deleted_at.is_(None),
                    )
                )
            ).all()
        )
