from sqlalchemy import DefaultClause, MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.department import Department
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.implementations.portal_manual_recommendation_repository_impl import (
    PortalManualRecommendationRepositoryImpl,
)


async def test_candidate_union_paging_and_live_file_scope():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    token = current_tenant_id.set(1)
    try:
        async with engine.begin() as connection:
            metadata = MetaData()
            for model in [
                Department,
                Knowledge,
                KnowledgeSpaceScope,
                DepartmentKnowledgeSpace,
                KnowledgeFile,
                KnowledgeDocument,
                KnowledgeDocumentVersion,
            ]:
                table = model.__table__.to_metadata(metadata)
                for column in table.columns:
                    if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                        column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
            await connection.run_sync(metadata.create_all)
        async with AsyncSession(engine) as session:
            session.add(Department(id=2, dept_id="TEST@2", tenant_id=1, name="有效部门", status="active", is_deleted=0))
            for space_id, level, enabled, tenant in [
                (1, "public", False, 1),
                (2, "department", True, 1),
                (3, "department", False, 1),
                (4, "team", True, 1),
                (5, "personal", True, 1),
                (6, "public", True, 2),
            ]:
                session.add(Knowledge(id=space_id, tenant_id=tenant, name=str(space_id), type=3, state=1))
                session.add(
                    KnowledgeSpaceScope(
                        space_id=space_id,
                        tenant_id=tenant,
                        level=level,
                        owner_type="department" if level == "department" else "user",
                        owner_id=2,
                        portal_discovery_enabled=enabled,
                        created_by=1,
                    )
                )
            for space_id in [2, 3]:
                session.add(DepartmentKnowledgeSpace(space_id=space_id, department_id=2, tenant_id=1, created_by=1))
            for file_id in range(1, 107):
                session.add(
                    KnowledgeFile(id=file_id, knowledge_id=1, tenant_id=1, file_name=f"文件{file_id}.pdf", status=2)
                )
            session.add(KnowledgeFile(id=107, knowledge_id=1, tenant_id=1, file_name="未成功.pdf", status=3))
            await session.commit()
            repo = PortalManualRecommendationRepositoryImpl(session)
            assert [row["id"] for row in await repo.list_spaces()] == [1, 2]
            rows, total = await repo.list_files(1, "", 2, 100)
            assert total == 106 and len(rows) == 6
            assert await repo.list_files(3, "", 1, 10) == ([], 0)
            assert await repo.find_references([{"space_id": 6, "file_id": 1}]) == []
            assert await repo.find_references([{"space_id": 1, "file_id": 107}]) == []
            session.add(KnowledgeDocument(id=700, tenant_id=1, knowledge_id=1, primary_version_id=702))
            session.add(KnowledgeFile(id=108, knowledge_id=1, tenant_id=1, file_name="旧版本.pdf", status=2))
            session.add(KnowledgeFile(id=109, knowledge_id=1, tenant_id=1, file_name="当前版本.pdf", status=2))
            session.add(
                KnowledgeDocumentVersion(id=701, document_id=700, knowledge_file_id=108, version_no=1, is_primary=False)
            )
            session.add(
                KnowledgeDocumentVersion(id=702, document_id=700, knowledge_file_id=109, version_no=2, is_primary=True)
            )
            await session.commit()
            from bisheng.knowledge.domain.services.portal_manual_recommendation_service import (
                PortalManualRecommendationService,
            )

            resolved = await PortalManualRecommendationService(repo).resolve_items(
                [
                    {"space_id": 1, "file_id": 108, "canonical_document_id": 700},
                ]
            )
            assert resolved[0]["id"] == 109 and resolved[0]["canonical_document_id"] == 700
            department = await session.get(Department, 2)
            department.status = "archived"
            await session.commit()
            assert [row["id"] for row in await repo.list_spaces()] == [1]

    finally:
        current_tenant_id.reset(token)
        await engine.dispose()
