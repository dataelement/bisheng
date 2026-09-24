"""从业务数据库加载全文索引所需的有界权威快照。"""

from __future__ import annotations

from sqlalchemy.orm import aliased
from sqlmodel import and_, col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.constants import (
    BUSINESS_DOMAIN_OPTIONS,
    get_business_domain_code_from_file,
    get_file_category_code_from_file,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
    KnowledgeSpaceSharedStorageRouting,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_source_repository import (
    KnowledgeFulltextSourceRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextAutoRepairSource,
    KnowledgeFulltextChunkSource,
    KnowledgeFulltextFileSnapshot,
)
from bisheng.knowledge.rag.shared_space_storage import (
    es_routing_value,
    get_shared_storage_conf,
    TenantRoutingSnapshot,
    require_initialized_shared_routing,
)
from bisheng.user.domain.models.user import User


class KnowledgeFulltextSourceRepositoryImpl(KnowledgeFulltextSourceRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute(self, statement):
        """全文基础层仅支持单租户, 权威快照读取不参与全局租户过滤。"""
        with bypass_tenant_filter():
            return await self.session.execute(statement)

    async def get_current_snapshot(self, file_id: int) -> KnowledgeFulltextFileSnapshot | None:
        statement = self._snapshot_statement().where(KnowledgeFile.id == file_id)
        row = (await self._execute(statement)).first()
        return await self._snapshot_from_row(row) if row is not None else None

    async def get_current_snapshots(self, file_ids: list[int]) -> dict[int, KnowledgeFulltextFileSnapshot | Exception]:
        rows = (await self._execute(self._snapshot_statement().where(KnowledgeFile.id.in_(file_ids)))).all()
        files = [row[0] for row in rows]
        tags = {file.id: [] for file in files}
        tag_rows = (await self._execute(select(TagLink.resource_id, Tag.name).join(Tag, Tag.id == TagLink.tag_id).where(
            TagLink.resource_id.in_([str(file.id) for file in files]),
            col(TagLink.resource_type).in_([ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value]),
        ).order_by(Tag.name, Tag.id))).all()
        for file_id, name in tag_rows:
            if name and str(file_id).isdigit() and int(file_id) in tags and name not in tags[int(file_id)]:
                tags[int(file_id)].append(name)
        users = dict((await self._execute(select(User.user_id, User.user_name).where(
            User.user_id.in_({file.original_uploader_id for file in files if file.original_uploader_id})
        ))).all())
        folder_ids = sorted({int(part) for file in files for part in str(file.file_level_path or "").split("/") if part.isdigit()})
        folders = {}
        for start in range(0, len(folder_ids), 500):
            folders.update(dict((await self._execute(select(KnowledgeFile.id, KnowledgeFile.file_name).where(
                KnowledgeFile.id.in_(folder_ids[start:start + 500]), KnowledgeFile.file_type == FileType.DIR.value,
            ))).all()))
        from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService
        types = {}
        for tenant in {int(file.tenant_id or 1) for file in files}:
            config = await ShougangPortalConfigService.get_config(tenant_id=tenant)
            types[tenant] = getattr(getattr(config, "portal", None), "document_types", None) or []
        snapshots = {}
        for row in rows:
            file = row[0]
            try:
                category = self.resolve_category_names(types[int(file.tenant_id or 1)],
                    document_category_code=get_file_category_code_from_file(file), file_subcategory_code=file.file_subcategory_code)
                path = "/".join(str(folders[int(part)]) for part in str(file.file_level_path or "").split("/")
                                if part.isdigit() and folders.get(int(part))) or None
                snapshots[file.id] = await self._snapshot_from_row(row, enrichment={
                    "tags": tags[file.id], "uploader": users.get(file.original_uploader_id), "category": category, "path": path,
                })
            except Exception as exc:
                snapshots[file.id] = exc
        return snapshots

    async def get_chunk_sources(self, snapshots: list[KnowledgeFulltextFileSnapshot]) -> dict[int, KnowledgeFulltextChunkSource | Exception | None]:
        self._batch_routings = {row.tenant_id: row for row in (await self._execute(
            select(KnowledgeSpaceSharedStorageRouting).where(KnowledgeSpaceSharedStorageRouting.tenant_id.in_({s.tenant_id for s in snapshots}))
        )).scalars()}
        self._batch_indices = dict((await self._execute(select(Knowledge.id, Knowledge.index_name).where(
            Knowledge.id.in_({s.knowledge_id for s in snapshots})
        ))).all())
        try:
            result = {}
            for snapshot in snapshots:
                try:
                    result[snapshot.file_id] = await self.get_chunk_source(snapshot)
                except Exception as exc:
                    result[snapshot.file_id] = exc
            return result
        finally:
            del self._batch_routings
            del self._batch_indices

    def _snapshot_statement(self):
        original_knowledge = aliased(Knowledge)
        version_document = aliased(KnowledgeDocument)
        statement = (
            select(
                KnowledgeFile,
                Knowledge,
                KnowledgeSpaceScope,
                KnowledgeDocument,
                KnowledgeDocumentVersion,
                version_document,
                original_knowledge.name,
            )
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .outerjoin(
                original_knowledge,
                original_knowledge.id == KnowledgeFile.original_knowledge_id,
            )
            .outerjoin(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
            .outerjoin(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeFile.reference_document_id,
            )
            .outerjoin(
                KnowledgeDocumentVersion,
                or_(
                    and_(
                        KnowledgeFile.reference_document_id.is_(None),
                        KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id,
                    ),
                    and_(
                        KnowledgeFile.reference_document_id.is_not(None),
                        KnowledgeDocumentVersion.id == KnowledgeDocument.primary_version_id,
                    ),
                ),
            )
            .outerjoin(
                version_document,
                version_document.id == KnowledgeDocumentVersion.document_id,
            )
        )
        return statement

    async def _snapshot_from_row(self, row, enrichment=None) -> KnowledgeFulltextFileSnapshot:
        (
            file,
            knowledge,
            scope,
            referenced_document,
            version,
            owning_document,
            original_knowledge_name,
        ) = row
        document = referenced_document if referenced_document is not None else owning_document
        document_category_code = get_file_category_code_from_file(file)
        business_domain_code = get_business_domain_code_from_file(file)
        if enrichment is None:
            tags = await self._load_tags(int(file.id))
            original_uploader_name = await self._load_user_name(file.original_uploader_id)
            document_category_name, file_subcategory_name = await self._load_category_names(
                tenant_id=int(file.tenant_id or 1), document_category_code=document_category_code,
                file_subcategory_code=file.file_subcategory_code,
            )
            folder_path = await self._load_folder_path(file.file_level_path)
        else:
            tags, original_uploader_name = enrichment["tags"], enrichment["uploader"]
            document_category_name, file_subcategory_name = enrichment["category"]
            folder_path = enrichment["path"]
        level = getattr(getattr(scope, "level", None), "value", getattr(scope, "level", None))
        return KnowledgeFulltextFileSnapshot(
            file_id=int(file.id),
            tenant_id=int(file.tenant_id or 1),
            knowledge_id=int(file.knowledge_id),
            file_type="FILE" if file.file_type == FileType.FILE.value else "DIR",
            status=str(file.status),
            deleted_at=file.deleted_at,
            logical_document_id=file.reference_document_id,
            document_version_id=getattr(version, "id", None),
            content_file_id=(
                int(version.knowledge_file_id)
                if version is not None
                else int(file.id)
            ),
            content_generation=(
                int(document.content_generation or 0)
                if document is not None
                else int(file.applied_content_generation or 0)
            ),
            is_primary_version=(
                file.reference_document_id is None
                if version is None
                else bool(
                    document is not None
                    and document.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value
                    and version is not None
                    and version.is_primary
                )
            ),
            file_name=file.file_name,
            alias_name=file.alias_name,
            summary=file.abstract,
            tags=tags,
            knowledge_name=knowledge.name,
            knowledge_type=knowledge.type,
            knowledge_level=level,
            knowledge_business_domain_codes=knowledge.business_domain_codes or [],
            business_domain_code=business_domain_code or None,
            business_domain_name=BUSINESS_DOMAIN_OPTIONS.get(business_domain_code),
            document_category_code=document_category_code or None,
            document_category_name=document_category_name,
            file_subcategory_code=file.file_subcategory_code,
            file_subcategory_name=file_subcategory_name,
            file_source=file.file_source or "unknown",
            folder_path=folder_path,
            source_path="/".join(part for part in (knowledge.name, folder_path, file.file_name) if part),
            uploader_id=file.user_id,
            uploader_name=file.user_name,
            original_uploader_id=file.original_uploader_id,
            original_uploader_name=original_uploader_name,
            original_knowledge_id=file.original_knowledge_id,
            original_knowledge_name=original_knowledge_name,
            updater_id=file.updater_id,
            updater_name=file.updater_name,
            created_at=file.create_time,
            updated_at=file.update_time,
            entry_type=file.entry_type,
            entry_status=file.entry_status,
            projection_status=file.projection_status,
            allow_download=file.allow_download,
            user_metadata=file.user_metadata or {},
        )

    async def get_chunk_source(
        self, snapshot: KnowledgeFulltextFileSnapshot
    ) -> KnowledgeFulltextChunkSource | None:
        conf = get_shared_storage_conf()
        if (
            snapshot.knowledge_type is not None
            and int(snapshot.knowledge_type) == KnowledgeTypeEnum.SPACE.value
        ):
            if hasattr(self, "_batch_routings"):
                routing = self._batch_routings.get(int(snapshot.tenant_id))
            else:
                result = await self._execute(
                    select(KnowledgeSpaceSharedStorageRouting).where(
                        KnowledgeSpaceSharedStorageRouting.tenant_id
                        == int(snapshot.tenant_id)
                    )
                )
                routing = result.scalars().first()
            require_initialized_shared_routing(
                int(snapshot.tenant_id),
                TenantRoutingSnapshot.from_row(routing) if routing is not None else None,
            )
            if (
                not routing.index_name
                or snapshot.logical_document_id is None
                or snapshot.document_version_id is None
            ):
                return None
            return KnowledgeFulltextChunkSource(
                index_name=str(routing.index_name),
                file_id=int(snapshot.file_id),
                knowledge_id=int(snapshot.knowledge_id),
                tenant_id=int(snapshot.tenant_id),
                canonical_document_id=int(snapshot.logical_document_id),
                canonical_version_id=int(snapshot.document_version_id),
                content_generation=int(snapshot.content_generation),
                routing=(
                    es_routing_value(
                        int(snapshot.tenant_id),
                        int(snapshot.logical_document_id),
                    )
                    if conf.es_routing_enabled
                    else None
                ),
            )

        index_name = self._batch_indices.get(snapshot.knowledge_id) if hasattr(self, "_batch_indices") else await self.get_knowledge_index_name(snapshot.knowledge_id)
        if not index_name:
            return None
        return KnowledgeFulltextChunkSource(
            index_name=index_name,
            file_id=int(snapshot.file_id),
            knowledge_id=int(snapshot.knowledge_id),
        )

    async def get_auto_repair_source(self, file_id: int) -> KnowledgeFulltextAutoRepairSource | None:
        result = await self._execute(
            select(
                KnowledgeFile.id,
                KnowledgeFile.knowledge_id,
                KnowledgeFile.md5,
                KnowledgeFile.object_name,
                KnowledgeFile.split_rule,
                KnowledgeFile.desired_content_generation,
            ).where(KnowledgeFile.id == file_id)
        )
        row = result.first()
        if row is None:
            return None
        return KnowledgeFulltextAutoRepairSource(
            file_id=int(row[0]),
            knowledge_id=int(row[1]),
            md5=row[2],
            object_name=row[3],
            split_rule=row[4],
            desired_content_generation=int(row[5] or 0),
        )

    async def list_file_ids(
        self,
        *,
        knowledge_id: int,
        after_file_id: int | None,
        limit: int,
    ) -> list[int]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        statement = (
            select(KnowledgeFile.id)
            .where(KnowledgeFile.knowledge_id == knowledge_id)
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
        )
        if after_file_id is not None:
            statement = statement.where(KnowledgeFile.id > after_file_id)
        result = await self._execute(statement)
        return [int(value) for value in result.scalars().all()]

    async def list_backfill_file_ids(
        self,
        *,
        after_file_id: int,
        limit: int,
        knowledge_id: int | None = None,
        file_id: int | None = None,
    ) -> list[int]:
        """按全局稳定 ID 顺序读取回填扫描页, 不在查询层复制 eligibility。"""
        if after_file_id < 0:
            raise ValueError("after_file_id must be greater than or equal to 0")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if knowledge_id is not None and knowledge_id <= 0:
            raise ValueError("knowledge_id must be greater than 0")
        if file_id is not None and file_id <= 0:
            raise ValueError("file_id must be greater than 0")

        statement = (
            select(KnowledgeFile.id)
            .where(KnowledgeFile.id > after_file_id)
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
        )
        if knowledge_id is not None:
            statement = statement.where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_id is not None:
            statement = statement.where(KnowledgeFile.id == file_id)
        result = await self._execute(statement)
        return [int(value) for value in result.scalars().all()]

    async def get_knowledge_index_name(self, knowledge_id: int) -> str | None:
        result = await self._execute(select(Knowledge.index_name).where(Knowledge.id == knowledge_id))
        return result.scalar_one_or_none()

    async def _load_tags(self, file_id: int) -> list[str]:
        statement = (
            select(Tag.name)
            .join(TagLink, TagLink.tag_id == Tag.id)
            .where(
                TagLink.resource_id == str(file_id),
                col(TagLink.resource_type).in_(
                    [ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value]
                ),
                Tag.name.is_not(None),
            )
            .order_by(Tag.name.asc(), Tag.id.asc())
        )
        result = await self._execute(statement)
        return list(dict.fromkeys(str(value) for value in result.scalars().all() if value))

    async def _load_user_name(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        result = await self._execute(select(User.user_name).where(User.user_id == user_id))
        return result.scalar_one_or_none()

    async def _load_folder_path(self, raw_path: str | None) -> str | None:
        folder_ids = [int(part) for part in str(raw_path or "").split("/") if part.isdigit()]
        if not folder_ids:
            return None
        result = await self._execute(
            select(KnowledgeFile.id, KnowledgeFile.file_name).where(
                col(KnowledgeFile.id).in_(folder_ids),
                KnowledgeFile.file_type == FileType.DIR.value,
            )
        )
        names = {int(folder_id): str(name) for folder_id, name in result.all() if name}
        path = "/".join(names[folder_id] for folder_id in folder_ids if folder_id in names)
        return path or None

    @classmethod
    async def _load_category_names(
        cls,
        *,
        tenant_id: int,
        document_category_code: str | None,
        file_subcategory_code: str | None,
    ) -> tuple[str | None, str | None]:
        if not document_category_code and not file_subcategory_code:
            return None, None
        try:
            from bisheng.shougang_portal_config.domain.services.portal_config_service import (
                ShougangPortalConfigService,
            )

            config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
            document_types = getattr(getattr(config, "portal", None), "document_types", None) or []
        except Exception:
            return None, None
        return cls.resolve_category_names(
            document_types,
            document_category_code=document_category_code,
            file_subcategory_code=file_subcategory_code,
        )

    @staticmethod
    def resolve_category_names(
        document_types,
        *,
        document_category_code: str | None,
        file_subcategory_code: str | None,
    ) -> tuple[str | None, str | None]:
        parent_code = str(document_category_code or "").strip().upper()
        child_code = str(file_subcategory_code or "").strip().upper()
        for item in document_types or []:
            item_code = str(getattr(item, "code", "") or "").strip().upper()
            if not item_code or item_code != parent_code:
                continue
            parent_name = str(getattr(item, "label", "") or "").strip() or None
            for child in getattr(item, "children", None) or []:
                if str(getattr(child, "code", "") or "").strip().upper() == child_code:
                    child_name = str(getattr(child, "label", "") or "").strip() or None
                    return parent_name, child_name
            return parent_name, parent_name if child_code == parent_code else None
        return None, None
