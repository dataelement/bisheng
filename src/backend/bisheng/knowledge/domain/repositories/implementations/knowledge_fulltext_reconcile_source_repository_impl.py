"""批量预取全文快照关联数据, 复用单文件快照组装契约。"""

from collections import defaultdict

from loguru import logger
from sqlmodel import col, func, select

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileReadError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import KnowledgeSpaceSharedStorageRouting
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource
from bisheng.knowledge.rag.shared_space_storage import (
    TenantRoutingSnapshot,
    es_routing_value,
    get_shared_storage_conf,
    require_initialized_shared_routing,
)
from bisheng.user.domain.models.user import User


class KnowledgeFulltextReconcileSourceRepository(KnowledgeFulltextSourceRepositoryImpl):
    async def upper_bound(self) -> int:
        return int((await self._execute(select(func.max(KnowledgeFile.id)))).scalar() or 0)

    async def page_ids(self, after: int, upper: int, limit: int = 200) -> list[int]:
        return list(
            (
                await self._execute(
                    select(KnowledgeFile.id)
                    .where(
                        KnowledgeFile.id > after,
                        KnowledgeFile.id <= upper,
                    )
                    .order_by(KnowledgeFile.id)
                    .limit(limit)
                )
            ).scalars()
        )

    async def snapshots(self, ids: list[int]) -> dict:
        if not ids:
            return {}
        rows = (
            await self._execute(
                self._snapshot_statement()
                .where(col(KnowledgeFile.id).in_(ids))
                .execution_options(populate_existing=True)
            )
        ).all()
        existing = set((await self._execute(select(KnowledgeFile.id).where(col(KnowledgeFile.id).in_(ids)))).scalars())
        files = [row[0] for row in rows]
        self.tags = defaultdict(list)
        tag_rows = (
            await self._execute(
                select(TagLink.resource_id, Tag.name)
                .join(Tag, Tag.id == TagLink.tag_id)
                .where(
                    col(TagLink.resource_id).in_([str(i) for i in ids]),
                    col(TagLink.resource_type).in_(
                        [ResourceTypeEnum.SPACE_FILE.value, ResourceTypeEnum.KNOWLEDGE_FILE.value]
                    ),
                    Tag.name.is_not(None),
                )
                .order_by(Tag.name, Tag.id)
            )
        ).all()
        for file_id, name in tag_rows:
            self.tags[int(file_id)].append(str(name))
        user_ids = {f.original_uploader_id for f in files if f.original_uploader_id is not None}
        self.names = (
            dict(
                (await self._execute(select(User.user_id, User.user_name).where(col(User.user_id).in_(user_ids)))).all()
            )
            if user_ids
            else {}
        )
        folder_ids = {int(i) for f in files for i in str(f.file_level_path or "").split("/") if i.isdigit()}
        self.folders = (
            dict(
                (
                    await self._execute(
                        select(KnowledgeFile.id, KnowledgeFile.file_name).where(
                            col(KnowledgeFile.id).in_(folder_ids),
                            KnowledgeFile.file_type == FileType.DIR.value,
                        )
                    )
                ).all()
            )
            if folder_ids
            else {}
        )
        self.categories = {}
        from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService

        for tenant_id in {int(f.tenant_id or 1) for f in files}:
            # 配置读取失败不能清空索引中的现有分类名称。
            config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
            self.categories[tenant_id] = getattr(getattr(config, "portal", None), "document_types", None) or []
        result = {i: ReconcileReadError("file exists but source relation is incomplete") for i in existing}
        seen = set()
        for row in rows:
            file_id = int(row[0].id)
            if file_id in seen:
                result[file_id] = ReconcileReadError("ambiguous file source relations")
                continue
            seen.add(file_id)
            try:
                if row[0].reference_document_id is not None and (row[3] is None or row[4] is None):
                    raise ReconcileReadError("logical document or primary version relation is incomplete")
                result[file_id] = await self._snapshot_from_row(row)
            except Exception as exc:
                logger.exception("fulltext reconcile source snapshot failed file_id={}", file_id)
                result[file_id] = exc
        return result

    async def _load_tags(self, file_id: int) -> list[str]:
        return list(dict.fromkeys(self.tags[file_id]))

    async def _load_user_name(self, user_id: int | None) -> str | None:
        return self.names.get(user_id)

    async def _load_folder_path(self, raw_path: str | None) -> str | None:
        return (
            "/".join(
                str(self.folders[int(i)])
                for i in str(raw_path or "").split("/")
                if i.isdigit() and int(i) in self.folders
            )
            or None
        )

    async def _load_category_names(
        self, *, tenant_id: int, document_category_code: str | None, file_subcategory_code: str | None
    ) -> tuple[str | None, str | None]:
        return self.resolve_category_names(
            self.categories[tenant_id],
            document_category_code=document_category_code,
            file_subcategory_code=file_subcategory_code,
        )

    async def chunk_sources(self, snapshots: list) -> dict:
        knowledge_ids = {s.knowledge_id for s in snapshots}
        indexes = dict(
            (
                await self._execute(
                    select(Knowledge.id, Knowledge.index_name).where(col(Knowledge.id).in_(knowledge_ids))
                )
            ).all()
        )
        tenant_ids = {s.tenant_id for s in snapshots}
        routes = {
            r.tenant_id: r
            for r in (
                await self._execute(
                    select(KnowledgeSpaceSharedStorageRouting).where(
                        col(KnowledgeSpaceSharedStorageRouting.tenant_id).in_(tenant_ids)
                    )
                )
            ).scalars()
        }
        conf = get_shared_storage_conf()
        result = {}
        for snapshot in snapshots:
            try:
                common = {"file_id": snapshot.file_id, "knowledge_id": snapshot.knowledge_id}
                if snapshot.knowledge_type == KnowledgeTypeEnum.SPACE.value:
                    row = routes.get(snapshot.tenant_id)
                    route = require_initialized_shared_routing(
                        snapshot.tenant_id, TenantRoutingSnapshot.from_row(row) if row else None
                    )
                    if snapshot.logical_document_id is None or snapshot.document_version_id is None:
                        raise ReconcileReadError("canonical content is not ready")
                    result[snapshot.file_id] = KnowledgeFulltextChunkSource(
                        **common,
                        index_name=route.index_name,
                        tenant_id=snapshot.tenant_id,
                        canonical_document_id=snapshot.logical_document_id,
                        canonical_version_id=snapshot.document_version_id,
                        content_generation=snapshot.content_generation,
                        routing=es_routing_value(snapshot.tenant_id, snapshot.logical_document_id)
                        if conf.es_routing_enabled
                        else None,
                    )
                else:
                    if not indexes.get(snapshot.knowledge_id):
                        raise ReconcileReadError("RAG index is not configured")
                    result[snapshot.file_id] = KnowledgeFulltextChunkSource(
                        **common, index_name=indexes[snapshot.knowledge_id]
                    )
            except Exception as exc:
                logger.exception("fulltext reconcile chunk routing failed file_id={}", snapshot.file_id)
                result[snapshot.file_id] = exc
        return result
