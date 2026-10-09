from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.database.models.department import Department
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.interfaces.portal_manual_recommendation_repository import (
    ManualFileRecord,
    PortalManualRecommendationRepository,
)


class PortalManualRecommendationRepositoryImpl(
    BaseRepositoryImpl[KnowledgeFile, int], PortalManualRecommendationRepository
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)

    async def list_spaces(self) -> list[dict]:
        statement = (
            select(Knowledge, KnowledgeSpaceScope)
            .join(
                KnowledgeSpaceScope,
                and_(
                    KnowledgeSpaceScope.space_id == Knowledge.id, KnowledgeSpaceScope.tenant_id == Knowledge.tenant_id
                ),
            )
            .where(Knowledge.type == KnowledgeTypeEnum.SPACE.value, Knowledge.state != KnowledgeState.DELETING.value)
            .order_by(Knowledge.id)
        )
        binding_statement = select(DepartmentKnowledgeSpace, Department).join(
            Department,
            and_(
                Department.id == DepartmentKnowledgeSpace.department_id,
                Department.tenant_id == DepartmentKnowledgeSpace.tenant_id,
            ),
        )
        with strict_tenant_filter():
            rows = (await self.session.execute(statement)).all()
            binding_rows = (await self.session.execute(binding_statement)).all()
        bindings = {binding.space_id: (binding, department) for binding, department in binding_rows}
        result = []
        for space, scope in rows:
            binding, department = bindings.get(space.id, (None, None))
            # 多租户根账号不能把其他租户的推广配置纳入本租户。
            tenant_id = get_current_tenant_id() or 1
            if int(space.tenant_id or 1) != tenant_id:
                continue
            level = str(getattr(scope.level, "value", scope.level))
            owner = str(getattr(scope.owner_type, "value", scope.owner_type))
            valid_binding = bool(binding and department and department.status == "active" and not department.is_deleted)
            supported = (
                level == "department"
                and owner == "department"
                and valid_binding
                and int(scope.owner_id) == int(binding.department_id)
            ) or (level in {"team", "team_ks"} and owner == "user" and valid_binding)
            if level != "public" and not (scope.portal_discovery_enabled and supported):
                continue
            result.append(
                {
                    "id": int(space.id),
                    "name": space.name,
                    "space_level": level,
                    "portal_discovery_enabled": bool(scope.portal_discovery_enabled),
                }
            )
        return result

    @staticmethod
    def _document_id():
        return func.coalesce(KnowledgeFile.reference_document_id, KnowledgeDocumentVersion.document_id)

    def _files_statement(self, space_ids):
        document_id = self._document_id()
        # 租户监听器对选中 ORM 模型追加 WHERE;使用受文件租户约束的表别名,保留无版本旧文件。
        document = KnowledgeDocument.__table__.alias("manual_document")
        statement = (
            select(KnowledgeFile, document_id, document.c.primary_version_id)
            .outerjoin(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .outerjoin(document, and_(document.c.id == document_id, document.c.tenant_id == KnowledgeFile.tenant_id))
            .where(
                col(KnowledgeFile.knowledge_id).in_(space_ids),
                KnowledgeFile.file_type == 1,
                KnowledgeFile.status == 2,
                col(KnowledgeFile.deleted_at).is_(None),
                or_(col(KnowledgeFile.entry_status).is_(None), KnowledgeFile.entry_status == "active"),
                or_(col(KnowledgeDocumentVersion.id).is_(None), col(KnowledgeDocumentVersion.is_primary).is_(True)),
                or_(document_id.is_(None), document.c.lifecycle_status == "active"),
            )
        )
        # 聚合外层无法由租户监听器识别子查询中的模型,使用统一辅助函数约束内层。
        with strict_tenant_filter():
            tenant_clause = build_tenant_filter_clause(KnowledgeFile.tenant_id)
        return statement.where(tenant_clause) if tenant_clause is not None else statement

    async def _records(self, statement, spaces):
        with strict_tenant_filter():
            rows = (await self.session.execute(statement)).all()
        metadata = {item["id"]: item for item in spaces}
        tenant_id = get_current_tenant_id() or 1
        return [
            ManualFileRecord(
                file,
                metadata[file.knowledge_id]["name"],
                metadata[file.knowledge_id]["space_level"],
                int(document_id) if document_id else None,
                int(version_id) if version_id else None,
            )
            for file, document_id, version_id in rows
            if file.knowledge_id in metadata and int(file.tenant_id or 1) == tenant_id
        ]

    async def list_files(self, space_id: int, q: str, page: int, page_size: int) -> tuple[list[ManualFileRecord], int]:
        spaces = [space for space in await self.list_spaces() if space["id"] == space_id]
        if not spaces:
            return [], 0
        statement = self._files_statement([space_id])
        if q:
            statement = statement.where(col(KnowledgeFile.file_name).contains(q, autoescape=True))
        with strict_tenant_filter():
            total = (await self.session.execute(select(func.count()).select_from(statement.subquery()))).scalar_one()
        rows = await self._records(
            statement.order_by(KnowledgeFile.id.desc()).offset((page - 1) * page_size).limit(page_size), spaces
        )
        return rows, int(total)

    async def find_references(self, references: list[dict]) -> list[ManualFileRecord]:
        if not references:
            return []
        requested = {ref["space_id"] for ref in references}
        spaces = [space for space in await self.list_spaces() if space["id"] in requested]
        if not spaces:
            return []
        file_ids = [ref["file_id"] for ref in references]
        document_ids = [ref["canonical_document_id"] for ref in references if ref.get("canonical_document_id")]
        condition = col(KnowledgeFile.id).in_(file_ids)
        if document_ids:
            condition = or_(condition, self._document_id().in_(document_ids))
        return await self._records(
            self._files_statement([space["id"] for space in spaces]).where(condition).order_by(KnowledgeFile.id.desc()),
            spaces,
        )
