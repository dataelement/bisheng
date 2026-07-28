"""发布到目标知识库时的当前可见内容 MD5 判重测试。"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


@pytest.mark.asyncio
async def test_duplicate_query_resolves_physical_and_logical_current_content(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=20,
                file_name="本地文件.pdf",
                md5="physical-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=30,
                primary_version_id=501,
            ),
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=30,
                file_name="共享内容.pdf",
                md5="logical-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=101,
                version_no=1,
                is_primary=True,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=7,
                knowledge_id=20,
                file_name="共享内容.pdf",
                md5=None,
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            ),
        ]
    )
    await async_db_session.commit()
    repository = KnowledgeFileRepositoryImpl(async_db_session)

    assert await repository.has_visible_content_in_space(
        tenant_id=7,
        knowledge_id=20,
        md5="physical-md5",
    )
    assert await repository.has_visible_content_in_space(
        tenant_id=7,
        knowledge_id=20,
        md5="logical-md5",
    )
    assert not await repository.has_visible_content_in_space(
        tenant_id=8,
        knowledge_id=20,
        md5="physical-md5",
    )


@pytest.mark.asyncio
async def test_duplicate_query_ignores_history_and_inactive_logical_entries(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=501,
            ),
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=20,
                file_name="历史版本.pdf",
                md5="duplicate-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=20,
                file_name="当前版本.pdf",
                md5="current-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            ),
            KnowledgeDocumentVersion(
                id=500,
                document_id=91,
                knowledge_file_id=100,
                version_no=1,
                is_primary=False,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=101,
                version_no=2,
                is_primary=True,
            ),
            KnowledgeDocument(
                id=92,
                tenant_id=7,
                knowledge_id=30,
                primary_version_id=601,
            ),
            KnowledgeFile(
                id=200,
                tenant_id=7,
                knowledge_id=30,
                file_name="准备中的共享内容.pdf",
                md5="duplicate-md5",
                status=KnowledgeFileStatus.SUCCESS.value,
            ),
            KnowledgeDocumentVersion(
                id=601,
                document_id=92,
                knowledge_file_id=200,
                version_no=1,
                is_primary=True,
            ),
            KnowledgeFile(
                id=201,
                tenant_id=7,
                knowledge_id=20,
                file_name="准备中的共享内容.pdf",
                md5=None,
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=92,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.PREPARING.value,
            ),
        ]
    )
    await async_db_session.commit()

    assert not await KnowledgeFileRepositoryImpl(
        async_db_session
    ).has_visible_content_in_space(
        tenant_id=7,
        knowledge_id=20,
        md5="duplicate-md5",
    )
