from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, delete, exists, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)


class KnowledgeFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)
        track_fulltext_file_changes(session)

    async def save(self, entity: KnowledgeFile) -> KnowledgeFile:
        self.session.add(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_saved",
        )
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: KnowledgeFile) -> KnowledgeFile:
        merged = await self.session.merge(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_updated",
        )
        await self.session.refresh(merged)
        return merged

    async def delete(self, entity_id: int) -> bool:
        entity = await self.find_by_id(entity_id)
        if entity is None:
            return False
        await self.session.delete(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_deleted",
        )
        return True

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

    async def find_by_id_for_update(self, entity_id: int) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(KnowledgeFile.id == entity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def set_parse_priority_if_unset(
        self,
        file_id: int,
        priority: str,
    ) -> KnowledgeFile | None:
        try:
            await self.session.execute(
                update(KnowledgeFile)
                .where(
                    KnowledgeFile.id == file_id,
                    KnowledgeFile.parse_priority.is_(None),
                )
                .values(parse_priority=priority)
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.find_by_id(file_id)

    async def find_by_ids_in_knowledge(
        self,
        entity_ids: list[int],
        knowledge_id: int,
    ) -> list[KnowledgeFile]:
        if not entity_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                col(KnowledgeFile.id).in_(entity_ids),
                KnowledgeFile.knowledge_id == knowledge_id,
            )
        )
        return list(result.scalars().all())

    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> list[KnowledgeFile]:
        if not entity_ids:
            return []
        stmt = (
            select(KnowledgeFile)
            .where(col(KnowledgeFile.id).in_(sorted(set(entity_ids))))
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_favorite_referrers_by_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> list[KnowledgeFile]:
        normalized_ids = {int(file_id) for file_id in source_file_ids if int(file_id) > 0}
        if not normalized_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                KnowledgeFile.file_source == "favorite_reference",
            )
        )
        rows = list(result.scalars().all())
        matched: list[KnowledgeFile] = []
        for row in rows:
            reference = (row.user_metadata or {}).get("favorite_reference") or {}
            try:
                source_file_id = int(reference.get("source_file_id") or 0)
            except (TypeError, ValueError):
                continue
            if source_file_id in normalized_ids:
                matched.append(row)
        return matched

    async def prepare_delete_by_ids(self, entity_ids: list[int]) -> int:
        if not entity_ids:
            return 0
        result = await self.session.execute(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(entity_ids)))
        await self.session.flush()
        return int(result.rowcount or 0)

    async def find_distribution_entries_by_document_id(
        self,
        document_id: int,
        *,
        statuses: set[str] | None = None,
        for_update: bool = False,
    ) -> list[KnowledgeFile]:
        stmt = (
            select(KnowledgeFile)
            .where(KnowledgeFile.reference_document_id == document_id)
            .order_by(KnowledgeFile.id.asc())
            .execution_options(populate_existing=True)
        )
        if statuses is not None:
            stmt = stmt.where(col(KnowledgeFile.entry_status).in_(sorted(statuses)))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_entry_in_space_for_update(
        self,
        document_id: int,
        knowledge_id: int,
    ) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.knowledge_id == knowledge_id,
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.ACTIVE.value,
                        KnowledgeFileEntryStatus.DELETING.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def has_visible_content_in_space(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        md5: str,
    ) -> bool:
        if not md5:
            return False

        any_version = select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
        )
        primary_version = (
            select(KnowledgeDocumentVersion.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.primary_version_id == KnowledgeDocumentVersion.id,
            )
            .where(
                KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
            )
        )
        physical_stmt = (
            select(KnowledgeFile.id)
            .where(
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFile.md5 == md5,
                col(KnowledgeFile.deleted_at).is_(None),
                or_(
                    KnowledgeFile.entry_type.is_(None),
                    and_(
                        KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                    ),
                ),
                or_(
                    ~exists(any_version),
                    exists(primary_version),
                ),
            )
            .limit(1)
        )
        physical_result = await self.session.exec(physical_stmt)
        if physical_result.first() is not None:
            return True

        logical_entry = aliased(KnowledgeFile)
        content_file = aliased(KnowledgeFile)
        logical_stmt = (
            select(logical_entry.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == logical_entry.reference_document_id,
            )
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeDocument.primary_version_id,
            )
            .join(
                content_file,
                content_file.id == KnowledgeDocumentVersion.knowledge_file_id,
            )
            .where(
                logical_entry.tenant_id == tenant_id,
                logical_entry.knowledge_id == knowledge_id,
                col(logical_entry.deleted_at).is_(None),
                col(logical_entry.entry_type).in_(
                    [
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
                logical_entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                content_file.tenant_id == tenant_id,
                content_file.file_type == FileType.FILE.value,
                content_file.status == KnowledgeFileStatus.SUCCESS.value,
                content_file.md5 == md5,
                col(content_file.deleted_at).is_(None),
            )
            .limit(1)
        )
        logical_result = await self.session.exec(logical_stmt)
        return logical_result.first() is not None

    async def find_manager_for_update(
        self,
        document_id: int,
    ) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_approval_instance_id(
        self,
        approval_instance_id: int,
    ) -> KnowledgeFile | None:
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.approval_instance_id == approval_instance_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.id.asc())
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def mark_document_entries_content_generation(
        self,
        document_id: int,
        generation: int,
    ) -> int:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            )
            .values(
                desired_content_generation=generation,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def request_projection_rebuild(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                KnowledgeFile.projection_status == KnowledgeFileProjectionStatus.READY.value,
                KnowledgeFile.projection_lease_owner.is_(None),
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
                projection_lease_owner=None,
                projection_lease_until=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    @staticmethod
    def _projection_candidate_predicate(now: datetime):
        is_distribution_row = or_(
            KnowledgeFile.reference_document_id.is_not(None),
            KnowledgeFile.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        )
        has_work = or_(
            KnowledgeFile.desired_content_generation > KnowledgeFile.applied_content_generation,
            KnowledgeFile.desired_entry_generation > KnowledgeFile.applied_entry_generation,
            col(KnowledgeFile.projection_status).in_(
                [
                    KnowledgeFileProjectionStatus.PENDING.value,
                    KnowledgeFileProjectionStatus.FAILED.value,
                    KnowledgeFileProjectionStatus.PROCESSING.value,
                ]
            ),
            KnowledgeFile.entry_status == KnowledgeFileEntryStatus.DELETING.value,
            KnowledgeFile.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        )
        retry_due = or_(
            KnowledgeFile.projection_next_retry_at.is_(None),
            KnowledgeFile.projection_next_retry_at <= now,
        )
        lease_available = or_(
            KnowledgeFile.projection_lease_until.is_(None),
            KnowledgeFile.projection_lease_until <= now,
        )
        return and_(
            is_distribution_row,
            col(KnowledgeFile.entry_status).in_(
                [
                    KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFileEntryStatus.DELETING.value,
                    KnowledgeFileEntryStatus.INVALID.value,
                ]
            ),
            has_work,
            retry_due,
            lease_available,
        )

    async def find_projection_candidates(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[KnowledgeFile]:
        if limit <= 0:
            return []
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(self._projection_candidate_predicate(now))
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def claim_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
    ) -> KnowledgeFile | None:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                self._projection_candidate_predicate(now),
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PROCESSING.value,
                projection_lease_owner=lease_owner,
                projection_lease_until=lease_until,
            )
        )
        await self.session.flush()
        if int(result.rowcount or 0) != 1:
            return None
        return await self.find_by_id(entry_id)

    async def apply_projection_result(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        target_content_generation: int,
        target_entry_generation: int,
    ) -> bool:
        target_is_current = and_(
            KnowledgeFile.desired_content_generation == target_content_generation,
            KnowledgeFile.desired_entry_generation == target_entry_generation,
        )
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.projection_lease_owner == lease_owner,
                KnowledgeFile.applied_content_generation <= target_content_generation,
                KnowledgeFile.applied_entry_generation <= target_entry_generation,
            )
            .values(
                applied_content_generation=target_content_generation,
                applied_entry_generation=target_entry_generation,
                projection_status=case(
                    (
                        target_is_current,
                        KnowledgeFileProjectionStatus.READY.value,
                    ),
                    else_=KnowledgeFileProjectionStatus.PENDING.value,
                ),
                projection_retry_count=0,
                projection_next_retry_at=None,
                projection_lease_owner=None,
                projection_lease_until=None,
                projection_last_error=None,
                projection_previous_file_id=case(
                    (
                        and_(
                            target_is_current,
                            col(KnowledgeFile.entry_status).in_(
                                [
                                    KnowledgeFileEntryStatus.ACTIVE.value,
                                    KnowledgeFileEntryStatus.INVALID.value,
                                ]
                            ),
                        ),
                        None,
                    ),
                    else_=KnowledgeFile.projection_previous_file_id,
                ),
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def fail_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        next_retry_at: datetime,
        error_summary: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.projection_lease_owner == lease_owner,
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.FAILED.value,
                projection_retry_count=KnowledgeFile.projection_retry_count + 1,
                projection_next_retry_at=next_retry_at,
                projection_lease_owner=None,
                projection_lease_until=None,
                projection_last_error=error_summary[:4000],
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def activate_prepared_entry(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.PREPARING.value,
            )
            .values(
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                desired_entry_generation=(KnowledgeFile.desired_entry_generation + 1),
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def mark_entry_deleting(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.ACTIVE.value,
                    ]
                ),
            )
            .values(
                entry_status=KnowledgeFileEntryStatus.DELETING.value,
                desired_entry_generation=(KnowledgeFile.desired_entry_generation + 1),
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def find_permission_reconcile_candidates(
        self,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[KnowledgeFile]:
        if limit <= 0:
            return []
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.DELETING.value,
                    ]
                ),
                KnowledgeFile.update_time <= older_than,
            )
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

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
