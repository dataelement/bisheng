"""批量预取全文快照关联数据, 复用单文件快照组装契约。"""

from collections import defaultdict

from loguru import logger
from sqlmodel import col, func, select

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileReadError, ReconcileSourceRelationError
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_identity import (
    group_source_rows,
    unique_source_row,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
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
        grouped = group_source_rows(rows)
        files = [group[0][0] for group in grouped.values()]
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
        for file_id, group in grouped.items():
            try:
                row = unique_source_row(group)
                result[file_id] = await self._snapshot_from_row(row)
            except ReconcileSourceRelationError as exc:
                # 预期数据问题由持久化状态统一告警；重复扫描不打印整段堆栈。
                result[file_id] = exc
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
        # 与普通全文消费复用同一正文定位规则，保留父类的批量路由查询。
        sources = await self.get_chunk_sources(snapshots)
        return {
            file_id: value if value is not None else ReconcileReadError("RAG source is not configured")
            for file_id, value in sources.items()
        }
