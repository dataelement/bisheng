"""Domain lifecycle for single-entity knowledge publish/share."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
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
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationError,
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation

logger = logging.getLogger(__name__)

PUBLISH_DUPLICATE_CONTENT_MESSAGE = "目标知识库已存在相同内容的文件，不能重复发布"  # noqa: RUF001

PermissionSnapshotLoader = Callable[
    [int],
    Awaitable[Sequence[TupleOperation]],
]


class KnowledgeDocumentDistributionError(RuntimeError):
    """Raised when a publish/share lifecycle invariant would be violated."""


@dataclass(frozen=True)
class CanonicalManagerSnapshot:
    document_id: int
    manager_file_id: int
    manager_space_id: int
    original_uploader_id: int | None = None
    original_knowledge_id: int | None = None


@dataclass(frozen=True)
class PublishKnowledgeDocumentCommand:
    tenant_id: int
    approval_instance_id: int
    document_id: int
    source_entry_id: int
    target_space_id: int
    target_file_level_path: str = ""
    target_level: int = 0
    target_document_id: int | None = None


@dataclass(frozen=True)
class PublishKnowledgeDocumentResult:
    document_id: int
    manager_file_id: int
    publish_entry_id: int
    target_space_id: int
    idempotent: bool


@dataclass(frozen=True)
class ShareKnowledgeDocumentCommand:
    tenant_id: int
    approval_instance_id: int
    document_id: int
    source_entry_id: int
    target_space_id: int
    allow_download: bool = False
    target_file_level_path: str = ""
    target_level: int = 0


@dataclass(frozen=True)
class ShareKnowledgeDocumentResult:
    document_id: int
    manager_file_id: int
    share_entry_id: int
    target_space_id: int
    idempotent: bool


@dataclass(frozen=True)
class RemoveShareEntryResult:
    document_id: int
    share_entry_id: int
    idempotent: bool


@dataclass(frozen=True)
class DeleteManagerResult:
    document_id: int
    manager_file_id: int
    action: str
    tombstone_entry_id: int | None = None
    idempotent: bool = False


@dataclass(frozen=True)
class SwitchPrimaryManagerResult:
    document_id: int
    manager_file_id: int
    previous_manager_file_id: int
    primary_version_id: int
    content_generation: int
    idempotent: bool = False


async def _default_permission_snapshot_loader(
    file_id: int,
) -> Sequence[TupleOperation]:
    from bisheng.permission.domain.services.permission_service import (
        PermissionService,
    )

    fga = await PermissionService._aget_fga()
    if fga is None:
        raise KnowledgeDocumentDistributionError("OpenFGA is unavailable while snapshotting source permissions")
    tuples = await fga.read_tuples(object=f"knowledge_file:{file_id}")
    return [
        TupleOperation(
            action="write",
            user=str(item["user"]),
            relation=str(item["relation"]),
            object=f"knowledge_file:{file_id}",
        )
        for item in tuples
        if item.get("relation") != "parent" and item.get("user") and item.get("relation")
    ]


class KnowledgeDocumentDistributionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        document_repository: KnowledgeDocumentRepository,
        version_repository: KnowledgeDocumentVersionRepository,
        file_repository: KnowledgeFileRepository,
        permission_activation_service: KnowledgeDocumentPermissionActivationService,
        permission_snapshot_loader: PermissionSnapshotLoader = (_default_permission_snapshot_loader),
    ):
        self.session = session
        self.document_repository = document_repository
        self.version_repository = version_repository
        self.file_repository = file_repository
        self.permission_activation_service = permission_activation_service
        self.permission_snapshot_loader = permission_snapshot_loader
        track_fulltext_file_changes(self.session)

    async def _commit(self) -> None:
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="document_distribution_updated",
        )

    async def _lock_published_spaces(self, space_ids: set[int]) -> None:
        normalized = sorted({int(item) for item in space_ids})
        result = await self.session.execute(
            select(Knowledge)
            .where(col(Knowledge.id).in_(normalized))
            .order_by(Knowledge.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        spaces = list(result.scalars().all())
        if len(spaces) != len(normalized) or any(
            item.state != KnowledgeState.PUBLISHED.value for item in spaces
        ):
            raise KnowledgeDocumentDistributionError(
                "source or target knowledge space is no longer published"
            )

    async def _ensure_publish_target_content_not_duplicate(
        self,
        command: PublishKnowledgeDocumentCommand,
        *,
        lock_target_space: bool = False,
        source_md5: str | None = None,
    ) -> None:
        resolved_md5 = str(source_md5).strip() if source_md5 is not None else None
        if resolved_md5 is None:
            manager = await self.file_repository.find_by_id(command.source_entry_id)
            if manager is None:
                raise KnowledgeDocumentDistributionError("publish manager no longer exists")
            resolved_md5 = str(manager.md5 or "").strip()
        if not resolved_md5:
            return

        if lock_target_space:
            target_result = await self.session.exec(
                select(Knowledge.id)
                .where(
                    Knowledge.id == command.target_space_id,
                    Knowledge.tenant_id == command.tenant_id,
                )
                .with_for_update()
            )
            if target_result.first() is None:
                raise KnowledgeDocumentDistributionError("publish target space no longer exists")

        if await self.file_repository.has_visible_content_in_space(
            tenant_id=command.tenant_id,
            knowledge_id=command.target_space_id,
            md5=resolved_md5,
        ):
            raise KnowledgeDocumentDistributionError(PUBLISH_DUPLICATE_CONTENT_MESSAGE)

    async def _discard_duplicate_publish_preparation(
        self,
        *,
        command: PublishKnowledgeDocumentCommand,
        publish_entry_id: int,
    ) -> None:
        locked_files = await self.file_repository.find_by_ids_for_update([command.source_entry_id, publish_entry_id])
        file_map = {int(item.id): item for item in locked_files}
        manager = file_map.get(command.source_entry_id)
        publish = file_map.get(publish_entry_id)
        if (
            manager is not None
            and manager.entry_status == KnowledgeFileEntryStatus.PREPARING.value
            and int(manager.approval_instance_id or 0) == command.approval_instance_id
        ):
            manager.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
            manager.approval_instance_id = None
            self.session.add(manager)
        if (
            publish is not None
            and publish.entry_status == KnowledgeFileEntryStatus.PREPARING.value
            and int(publish.approval_instance_id or 0) == command.approval_instance_id
        ):
            await self.session.delete(publish)
        await self.session.flush()
        await self._commit()

    async def _load_or_create_primary_document(
        self,
        *,
        tenant_id: int,
        source_file_id: int,
    ) -> tuple[KnowledgeFile, KnowledgeDocument]:
        source_file = await self.file_repository.find_by_id_for_update(source_file_id)
        if source_file is None:
            raise KnowledgeDocumentDistributionError("source file does not exist")
        if int(source_file.tenant_id or 0) != int(tenant_id):
            raise KnowledgeDocumentDistributionError("source tenant mismatch")
        if source_file.file_type != FileType.FILE.value or source_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise KnowledgeDocumentDistributionError("only a parsed file can become manager")
        if source_file.entry_type in {
            KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFileEntryType.SHARE.value,
            KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        }:
            raise KnowledgeDocumentDistributionError("source entry is not the current manager")

        if source_file.original_uploader_id is None and source_file.user_id is not None:
            source_file.original_uploader_id = int(source_file.user_id)
        if source_file.original_knowledge_id is None:
            source_file.original_knowledge_id = int(source_file.knowledge_id)
        self.session.add(source_file)

        version = await self.version_repository.find_by_knowledge_file_id(source_file_id)
        if version is None:
            document = KnowledgeDocument(
                tenant_id=tenant_id,
                knowledge_id=int(source_file.knowledge_id),
                file_level_path=source_file.file_level_path,
                level=int(source_file.level or 0),
            )
            self.session.add(document)
            await self.session.flush()
            version = KnowledgeDocumentVersion(
                document_id=int(document.id),
                knowledge_file_id=int(source_file.id),
                version_no=1,
                is_primary=True,
            )
            self.session.add(version)
            await self.session.flush()
            document.primary_version_id = int(version.id)
        else:
            document = await self.document_repository.find_by_id_for_update(int(version.document_id))
            if document is None:
                raise KnowledgeDocumentDistributionError("source version has no canonical document")
            if int(document.tenant_id or 0) != int(tenant_id):
                raise KnowledgeDocumentDistributionError("canonical document tenant mismatch")
            if int(document.primary_version_id or 0) != int(version.id or 0):
                raise KnowledgeDocumentDistributionError("historical version cannot become manager")

        return source_file, document

    async def ensure_document_identity(
        self,
        *,
        tenant_id: int,
        source_file_id: int,
    ) -> CanonicalManagerSnapshot:
        """Create the stable document identity without activating manager behavior."""
        source_file, document = await self._load_or_create_primary_document(
            tenant_id=tenant_id,
            source_file_id=source_file_id,
        )
        self.session.add(document)
        await self.session.flush()
        await self._commit()
        return CanonicalManagerSnapshot(
            document_id=int(document.id),
            manager_file_id=int(source_file.id),
            manager_space_id=int(source_file.knowledge_id),
            original_uploader_id=source_file.original_uploader_id,
            original_knowledge_id=source_file.original_knowledge_id,
        )

    async def normalize_manager(
        self,
        *,
        tenant_id: int,
        source_file_id: int,
        expected_document_id: int | None = None,
    ) -> CanonicalManagerSnapshot:
        source_file, document = await self._load_or_create_primary_document(
            tenant_id=tenant_id,
            source_file_id=source_file_id,
        )
        if expected_document_id is not None and int(document.id) != int(expected_document_id):
            await self.session.rollback()
            raise KnowledgeDocumentDistributionError("source canonical document has changed")

        source_file.reference_document_id = int(document.id)
        source_file.entry_type = KnowledgeFileEntryType.MANAGER.value
        source_file.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        source_file.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        source_file.desired_content_generation = document.content_generation
        source_file.applied_content_generation = 0
        source_file.desired_entry_generation += 1
        source_file.applied_entry_generation = 0
        self.session.add(source_file)
        self.session.add(document)
        await self.session.flush()
        await self._commit()
        return CanonicalManagerSnapshot(
            document_id=int(document.id),
            manager_file_id=int(source_file.id),
            manager_space_id=int(source_file.knowledge_id),
            original_uploader_id=source_file.original_uploader_id,
            original_knowledge_id=source_file.original_knowledge_id,
        )

    async def restore_unapproved_manager(
        self,
        *,
        tenant_id: int,
        document_id: int,
        source_file_id: int,
    ) -> bool:
        """Demote only a standalone manager created before approval completed."""
        document = await self.document_repository.find_by_id_for_update(document_id)
        source_file = await self.file_repository.find_by_id_for_update(source_file_id)
        if document is None or source_file is None:
            await self.session.rollback()
            return False
        if (
            int(document.tenant_id or 0) != int(tenant_id)
            or int(source_file.tenant_id or 0) != int(tenant_id)
            or int(document.knowledge_id or 0) != int(source_file.knowledge_id or 0)
            or document.predecessor_logic_file_id is not None
            or source_file.reference_document_id != int(document_id)
            or source_file.entry_type != KnowledgeFileEntryType.MANAGER.value
            or source_file.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
        ):
            await self.session.rollback()
            return False

        version = await self.version_repository.find_by_knowledge_file_id(source_file_id)
        if version is None or int(document.primary_version_id or 0) != int(version.id or 0):
            await self.session.rollback()
            return False

        entries = await self.file_repository.find_distribution_entries_by_document_id(
            document_id,
            for_update=True,
        )
        if any(int(entry.id) != int(source_file_id) for entry in entries):
            await self.session.rollback()
            return False

        source_file.reference_document_id = None
        source_file.entry_type = None
        source_file.entry_status = None
        source_file.approval_instance_id = None
        source_file.allow_download = False
        source_file.projection_status = KnowledgeFileProjectionStatus.READY.value
        source_file.projection_retry_count = 0
        source_file.projection_next_retry_at = None
        source_file.projection_lease_owner = None
        source_file.projection_lease_until = None
        source_file.projection_last_error = None
        source_file.projection_previous_file_id = None
        source_file.desired_content_generation = 0
        source_file.applied_content_generation = 0
        source_file.desired_entry_generation = 0
        source_file.applied_entry_generation = 0
        self.session.add(source_file)
        await self.session.flush()
        await self._commit()
        return True

    async def _ensure_canonical_name_available(
        self,
        *,
        entries: Sequence[KnowledgeFile],
        file_name: str,
        excluded_file_ids: set[int],
    ) -> None:
        for entry in entries:
            if entry.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
                continue
            if entry.file_level_path:
                path_filter = KnowledgeFile.file_level_path == entry.file_level_path
            else:
                path_filter = or_(
                    KnowledgeFile.file_level_path.is_(None),
                    KnowledgeFile.file_level_path == "",
                )
            stmt = (
                select(KnowledgeFile.id)
                .where(
                    KnowledgeFile.knowledge_id == int(entry.knowledge_id),
                    KnowledgeFile.file_type == FileType.FILE.value,
                    KnowledgeFile.file_name == file_name,
                    path_filter,
                    col(KnowledgeFile.deleted_at).is_(None),
                )
                .limit(1)
            )
            if excluded_file_ids:
                stmt = stmt.where(col(KnowledgeFile.id).not_in(sorted(excluded_file_ids)))
            conflict = (await self.session.execute(stmt)).scalars().first()
            if conflict is not None:
                raise KnowledgeDocumentDistributionError("canonical name conflict in an active entry directory")

    async def _replace_primary_tag_links(
        self,
        *,
        tenant_id: int,
        source_file_id: int,
        target_file_id: int,
    ) -> None:
        """随主版本切换迁移 canonical 标签关系, 不复制到逻辑入口。"""
        from bisheng.database.models.group_resource import (
            ResourceTypeEnum,
        )
        from bisheng.database.models.review_tags import ReviewTagLink
        from bisheng.database.models.tag import TagLink

        resource_type = ResourceTypeEnum.SPACE_FILE.value
        source_resource_id = str(source_file_id)
        target_resource_id = str(target_file_id)
        tag_rows = list(
            (
                await self.session.execute(
                    select(TagLink)
                    .where(
                        TagLink.resource_id == source_resource_id,
                        TagLink.resource_type == resource_type,
                    )
                    .order_by(TagLink.id.asc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        review_rows = list(
            (
                await self.session.execute(
                    select(ReviewTagLink)
                    .where(
                        ReviewTagLink.resource_id == source_resource_id,
                        ReviewTagLink.resource_type == resource_type,
                        ReviewTagLink.is_deleted.is_(False),
                    )
                    .order_by(ReviewTagLink.id.asc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        await self.session.execute(
            delete(TagLink).where(
                TagLink.resource_id == target_resource_id,
                TagLink.resource_type == resource_type,
            )
        )
        await self.session.execute(
            delete(ReviewTagLink).where(
                ReviewTagLink.resource_id == target_resource_id,
                ReviewTagLink.resource_type == resource_type,
            )
        )
        for row in tag_rows:
            self.session.add(
                TagLink(
                    tag_id=int(row.tag_id),
                    resource_id=target_resource_id,
                    resource_type=resource_type,
                    user_id=int(row.user_id or 0),
                    tenant_id=tenant_id,
                )
            )
        for row in review_rows:
            self.session.add(
                ReviewTagLink(
                    tag_id=int(row.tag_id),
                    resource_id=target_resource_id,
                    resource_type=resource_type,
                    user_id=int(row.user_id or 0),
                    tenant_id=tenant_id,
                    is_deleted=False,
                    remark=row.remark,
                )
            )
        await self.session.flush()

    @staticmethod
    def _validate_switch_manager_state(
        *,
        tenant_id: int,
        document: KnowledgeDocument | None,
        current_manager: KnowledgeFile | None,
        target_version: KnowledgeDocumentVersion | None,
        target_file: KnowledgeFile | None,
    ) -> None:
        if document is None or current_manager is None or target_version is None or target_file is None:
            raise KnowledgeDocumentDistributionError("primary switch state no longer exists")
        if (
            int(document.tenant_id or 0) != tenant_id
            or int(current_manager.tenant_id or 0) != tenant_id
            or int(target_file.tenant_id or 0) != tenant_id
            or int(current_manager.reference_document_id or 0) != int(document.id)
            or current_manager.entry_type != KnowledgeFileEntryType.MANAGER.value
            or current_manager.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
            or int(target_version.document_id) != int(document.id)
            or int(target_version.knowledge_file_id) != int(target_file.id)
        ):
            raise KnowledgeDocumentDistributionError("primary switch requires the active canonical manager")
        if target_file.file_type != FileType.FILE.value or target_file.status != KnowledgeFileStatus.SUCCESS.value:
            raise KnowledgeDocumentDistributionError("target primary version is not parsed successfully")

    async def switch_primary_manager(
        self,
        *,
        tenant_id: int,
        document_id: int,
        current_manager_file_id: int,
        target_version_id: int,
    ) -> SwitchPrimaryManagerResult:
        """Switch the physical manager after permission prewrite."""
        document = await self.document_repository.find_by_id(document_id)
        target_version = await self.version_repository.find_by_id(target_version_id)
        current_manager = await self.file_repository.find_by_id(current_manager_file_id)
        target_file = (
            await self.file_repository.find_by_id(int(target_version.knowledge_file_id))
            if target_version is not None
            else None
        )
        self._validate_switch_manager_state(
            tenant_id=tenant_id,
            document=document,
            current_manager=current_manager,
            target_version=target_version,
            target_file=target_file,
        )
        if int(document.primary_version_id or 0) == target_version_id:
            return SwitchPrimaryManagerResult(
                document_id=document_id,
                manager_file_id=current_manager_file_id,
                previous_manager_file_id=current_manager_file_id,
                primary_version_id=target_version_id,
                content_generation=int(document.content_generation),
                idempotent=True,
            )

        versions = await self.version_repository.find_by_document_id(document_id)
        entries = await self.file_repository.find_distribution_entries_by_document_id(
            document_id,
            statuses={KnowledgeFileEntryStatus.ACTIVE.value},
        )
        excluded_file_ids = {int(version.knowledge_file_id) for version in versions} | {
            int(entry.id) for entry in entries
        }
        await self._ensure_canonical_name_available(
            entries=entries,
            file_name=str(target_file.file_name),
            excluded_file_ids=excluded_file_ids,
        )
        explicit_snapshot = list(await self.permission_snapshot_loader(current_manager_file_id))
        manager_candidate = target_file.model_copy(
            update={
                "knowledge_id": int(document.knowledge_id),
                "file_level_path": current_manager.file_level_path,
                "level": current_manager.level,
            }
        )
        target_parent = self.permission_activation_service.build_parent_operation(
            manager_candidate,
            action="write",
        )
        try:
            await self.permission_activation_service.tuple_writer(
                [
                    target_parent,
                    *self._retarget_explicit_operations(
                        explicit_snapshot,
                        target_file_id=int(target_file.id),
                        action="write",
                    ),
                ]
            )
        except Exception as exc:
            raise KnowledgeDocumentDistributionError("primary switch permission prewrite failed") from exc

        await self._commit()
        document = await self.document_repository.find_by_id_for_update(document_id)
        locked_files = await self.file_repository.find_by_ids_for_update(sorted(excluded_file_ids))
        file_map = {int(item.id): item for item in locked_files}
        current_manager = file_map.get(current_manager_file_id)
        target_file = file_map.get(int(target_version.knowledge_file_id))
        version_result = await self.session.execute(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        versions = list(version_result.scalars().all())
        version_map = {int(item.id): item for item in versions}
        target_version = version_map.get(target_version_id)
        self._validate_switch_manager_state(
            tenant_id=tenant_id,
            document=document,
            current_manager=current_manager,
            target_version=target_version,
            target_file=target_file,
        )
        if int(document.primary_version_id or 0) != int(
            next(
                (version.id for version in versions if int(version.knowledge_file_id) == current_manager_file_id),
                0,
            )
        ):
            raise KnowledgeDocumentDistributionError("primary switch state changed concurrently")

        entries = [
            item
            for item in locked_files
            if int(item.reference_document_id or 0) == document_id
            and item.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
        ]
        await self._ensure_canonical_name_available(
            entries=entries,
            file_name=str(target_file.file_name),
            excluded_file_ids=excluded_file_ids,
        )
        old_parent_delete = self.permission_activation_service.build_parent_operation(
            current_manager,
            action="delete",
        )
        await self._replace_primary_tag_links(
            tenant_id=tenant_id,
            source_file_id=current_manager_file_id,
            target_file_id=int(target_file.id),
        )
        previous_manager_path = current_manager.file_level_path
        previous_manager_level = current_manager.level

        document.primary_version_id = target_version_id
        document.content_generation += 1
        for version in versions:
            version.is_primary = int(version.id) == target_version_id
            self.session.add(version)

        current_manager.entry_type = None
        current_manager.entry_status = None
        # 历史物理版本通过 KnowledgeDocumentVersion 保留 durable identity,
        # 不再作为分发入口参与入口扫描和最终删除收敛。
        current_manager.reference_document_id = None
        current_manager.projection_previous_file_id = None

        target_file.knowledge_id = int(document.knowledge_id)
        if target_file.original_uploader_id is None:
            target_file.original_uploader_id = current_manager.original_uploader_id
        if target_file.original_knowledge_id is None:
            target_file.original_knowledge_id = current_manager.original_knowledge_id
        target_file.file_level_path = previous_manager_path
        target_file.level = previous_manager_level
        target_file.reference_document_id = document_id
        target_file.entry_type = KnowledgeFileEntryType.MANAGER.value
        target_file.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        target_file.projection_previous_file_id = current_manager_file_id
        target_file.desired_entry_generation += 1
        target_file.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        target_file.projection_next_retry_at = None

        for entry in entries:
            if int(entry.id) == current_manager_file_id:
                continue
            entry.file_name = target_file.file_name
            self.session.add(entry)
        self.session.add(document)
        self.session.add(current_manager)
        self.session.add(target_file)
        await self.session.flush()
        await self.file_repository.mark_document_entries_content_generation(
            document_id,
            int(document.content_generation),
        )
        await self._commit()

        try:
            await self.permission_activation_service.tuple_writer(
                [
                    old_parent_delete,
                    *self._retarget_explicit_operations(
                        explicit_snapshot,
                        target_file_id=current_manager_file_id,
                        action="delete",
                    ),
                ]
            )
        except Exception:
            logger.exception(
                "F059 old manager permission cleanup deferred after primary "
                "switch: document_id=%s previous_manager_file_id=%s",
                document_id,
                current_manager_file_id,
            )

        return SwitchPrimaryManagerResult(
            document_id=document_id,
            manager_file_id=int(target_file.id),
            previous_manager_file_id=current_manager_file_id,
            primary_version_id=target_version_id,
            content_generation=int(document.content_generation),
        )

    async def rename_manager_document(
        self,
        *,
        tenant_id: int,
        document_id: int,
        manager_file_id: int,
        new_name: str,
        updater_id: int,
        updater_name: str | None,
        user_metadata: dict | None = None,
        clear_alias: bool = False,
    ) -> KnowledgeFile:
        document = await self.document_repository.find_by_id_for_update(document_id)
        manager = await self.file_repository.find_by_id_for_update(manager_file_id)
        primary_version = (
            await self.version_repository.find_by_id(int(document.primary_version_id))
            if document is not None and document.primary_version_id is not None
            else None
        )
        self._validate_switch_manager_state(
            tenant_id=tenant_id,
            document=document,
            current_manager=manager,
            target_version=primary_version,
            target_file=manager,
        )
        entries = await self.file_repository.find_distribution_entries_by_document_id(
            document_id,
            statuses={KnowledgeFileEntryStatus.ACTIVE.value},
            for_update=True,
        )
        versions = await self.version_repository.find_by_document_id(document_id)
        excluded_file_ids = {int(version.knowledge_file_id) for version in versions} | {
            int(entry.id) for entry in entries
        }
        await self._ensure_canonical_name_available(
            entries=entries,
            file_name=new_name,
            excluded_file_ids=excluded_file_ids,
        )

        document.content_generation += 1
        for entry in entries:
            entry.file_name = new_name
            entry.updater_id = updater_id
            entry.updater_name = updater_name
            self.session.add(entry)
        manager.file_name = new_name
        if user_metadata is not None:
            manager.user_metadata = user_metadata
        if clear_alias:
            manager.alias_name = None
        self.session.add(document)
        self.session.add(manager)
        await self.session.flush()
        await self.file_repository.mark_document_entries_content_generation(
            document_id,
            int(document.content_generation),
        )
        await self._commit()
        return manager

    async def touch_manager_content(
        self,
        *,
        tenant_id: int,
        document_id: int,
        manager_file_id: int,
    ) -> int:
        """Advance canonical content generation after a manager-only write."""
        document = await self.document_repository.find_by_id_for_update(document_id)
        manager = await self.file_repository.find_by_id_for_update(manager_file_id)
        primary_version = (
            await self.version_repository.find_by_id(int(document.primary_version_id))
            if document is not None and document.primary_version_id is not None
            else None
        )
        self._validate_switch_manager_state(
            tenant_id=tenant_id,
            document=document,
            current_manager=manager,
            target_version=primary_version,
            target_file=manager,
        )
        document.content_generation += 1
        self.session.add(document)
        await self.session.flush()
        await self.file_repository.mark_document_entries_content_generation(
            document_id,
            int(document.content_generation),
        )
        await self._commit()
        return int(document.content_generation)

    @staticmethod
    def _create_publish_entry(
        *,
        manager: KnowledgeFile,
        document: KnowledgeDocument,
        approval_instance_id: int,
    ) -> KnowledgeFile:
        return KnowledgeFile(
            tenant_id=int(manager.tenant_id),
            user_id=manager.user_id,
            user_name=manager.user_name,
            updater_id=manager.updater_id,
            updater_name=manager.updater_name,
            original_uploader_id=manager.original_uploader_id,
            original_knowledge_id=manager.original_knowledge_id,
            knowledge_id=int(manager.knowledge_id),
            file_name=manager.file_name,
            alias_name=manager.alias_name,
            file_type=FileType.FILE.value,
            file_source=manager.file_source,
            level=int(manager.level or 0),
            file_level_path=manager.file_level_path,
            abstract=manager.abstract,
            file_size=0,
            md5=None,
            parse_type=manager.parse_type,
            split_rule=manager.split_rule,
            thumbnails=None,
            preview_file_object_name=None,
            bbox_object_name="",
            object_name=None,
            status=manager.status,
            user_metadata=dict(manager.user_metadata or {}),
            remark=manager.remark,
            file_encoding=manager.file_encoding,
            file_subcategory_code=manager.file_subcategory_code,
            file_subcategory_source=manager.file_subcategory_source,
            simhash=manager.simhash,
            reference_document_id=int(document.id),
            entry_type=KnowledgeFileEntryType.PUBLISH.value,
            entry_status=KnowledgeFileEntryStatus.PREPARING.value,
            predecessor_logic_file_id=document.predecessor_logic_file_id,
            allow_download=False,
            approval_instance_id=approval_instance_id,
            projection_previous_file_id=int(manager.id),
            desired_content_generation=document.content_generation,
            applied_content_generation=0,
            desired_entry_generation=0,
            applied_entry_generation=0,
            projection_status=KnowledgeFileProjectionStatus.PENDING.value,
        )

    async def _validate_publish_authority(
        self,
        command: PublishKnowledgeDocumentCommand,
        document: KnowledgeDocument,
        manager: KnowledgeFile,
        *,
        allow_preparing_manager: bool = False,
    ) -> None:
        manager_status_is_valid = manager.entry_status == KnowledgeFileEntryStatus.ACTIVE.value or (
            allow_preparing_manager
            and manager.entry_status == KnowledgeFileEntryStatus.PREPARING.value
            and int(manager.approval_instance_id or 0) == command.approval_instance_id
        )
        if int(document.tenant_id or 0) != command.tenant_id or int(manager.tenant_id or 0) != command.tenant_id:
            raise KnowledgeDocumentDistributionError("publish tenant mismatch")
        if (
            int(document.primary_version_id or 0) <= 0
            or int(manager.reference_document_id or 0) != command.document_id
            or manager.entry_type != KnowledgeFileEntryType.MANAGER.value
            or not manager_status_is_valid
            or int(manager.id) != command.source_entry_id
            or int(manager.knowledge_id) != int(document.knowledge_id)
        ):
            raise KnowledgeDocumentDistributionError("publish source is not the current manager")
        existing_target = await self.file_repository.find_entry_in_space_for_update(
            command.document_id,
            command.target_space_id,
        )
        if existing_target is not None:
            raise KnowledgeDocumentDistributionError("canonical document already has an entry in target space")

    async def _prepare_manager_permission_transition(
        self,
        command: PublishKnowledgeDocumentCommand,
    ) -> KnowledgeFile:
        """Hide the moving manager before target permissions are prewritten."""
        manager = await self.file_repository.find_by_id_for_update(command.source_entry_id)
        if manager is None:
            raise KnowledgeDocumentDistributionError("publish manager no longer exists")
        if (
            int(manager.tenant_id or 0) != command.tenant_id
            or int(manager.reference_document_id or 0) != command.document_id
            or manager.entry_type != KnowledgeFileEntryType.MANAGER.value
        ):
            raise KnowledgeDocumentDistributionError("publish source is not the current manager")
        if (
            manager.entry_status == KnowledgeFileEntryStatus.PREPARING.value
            and int(manager.approval_instance_id or 0) == command.approval_instance_id
        ):
            await self._commit()
            return manager
        if manager.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
            raise KnowledgeDocumentDistributionError("publish manager permission transition is not retryable")
        manager.entry_status = KnowledgeFileEntryStatus.PREPARING.value
        manager.approval_instance_id = command.approval_instance_id
        self.session.add(manager)
        await self.session.flush()
        await self._commit()
        return manager

    async def _prepare_publish_entry(
        self,
        command: PublishKnowledgeDocumentCommand,
    ) -> KnowledgeFile:
        document_map: dict[int, KnowledgeDocument] = {}
        if command.target_document_id is not None:
            locked_documents = await self.document_repository.find_by_ids_for_update(
                [
                    command.document_id,
                    command.target_document_id,
                ]
            )
            document_map = {int(item.id): item for item in locked_documents}
            document = document_map.get(command.document_id)
        else:
            document = await self.document_repository.find_by_id_for_update(command.document_id)
        manager = await self.file_repository.find_by_id_for_update(command.source_entry_id)
        if document is None or manager is None:
            raise KnowledgeDocumentDistributionError("publish source state no longer exists")
        await self._validate_publish_authority(
            command,
            document,
            manager,
            allow_preparing_manager=True,
        )
        if command.target_document_id is not None:
            target_document = document_map.get(command.target_document_id)
            if target_document is None:
                raise KnowledgeDocumentDistributionError("target document does not exist")
            await self._validate_merge_target(
                command=command,
                source_document=document,
                target_document=target_document,
            )
        await self._ensure_publish_target_content_not_duplicate(command)
        publish = self._create_publish_entry(
            manager=manager,
            document=document,
            approval_instance_id=command.approval_instance_id,
        )
        self.session.add(publish)
        await self.session.flush()
        await self._commit()
        return publish

    async def _validate_merge_target(
        self,
        *,
        command: PublishKnowledgeDocumentCommand,
        source_document: KnowledgeDocument,
        target_document: KnowledgeDocument,
    ) -> tuple[
        KnowledgeDocumentVersion,
        KnowledgeDocumentVersion,
        KnowledgeFile,
    ]:
        if int(source_document.id) == int(target_document.id):
            raise KnowledgeDocumentDistributionError("source and target document must differ")
        if (
            int(target_document.tenant_id or 0) != command.tenant_id
            or int(target_document.knowledge_id) != command.target_space_id
            or target_document.lifecycle_status != KnowledgeDocumentLifecycleStatus.ACTIVE.value
            or target_document.predecessor_logic_file_id is not None
        ):
            raise KnowledgeDocumentDistributionError("target document is not eligible for merge")

        source_versions = await self.version_repository.find_by_document_id(int(source_document.id))
        target_versions = await self.version_repository.find_by_document_id(int(target_document.id))
        if len(source_versions) != 1 or not target_versions:
            raise KnowledgeDocumentDistributionError("merge requires a single-version source and a versioned target")
        target_primary = next(
            (version for version in target_versions if int(version.id) == int(target_document.primary_version_id or 0)),
            None,
        )
        if target_primary is None:
            raise KnowledgeDocumentDistributionError("target primary version pointer is invalid")
        target_manager = await self.file_repository.find_by_id_for_update(int(target_primary.knowledge_file_id))
        if (
            target_manager is None
            or int(target_manager.tenant_id or 0) != command.tenant_id
            or int(target_manager.knowledge_id) != command.target_space_id
        ):
            raise KnowledgeDocumentDistributionError("target primary file is not local to target space")
        target_entries = await self.file_repository.find_distribution_entries_by_document_id(
            int(target_document.id),
            for_update=True,
        )
        if target_entries and not (
            len(target_entries) == 1
            and int(target_entries[0].id) == int(target_manager.id)
            and target_entries[0].entry_type == KnowledgeFileEntryType.MANAGER.value
            and target_entries[0].entry_status == KnowledgeFileEntryStatus.ACTIVE.value
        ):
            raise KnowledgeDocumentDistributionError("distributed target document cannot be merged")
        return source_versions[0], target_primary, target_manager

    @staticmethod
    def _retarget_explicit_operations(
        operations: Sequence[TupleOperation],
        *,
        target_file_id: int,
        action: str,
    ) -> list[TupleOperation]:
        return [
            TupleOperation(
                action=action,
                user=operation.user,
                relation=operation.relation,
                object=f"knowledge_file:{target_file_id}",
            )
            for operation in operations
            if operation.relation != "parent"
        ]

    async def _activate_publish_transfer(
        self,
        *,
        command: PublishKnowledgeDocumentCommand,
        publish_entry_id: int,
        source_md5: str,
    ) -> None:
        source_entry = await self.file_repository.find_by_id(command.source_entry_id)
        if source_entry is None:
            raise KnowledgeDocumentDistributionError("publish source no longer exists")
        await self._lock_published_spaces(
            {int(source_entry.knowledge_id), int(command.target_space_id)}
        )
        await self._ensure_publish_target_content_not_duplicate(
            command,
            lock_target_space=True,
            source_md5=source_md5,
        )
        if command.target_document_id is not None:
            await self._activate_publish_merge(
                command=command,
                publish_entry_id=publish_entry_id,
            )
            return

        document = await self.document_repository.find_by_id_for_update(command.document_id)
        locked_files = await self.file_repository.find_by_ids_for_update([command.source_entry_id, publish_entry_id])
        file_map = {int(item.id): item for item in locked_files}
        manager = file_map.get(command.source_entry_id)
        publish = file_map.get(publish_entry_id)
        if document is None or manager is None or publish is None:
            raise KnowledgeDocumentDistributionError("publish activation state no longer exists")

        if (
            publish.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
            and int(document.knowledge_id) == command.target_space_id
            and int(document.predecessor_logic_file_id or 0) == publish_entry_id
        ):
            return
        await self._validate_publish_authority(
            command,
            document,
            manager,
            allow_preparing_manager=True,
        )
        if publish.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
            raise KnowledgeDocumentDistributionError("publish entry is not preparing")

        versions = await self.version_repository.find_by_document_id(command.document_id)
        physical_file_ids = sorted({int(version.knowledge_file_id) for version in versions})
        physical_files = await self.file_repository.find_by_ids_for_update(physical_file_ids)
        if len(physical_files) != len(physical_file_ids):
            raise KnowledgeDocumentDistributionError("canonical document has missing physical versions")

        document.content_generation += 1
        document.knowledge_id = command.target_space_id
        document.file_level_path = command.target_file_level_path
        document.level = command.target_level
        document.predecessor_logic_file_id = publish_entry_id

        for physical_file in physical_files:
            physical_file.knowledge_id = command.target_space_id
            self.session.add(physical_file)

        manager.knowledge_id = command.target_space_id
        manager.file_level_path = command.target_file_level_path
        manager.level = command.target_level
        # Keep a durable source anchor until the manager has been projected in
        # the target space.  The publish entry remains in the source space and
        # can resolve either its ready logical projection or the old physical
        # manager projection.  The projection CAS clears this anchor only after
        # the target manager projection is ready.
        manager.projection_previous_file_id = publish_entry_id
        manager.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        manager.approval_instance_id = None
        manager.desired_entry_generation += 1
        manager.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        manager.projection_next_retry_at = None

        publish.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        publish.desired_entry_generation += 1
        publish.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        publish.projection_next_retry_at = None

        self.session.add(document)
        self.session.add(manager)
        self.session.add(publish)
        await self.session.flush()
        await self.file_repository.mark_document_entries_content_generation(
            command.document_id,
            document.content_generation,
        )
        await self._commit()

    async def _activate_publish_merge(
        self,
        *,
        command: PublishKnowledgeDocumentCommand,
        publish_entry_id: int,
    ) -> None:
        if command.target_document_id is None:
            raise KnowledgeDocumentDistributionError("target document is required for merge")
        documents = await self.document_repository.find_by_ids_for_update(
            [command.document_id, command.target_document_id]
        )
        document_map = {int(item.id): item for item in documents}
        source_document = document_map.get(command.document_id)
        target_document = document_map.get(command.target_document_id)
        if source_document is None:
            existing_publish = await self.file_repository.find_by_id_for_update(publish_entry_id)
            if (
                existing_publish is not None
                and int(existing_publish.reference_document_id or 0) == command.target_document_id
                and existing_publish.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
            ):
                return
            raise KnowledgeDocumentDistributionError("merge source document no longer exists")
        if target_document is None:
            raise KnowledgeDocumentDistributionError("merge target document no longer exists")

        source_version, _target_primary, target_old_manager = await self._validate_merge_target(
            command=command,
            source_document=source_document,
            target_document=target_document,
        )
        source_entries = await self.file_repository.find_distribution_entries_by_document_id(
            command.document_id,
            for_update=True,
        )
        source_entry_map = {int(item.id): item for item in source_entries}
        manager = source_entry_map.get(command.source_entry_id)
        publish = source_entry_map.get(publish_entry_id)
        if manager is None or publish is None:
            raise KnowledgeDocumentDistributionError("merge source entries no longer exist")
        await self._validate_publish_authority(
            command,
            source_document,
            manager,
            allow_preparing_manager=True,
        )
        if publish.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
            raise KnowledgeDocumentDistributionError("merge publish entry is not preparing")

        target_versions = await self.version_repository.find_by_document_id(int(target_document.id))
        next_version_no = max(int(version.version_no) for version in target_versions) + 1
        for version in target_versions:
            version.is_primary = False
            self.session.add(version)
        source_version.document_id = int(target_document.id)
        source_version.version_no = next_version_no
        source_version.is_primary = True

        target_origin_uploader_id = (
            target_old_manager.original_uploader_id
            if target_old_manager.original_uploader_id is not None
            else target_old_manager.user_id
        )
        target_origin_knowledge_id = (
            target_old_manager.original_knowledge_id
            if target_old_manager.original_knowledge_id is not None
            else target_old_manager.knowledge_id
        )

        target_old_manager.original_uploader_id = target_origin_uploader_id
        target_old_manager.original_knowledge_id = target_origin_knowledge_id
        target_old_manager.reference_document_id = None
        target_old_manager.entry_type = None
        target_old_manager.entry_status = None
        target_old_manager.projection_status = KnowledgeFileProjectionStatus.READY.value
        target_old_manager.projection_lease_owner = None
        target_old_manager.projection_lease_until = None

        manager.knowledge_id = command.target_space_id
        manager.original_uploader_id = target_origin_uploader_id
        manager.original_knowledge_id = target_origin_knowledge_id
        manager.file_level_path = command.target_file_level_path
        manager.level = command.target_level
        manager.reference_document_id = int(target_document.id)
        manager.entry_type = KnowledgeFileEntryType.MANAGER.value
        manager.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        manager.approval_instance_id = None
        manager.projection_previous_file_id = int(target_old_manager.id)
        manager.desired_entry_generation += 1
        manager.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        manager.projection_next_retry_at = None

        for entry in source_entries:
            entry.reference_document_id = int(target_document.id)
            entry.original_uploader_id = target_origin_uploader_id
            entry.original_knowledge_id = target_origin_knowledge_id
            self.session.add(entry)
        publish.original_uploader_id = target_origin_uploader_id
        publish.original_knowledge_id = target_origin_knowledge_id
        publish.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        publish.desired_entry_generation += 1
        publish.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        publish.projection_next_retry_at = None

        target_document.primary_version_id = int(source_version.id)
        target_document.predecessor_logic_file_id = int(publish.id)
        target_document.content_generation = (
            max(
                int(source_document.content_generation),
                int(target_document.content_generation),
            )
            + 1
        )
        target_document.file_level_path = command.target_file_level_path
        target_document.level = command.target_level

        self.session.add(source_version)
        self.session.add(target_old_manager)
        self.session.add(manager)
        self.session.add(publish)
        self.session.add(target_document)
        await self.session.flush()
        await self.file_repository.mark_document_entries_content_generation(
            int(target_document.id),
            target_document.content_generation,
        )
        await self.session.delete(source_document)
        await self.session.flush()
        await self._commit()

    async def publish_approved(
        self,
        command: PublishKnowledgeDocumentCommand,
    ) -> PublishKnowledgeDocumentResult:
        source_entry = await self.file_repository.find_by_id(
            command.source_entry_id
        )
        if source_entry is None:
            raise KnowledgeDocumentDistributionError(
                "publish source no longer exists"
            )
        await self._lock_published_spaces(
            {int(source_entry.knowledge_id), int(command.target_space_id)}
        )
        existing = await self.file_repository.find_by_approval_instance_id(command.approval_instance_id)
        if existing is not None:
            result_document_id = command.target_document_id or command.document_id
            if (
                int(existing.reference_document_id or 0)
                not in {
                    command.document_id,
                    int(result_document_id),
                }
                or existing.entry_type != KnowledgeFileEntryType.PUBLISH.value
            ):
                raise KnowledgeDocumentDistributionError("approval instance is bound to a different entry")
            document = await self.document_repository.find_by_id(int(result_document_id))
            if (
                existing.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
                and document is not None
                and int(document.knowledge_id) == command.target_space_id
            ):
                return PublishKnowledgeDocumentResult(
                    document_id=int(result_document_id),
                    manager_file_id=command.source_entry_id,
                    publish_entry_id=int(existing.id),
                    target_space_id=command.target_space_id,
                    idempotent=True,
                )
            if existing.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
                raise KnowledgeDocumentDistributionError("approval entry is not retryable")
            try:
                await self._ensure_publish_target_content_not_duplicate(command)
            except KnowledgeDocumentDistributionError as exc:
                if str(exc) == PUBLISH_DUPLICATE_CONTENT_MESSAGE:
                    await self.session.rollback()
                    await self._discard_duplicate_publish_preparation(
                        command=command,
                        publish_entry_id=int(existing.id),
                    )
                raise
            publish = existing
        else:
            try:
                publish = await self._prepare_publish_entry(command)
            except Exception:
                await self.session.rollback()
                raise

        manager = await self.file_repository.find_by_id(command.source_entry_id)
        if manager is None:
            raise KnowledgeDocumentDistributionError("publish manager no longer exists")
        source_md5 = str(manager.md5 or "").strip()
        old_parent_delete = self.permission_activation_service.build_parent_operation(
            manager,
            action="delete",
        )
        target_old_manager = None
        target_old_parent_delete = None
        target_explicit_snapshot: list[TupleOperation] = []
        prewrite_cleanup_operations: list[TupleOperation] = []
        try:
            explicit_snapshot = list(await self.permission_snapshot_loader(command.source_entry_id))
            if command.target_document_id is not None:
                target_document = await self.document_repository.find_by_id(command.target_document_id)
                target_primary = (
                    await self.version_repository.find_by_id(int(target_document.primary_version_id))
                    if target_document is not None and target_document.primary_version_id is not None
                    else None
                )
                target_old_manager = (
                    await self.file_repository.find_by_id(int(target_primary.knowledge_file_id))
                    if target_primary is not None
                    else None
                )
                if target_old_manager is None:
                    raise KnowledgeDocumentDistributionError("merge target manager no longer exists")
                target_explicit_snapshot = list(await self.permission_snapshot_loader(int(target_old_manager.id)))
                target_old_parent_delete = self.permission_activation_service.build_parent_operation(
                    target_old_manager,
                    action="delete",
                )
            manager = await self._prepare_manager_permission_transition(command)
            manager_target_parent = TupleOperation(
                action="write",
                user=(
                    f"folder:{command.target_file_level_path.rstrip('/').split('/')[-1]}"
                    if command.target_file_level_path
                    else f"knowledge_space:{command.target_space_id}"
                ),
                relation="parent",
                object=f"knowledge_file:{command.source_entry_id}",
            )
            prewrite_cleanup_operations = [
                self.permission_activation_service.build_parent_operation(
                    publish,
                    action="delete",
                ),
                *self._retarget_explicit_operations(
                    explicit_snapshot,
                    target_file_id=int(publish.id),
                    action="delete",
                ),
                TupleOperation(
                    action="delete",
                    user=manager_target_parent.user,
                    relation=manager_target_parent.relation,
                    object=manager_target_parent.object,
                ),
                *self._retarget_explicit_operations(
                    target_explicit_snapshot,
                    target_file_id=command.source_entry_id,
                    action="delete",
                ),
            ]
            await self.permission_activation_service.prewrite_entry_permissions(
                entry=publish,
                explicit_operations=self._retarget_explicit_operations(
                    explicit_snapshot,
                    target_file_id=int(publish.id),
                    action="write",
                ),
                additional_operations=[
                    manager_target_parent,
                    *self._retarget_explicit_operations(
                        target_explicit_snapshot,
                        target_file_id=command.source_entry_id,
                        action="write",
                    ),
                ],
            )
        except KnowledgeDocumentPermissionActivationError as exc:
            raise KnowledgeDocumentDistributionError("publish permission prewrite failed") from exc
        except Exception as exc:
            raise KnowledgeDocumentDistributionError("publish permission snapshot or prewrite failed") from exc

        publish_entry_id = int(publish.id)
        try:
            await self._activate_publish_transfer(
                command=command,
                publish_entry_id=publish_entry_id,
                source_md5=source_md5,
            )
        except Exception as exc:
            await self.session.rollback()
            if isinstance(exc, KnowledgeDocumentDistributionError) and str(exc) == PUBLISH_DUPLICATE_CONTENT_MESSAGE:
                await self._discard_duplicate_publish_preparation(
                    command=command,
                    publish_entry_id=publish_entry_id,
                )
                try:
                    await self.permission_activation_service.tuple_writer(prewrite_cleanup_operations)
                except Exception:
                    logger.exception(
                        "F059 duplicate publish permission cleanup deferred: document_id=%s target_space_id=%s",
                        command.document_id,
                        command.target_space_id,
                    )
            raise

        cleanup_operations = [
            old_parent_delete,
            *self._retarget_explicit_operations(
                explicit_snapshot,
                target_file_id=command.source_entry_id,
                action="delete",
            ),
        ]
        if target_old_manager is not None and target_old_parent_delete is not None:
            cleanup_operations.extend(
                [
                    target_old_parent_delete,
                    *self._retarget_explicit_operations(
                        target_explicit_snapshot,
                        target_file_id=int(target_old_manager.id),
                        action="delete",
                    ),
                ]
            )
        try:
            await self.permission_activation_service.tuple_writer(cleanup_operations)
        except Exception:
            logger.exception(
                "F059 old manager permission cleanup deferred: document_id=%s",
                command.document_id,
            )

        return PublishKnowledgeDocumentResult(
            document_id=int(command.target_document_id or command.document_id),
            manager_file_id=command.source_entry_id,
            publish_entry_id=int(publish.id),
            target_space_id=command.target_space_id,
            idempotent=False,
        )

    @staticmethod
    def _create_share_entry(
        *,
        source_entry: KnowledgeFile,
        document: KnowledgeDocument,
        command: ShareKnowledgeDocumentCommand,
    ) -> KnowledgeFile:
        return KnowledgeFile(
            tenant_id=command.tenant_id,
            user_id=source_entry.user_id,
            user_name=source_entry.user_name,
            updater_id=source_entry.updater_id,
            updater_name=source_entry.updater_name,
            original_uploader_id=source_entry.original_uploader_id,
            original_knowledge_id=source_entry.original_knowledge_id,
            knowledge_id=command.target_space_id,
            file_name=source_entry.file_name,
            alias_name=source_entry.alias_name,
            file_type=FileType.FILE.value,
            file_source=source_entry.file_source,
            level=command.target_level,
            file_level_path=command.target_file_level_path,
            abstract=source_entry.abstract,
            file_size=0,
            md5=None,
            parse_type=source_entry.parse_type,
            split_rule=source_entry.split_rule,
            thumbnails=None,
            preview_file_object_name=None,
            bbox_object_name="",
            object_name=None,
            status=source_entry.status,
            user_metadata=dict(source_entry.user_metadata or {}),
            remark=source_entry.remark,
            file_encoding=source_entry.file_encoding,
            file_subcategory_code=source_entry.file_subcategory_code,
            file_subcategory_source=source_entry.file_subcategory_source,
            simhash=source_entry.simhash,
            reference_document_id=int(document.id),
            entry_type=KnowledgeFileEntryType.SHARE.value,
            entry_status=KnowledgeFileEntryStatus.PREPARING.value,
            share_source_file_id=int(source_entry.id),
            allow_download=command.allow_download,
            approval_instance_id=command.approval_instance_id,
            desired_content_generation=document.content_generation,
            applied_content_generation=0,
            desired_entry_generation=1,
            applied_entry_generation=0,
            projection_status=KnowledgeFileProjectionStatus.PENDING.value,
        )

    async def _validate_share_authority(
        self,
        *,
        command: ShareKnowledgeDocumentCommand,
        document: KnowledgeDocument,
        source_entry: KnowledgeFile,
    ) -> KnowledgeFile:
        if int(document.tenant_id or 0) != command.tenant_id or int(source_entry.tenant_id or 0) != command.tenant_id:
            raise KnowledgeDocumentDistributionError("share tenant mismatch")
        if (
            int(source_entry.reference_document_id or 0) != command.document_id
            or source_entry.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
            or source_entry.entry_type
            not in {
                KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFileEntryType.PUBLISH.value,
            }
        ):
            raise KnowledgeDocumentDistributionError("share source must be an active manager or publish entry")
        if int(source_entry.knowledge_id) == command.target_space_id:
            raise KnowledgeDocumentDistributionError("share target must differ from source space")
        existing_target = await self.file_repository.find_entry_in_space_for_update(
            command.document_id,
            command.target_space_id,
        )
        if existing_target is not None:
            raise KnowledgeDocumentDistributionError("canonical document already has an entry in target space")
        manager = await self.file_repository.find_manager_for_update(command.document_id)
        if manager is None:
            raise KnowledgeDocumentDistributionError("canonical document has no active manager")
        return manager

    async def share_approved(
        self,
        command: ShareKnowledgeDocumentCommand,
    ) -> ShareKnowledgeDocumentResult:
        source_entry = await self.file_repository.find_by_id(
            command.source_entry_id
        )
        if source_entry is None:
            raise KnowledgeDocumentDistributionError(
                "share source state no longer exists"
            )
        await self._lock_published_spaces(
            {int(source_entry.knowledge_id), int(command.target_space_id)}
        )
        existing = await self.file_repository.find_by_approval_instance_id(command.approval_instance_id)
        if existing is not None:
            if (
                int(existing.reference_document_id or 0) != command.document_id
                or existing.entry_type != KnowledgeFileEntryType.SHARE.value
                or int(existing.knowledge_id) != command.target_space_id
            ):
                raise KnowledgeDocumentDistributionError("approval instance is bound to a different entry")
            manager = await self.file_repository.find_manager_for_update(command.document_id)
            if manager is None:
                raise KnowledgeDocumentDistributionError("canonical document has no active manager")
            if existing.entry_status == KnowledgeFileEntryStatus.ACTIVE.value:
                return ShareKnowledgeDocumentResult(
                    document_id=command.document_id,
                    manager_file_id=int(manager.id),
                    share_entry_id=int(existing.id),
                    target_space_id=command.target_space_id,
                    idempotent=True,
                )
            if existing.entry_status != KnowledgeFileEntryStatus.PREPARING.value:
                raise KnowledgeDocumentDistributionError("share approval entry is not retryable")
            share = existing
        else:
            document = await self.document_repository.find_by_id_for_update(command.document_id)
            source_entry = await self.file_repository.find_by_id_for_update(command.source_entry_id)
            if document is None or source_entry is None:
                raise KnowledgeDocumentDistributionError("share source state no longer exists")
            manager = await self._validate_share_authority(
                command=command,
                document=document,
                source_entry=source_entry,
            )
            share = self._create_share_entry(
                source_entry=source_entry,
                document=document,
                command=command,
            )
            self.session.add(share)
            await self.session.flush()
            await self._commit()

        try:
            source_entry = await self.file_repository.find_by_id(
                command.source_entry_id
            )
            if source_entry is None:
                raise KnowledgeDocumentDistributionError(
                    "share source state no longer exists"
                )
            await self._lock_published_spaces(
                {int(source_entry.knowledge_id), int(command.target_space_id)}
            )
            await self.permission_activation_service.prewrite_and_activate(
                entry_id=int(share.id),
            )
            await self._commit()
        except Exception as exc:
            await self.session.rollback()
            raise KnowledgeDocumentDistributionError("share permission prewrite or activation failed") from exc

        return ShareKnowledgeDocumentResult(
            document_id=command.document_id,
            manager_file_id=int(manager.id),
            share_entry_id=int(share.id),
            target_space_id=command.target_space_id,
            idempotent=False,
        )

    async def remove_share_entry(
        self,
        *,
        tenant_id: int,
        document_id: int,
        share_entry_id: int,
        actor_entry_id: int,
    ) -> RemoveShareEntryResult:
        document = await self.document_repository.find_by_id_for_update(document_id)
        locked = await self.file_repository.find_by_ids_for_update([actor_entry_id, share_entry_id])
        file_map = {int(item.id): item for item in locked}
        actor = file_map.get(actor_entry_id)
        share = file_map.get(share_entry_id)
        if document is None or actor is None or share is None:
            raise KnowledgeDocumentDistributionError("share removal state no longer exists")
        if (
            int(document.tenant_id or 0) != tenant_id
            or int(actor.tenant_id or 0) != tenant_id
            or int(share.tenant_id or 0) != tenant_id
        ):
            raise KnowledgeDocumentDistributionError("share removal tenant mismatch")
        if (
            int(share.reference_document_id or 0) != document_id
            or share.entry_type != KnowledgeFileEntryType.SHARE.value
        ):
            raise KnowledgeDocumentDistributionError("target entry is not a share")
        actor_is_recipient = int(actor.id) == int(share.id)
        actor_is_manager = (
            int(actor.reference_document_id or 0) == document_id
            and actor.entry_type == KnowledgeFileEntryType.MANAGER.value
            and actor.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
        )
        if not actor_is_recipient and not actor_is_manager:
            raise KnowledgeDocumentDistributionError("only the recipient entry or current manager can remove a share")
        if share.entry_status == KnowledgeFileEntryStatus.DELETING.value:
            return RemoveShareEntryResult(
                document_id=document_id,
                share_entry_id=share_entry_id,
                idempotent=True,
            )
        if share.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
            raise KnowledgeDocumentDistributionError("share entry is not active")
        if not await self.file_repository.mark_entry_deleting(share_entry_id):
            raise KnowledgeDocumentDistributionError("share entry state changed concurrently")
        await self._commit()

        try:
            explicit_snapshot = list(await self.permission_snapshot_loader(share_entry_id))
            await self.permission_activation_service.revoke_deleting_entry(
                entry_id=share_entry_id,
                explicit_operations=explicit_snapshot,
            )
        except Exception:
            logger.exception(
                "F059 share permission revoke deferred: entry_id=%s",
                share_entry_id,
            )

        return RemoveShareEntryResult(
            document_id=document_id,
            share_entry_id=share_entry_id,
            idempotent=False,
        )

    async def remove_invalid_entry(
        self,
        *,
        tenant_id: int,
        document_id: int,
        entry_id: int,
    ) -> RemoveShareEntryResult:
        document = await self.document_repository.find_by_id_for_update(document_id)
        entry = await self.file_repository.find_by_id_for_update(entry_id)
        if document is None or entry is None:
            raise KnowledgeDocumentDistributionError("invalid entry no longer exists")
        if (
            int(document.tenant_id or 0) != tenant_id
            or int(entry.tenant_id or 0) != tenant_id
            or int(entry.reference_document_id or 0) != document_id
            or document.lifecycle_status
            not in {
                KnowledgeDocumentLifecycleStatus.DELETING.value,
                KnowledgeDocumentLifecycleStatus.INVALID.value,
            }
            or entry.entry_status != KnowledgeFileEntryStatus.INVALID.value
            or entry.entry_type
            not in {
                KnowledgeFileEntryType.PUBLISH.value,
                KnowledgeFileEntryType.SHARE.value,
            }
        ):
            raise KnowledgeDocumentDistributionError("entry is not an invalid distribution tombstone")
        entry.entry_status = KnowledgeFileEntryStatus.DELETING.value
        entry.desired_entry_generation = int(entry.desired_entry_generation or 0) + 1
        entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        entry.projection_next_retry_at = None
        entry.projection_lease_owner = None
        entry.projection_lease_until = None
        self.session.add(entry)
        await self._commit()
        return RemoveShareEntryResult(
            document_id=document_id,
            share_entry_id=entry_id,
            idempotent=False,
        )

    @staticmethod
    def _create_projection_tombstone(
        *,
        manager: KnowledgeFile,
        document: KnowledgeDocument,
    ) -> KnowledgeFile:
        return KnowledgeFile(
            tenant_id=int(manager.tenant_id),
            user_id=manager.user_id,
            user_name=manager.user_name,
            updater_id=manager.updater_id,
            updater_name=manager.updater_name,
            original_uploader_id=manager.original_uploader_id,
            original_knowledge_id=manager.original_knowledge_id,
            knowledge_id=int(manager.knowledge_id),
            file_name=manager.file_name,
            alias_name=manager.alias_name,
            file_type=FileType.FILE.value,
            file_source=manager.file_source,
            level=int(manager.level or 0),
            file_level_path=manager.file_level_path,
            file_size=0,
            object_name=None,
            preview_file_object_name=None,
            bbox_object_name="",
            md5=None,
            status=manager.status,
            reference_document_id=int(document.id),
            entry_type=KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
            entry_status=KnowledgeFileEntryStatus.PREPARING.value,
            projection_previous_file_id=int(manager.id),
            desired_content_generation=document.content_generation,
            applied_content_generation=document.content_generation,
            desired_entry_generation=1,
            applied_entry_generation=0,
            projection_status=KnowledgeFileProjectionStatus.PENDING.value,
        )

    async def preflight_delete_entry(
        self,
        *,
        tenant_id: int,
        document_id: int,
        entry_id: int,
    ) -> str:
        """Validate one explicit delete without changing lifecycle state."""
        document = await self.document_repository.find_by_id(document_id)
        entry = await self.file_repository.find_by_id(entry_id)
        if document is None or entry is None:
            raise KnowledgeDocumentDistributionError("delete target no longer exists")
        if (
            int(document.tenant_id or 0) != tenant_id
            or int(entry.tenant_id or 0) != tenant_id
            or int(entry.reference_document_id or 0) != document_id
            or entry.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
        ):
            raise KnowledgeDocumentDistributionError("delete target state changed")
        if entry.entry_type == KnowledgeFileEntryType.PUBLISH.value:
            raise KnowledgeDocumentDistributionError("publish entries cannot be deleted")
        if entry.entry_type == KnowledgeFileEntryType.SHARE.value:
            return "remove_share"
        if entry.entry_type != KnowledgeFileEntryType.MANAGER.value:
            raise KnowledgeDocumentDistributionError("entry type does not support explicit delete")
        return "final_delete"

    @staticmethod
    def _mark_entry_for_manager_delete(
        entry: KnowledgeFile,
        status: KnowledgeFileEntryStatus,
    ) -> None:
        entry.entry_status = status.value
        entry.desired_entry_generation = int(entry.desired_entry_generation or 0) + 1
        entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        entry.projection_next_retry_at = None
        entry.projection_lease_owner = None
        entry.projection_lease_until = None

    async def delete_manager(
        self,
        *,
        tenant_id: int,
        document_id: int,
        manager_file_id: int,
    ) -> DeleteManagerResult:
        manager_snapshot = await self.file_repository.find_by_id(manager_file_id)
        if manager_snapshot is None:
            raise KnowledgeDocumentDistributionError("manager delete state no longer exists")
        manager_space_id = int(manager_snapshot.knowledge_id)
        await self.session.execute(
            select(Knowledge)
            .where(
                Knowledge.id == manager_space_id,
                Knowledge.tenant_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        document = await self.document_repository.find_by_id_for_update(document_id)
        manager = await self.file_repository.find_by_id_for_update(manager_file_id)
        if document is None or manager is None:
            raise KnowledgeDocumentDistributionError("manager delete state no longer exists")
        if (
            int(document.tenant_id or 0) != tenant_id
            or int(manager.tenant_id or 0) != tenant_id
            or int(manager.reference_document_id or 0) != document_id
            or manager.entry_type != KnowledgeFileEntryType.MANAGER.value
            or int(manager.knowledge_id) != manager_space_id
            or int(document.knowledge_id) != manager_space_id
        ):
            raise KnowledgeDocumentDistributionError("delete target is not the canonical manager")
        if (
            document.lifecycle_status == KnowledgeDocumentLifecycleStatus.DELETING.value
            and manager.entry_status == KnowledgeFileEntryStatus.DELETING.value
        ):
            return DeleteManagerResult(
                document_id=document_id,
                manager_file_id=manager_file_id,
                action="final_delete",
                idempotent=True,
            )

        if manager.entry_status not in {
            KnowledgeFileEntryStatus.ACTIVE.value,
            KnowledgeFileEntryStatus.PREPARING.value,
            KnowledgeFileEntryStatus.DELETING.value,
        }:
            raise KnowledgeDocumentDistributionError("manager state changed concurrently")

        entries = await self.file_repository.find_distribution_entries_by_document_id(
            document_id,
            for_update=True,
        )
        document.lifecycle_status = KnowledgeDocumentLifecycleStatus.DELETING.value
        for entry in entries:
            if int(entry.id) == manager_file_id:
                self._mark_entry_for_manager_delete(
                    entry,
                    KnowledgeFileEntryStatus.DELETING,
                )
            elif (
                entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
                and entry.entry_type
                in {
                    KnowledgeFileEntryType.PUBLISH.value,
                    KnowledgeFileEntryType.SHARE.value,
                }
            ):
                self._mark_entry_for_manager_delete(
                    entry,
                    KnowledgeFileEntryStatus.INVALID,
                )
            elif entry.entry_status in {
                KnowledgeFileEntryStatus.PREPARING.value,
                KnowledgeFileEntryStatus.DELETING.value,
            }:
                self._mark_entry_for_manager_delete(
                    entry,
                    KnowledgeFileEntryStatus.DELETING,
                )
        self.session.add(document)
        self.session.add_all(entries)
        await self.session.flush()
        await self._commit()
        return DeleteManagerResult(
            document_id=document_id,
            manager_file_id=manager_file_id,
            action="final_delete",
        )

    async def _rollback_manager(
        self,
        *,
        tenant_id: int,
        document: KnowledgeDocument,
        manager: KnowledgeFile,
        predecessor_id: int,
    ) -> DeleteManagerResult:
        predecessor = await self.file_repository.find_by_id_for_update(predecessor_id)
        if (
            predecessor is None
            or int(predecessor.tenant_id or 0) != tenant_id
            or int(predecessor.reference_document_id or 0) != int(document.id)
            or predecessor.entry_type != KnowledgeFileEntryType.PUBLISH.value
            or predecessor.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
        ):
            raise KnowledgeDocumentDistributionError("publish predecessor is not restorable")
        if manager.entry_status not in {
            KnowledgeFileEntryStatus.ACTIVE.value,
            KnowledgeFileEntryStatus.PREPARING.value,
        }:
            raise KnowledgeDocumentDistributionError("rollback manager is not retryable")

        entries = await self.file_repository.find_distribution_entries_by_document_id(
            int(document.id),
            for_update=True,
        )
        tombstone = next(
            (
                entry
                for entry in entries
                if entry.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
                and entry.entry_status == KnowledgeFileEntryStatus.PREPARING.value
                and int(entry.projection_previous_file_id or 0) == int(manager.id)
                and int(entry.knowledge_id) == int(manager.knowledge_id)
            ),
            None,
        )
        if tombstone is None:
            tombstone = self._create_projection_tombstone(
                manager=manager,
                document=document,
            )
            self.session.add(tombstone)
            await self.session.flush()
        manager.entry_status = KnowledgeFileEntryStatus.PREPARING.value
        self.session.add(manager)
        await self._commit()

        try:
            predecessor_permissions = list(await self.permission_snapshot_loader(int(predecessor.id)))
            manager_target_parent = self.permission_activation_service.build_parent_operation(
                predecessor,
                action="write",
            )
            manager_target_parent = TupleOperation(
                action="write",
                user=manager_target_parent.user,
                relation=manager_target_parent.relation,
                object=f"knowledge_file:{int(manager.id)}",
            )
            await self.permission_activation_service.tuple_writer(
                [
                    manager_target_parent,
                    *self._retarget_explicit_operations(
                        predecessor_permissions,
                        target_file_id=int(manager.id),
                        action="write",
                    ),
                ]
            )
        except Exception as exc:
            raise KnowledgeDocumentDistributionError("rollback permission prewrite failed") from exc

        document = await self.document_repository.find_by_id_for_update(int(document.id))
        locked = await self.file_repository.find_by_ids_for_update([int(manager.id), predecessor_id, int(tombstone.id)])
        file_map = {int(item.id): item for item in locked}
        manager = file_map.get(int(manager.id))
        predecessor = file_map.get(predecessor_id)
        tombstone = file_map.get(int(tombstone.id))
        if (
            document is None
            or manager is None
            or predecessor is None
            or tombstone is None
            or int(document.predecessor_logic_file_id or 0) != predecessor_id
            or manager.entry_status != KnowledgeFileEntryStatus.PREPARING.value
            or predecessor.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
            or tombstone.entry_status != KnowledgeFileEntryStatus.PREPARING.value
        ):
            raise KnowledgeDocumentDistributionError("rollback state changed concurrently")

        versions = await self.version_repository.find_by_document_id(int(document.id))
        physical_file_ids = sorted({int(version.knowledge_file_id) for version in versions})
        physical_files = await self.file_repository.find_by_ids_for_update(physical_file_ids)
        if len(physical_files) != len(physical_file_ids):
            raise KnowledgeDocumentDistributionError("canonical document has missing physical versions")
        for physical_file in physical_files:
            physical_file.knowledge_id = int(predecessor.knowledge_id)
            self.session.add(physical_file)

        old_parent_delete = self.permission_activation_service.build_parent_operation(
            manager,
            action="delete",
        )
        manager.knowledge_id = int(predecessor.knowledge_id)
        manager.file_level_path = predecessor.file_level_path
        manager.level = predecessor.level
        manager.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
        manager.projection_previous_file_id = int(predecessor.id)
        manager.desired_entry_generation += 1
        manager.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        manager.projection_next_retry_at = None

        document.knowledge_id = int(predecessor.knowledge_id)
        document.file_level_path = predecessor.file_level_path
        document.level = predecessor.level
        document.predecessor_logic_file_id = predecessor.predecessor_logic_file_id

        predecessor.entry_status = KnowledgeFileEntryStatus.DELETING.value
        predecessor.desired_entry_generation += 1
        predecessor.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        predecessor.projection_next_retry_at = None
        tombstone.entry_status = KnowledgeFileEntryStatus.DELETING.value
        tombstone.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        tombstone.projection_next_retry_at = None

        self.session.add(document)
        self.session.add(manager)
        self.session.add(predecessor)
        self.session.add(tombstone)
        await self.session.flush()
        await self._commit()

        try:
            await self.permission_activation_service.tuple_writer([old_parent_delete])
        except Exception:
            logger.exception(
                "F059 rollback old manager permission cleanup deferred: document_id=%s",
                document.id,
            )

        return DeleteManagerResult(
            document_id=int(document.id),
            manager_file_id=int(manager.id),
            action="rollback",
            tombstone_entry_id=int(tombstone.id),
        )
