from datetime import datetime

import pytest
from sqlalchemy import DefaultClause, MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_mcp_repository_impl import (
    KnowledgeMcpRepositoryImpl,
)


@pytest.fixture
async def repository():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    token = current_tenant_id.set(1)
    try:
        metadata = MetaData()
        for model in (Knowledge, KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                    column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with AsyncSession(engine) as session:
            yield KnowledgeMcpRepositoryImpl(session)
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def test_repository_filters_inventory_and_uses_stable_keys(repository):
    """AC-05: actual ORM excludes old versions, invalid entries and recycled rows."""
    session = repository.session
    session.add(Knowledge(id=1, name="space", type=3, tenant_id=1))
    for file_id in range(1, 7):
        session.add(
            KnowledgeFile(
                id=file_id,
                knowledge_id=1,
                tenant_id=1,
                file_type=1,
                file_name=f"{file_id}.txt",
                status=2,
                update_time=datetime(2026, 1, 1),
            )
        )
    await session.commit()
    row = await session.get(KnowledgeFile, 4)
    row.reference_document_id, row.entry_status, row.entry_type = 10, "invalid", "publish"
    (await session.get(KnowledgeFile, 5)).deleted_at = datetime(2026, 1, 2)
    session.add(KnowledgeDocument(id=10, tenant_id=1, knowledge_id=1, primary_version_id=21))
    session.add(
        KnowledgeDocumentVersion(
            id=20, tenant_id=1, document_id=10, knowledge_file_id=1, version_no=1, is_primary=False
        )
    )
    session.add(
        KnowledgeDocumentVersion(id=21, tenant_id=1, document_id=10, knowledge_file_id=6, version_no=2, is_primary=True)
    )
    await session.commit()
    first = await repository.scan_files([1], file_type=1, parent_path="", limit=2)
    assert [r.id for r in first] == [6, 3]
    next_page = await repository.scan_files(
        [1], file_type=1, parent_path="", limit=2, after=[first[-1].update_time.isoformat(), first[-1].id]
    )
    assert [r.id for r in next_page] == [2]
    assert await repository.scan_files([2], file_type=1, parent_path="") == []


@pytest.mark.parametrize("recursive,expected", [(True, [1, 2]), (False, [1])])
async def test_folder_scope_matches_path_segments_and_direct_layer(repository, recursive, expected):
    """F083 覆盖 AC: AC-02;相似目录/兄弟/其他空间/未成功文件不进入范围。"""
    for file_id, space_id, path, status in [
        (1, 1, "/305", 2),
        (2, 1, "/305/400", 2),
        (3, 1, "/3050", 2),
        (4, 1, "/306", 2),
        (5, 2, "/305", 2),
        (6, 1, "/305", 5),
    ]:
        repository.session.add(
            KnowledgeFile(
                id=file_id,
                knowledge_id=space_id,
                tenant_id=1,
                file_type=1,
                file_name=f"{file_id}.txt",
                file_level_path=path,
                status=status,
            )
        )
    await repository.session.commit()
    rows = await repository.scan_files(
        [1],
        file_type=1,
        parent_path="/305",
        recursive=recursive,
        statuses=[2],
        sort_by="file_name",
        order="asc",
    )
    assert [row.id for row in rows] == expected
