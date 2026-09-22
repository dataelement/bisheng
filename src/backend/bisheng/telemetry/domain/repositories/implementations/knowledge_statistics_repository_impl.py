# ruff: noqa: RUF002
"""只读取得当前文件和历史入口的文档身份。"""

from sqlalchemy import func, select

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.domain.document_identity import document_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.telemetry.domain.repositories.interfaces.knowledge_statistics_repository import (
    KnowledgeStatisticsRepository,
)


class KnowledgeStatisticsRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeStatisticsRepository):
    @staticmethod
    def aliases(identities: set[str]) -> dict[int, str]:
        """与导出脚本一致，只关联数据库仍保留的非个人历史入口。"""
        if not identities:
            return {}
        version = (
            select(KnowledgeDocumentVersion.document_id)
            .where(KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .correlate(KnowledgeFile)
            .scalar_subquery()
        )
        statement = (
            select(KnowledgeFile.id, func.coalesce(KnowledgeFile.reference_document_id, version))
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
            .where(
                Knowledge.type == 3,
                KnowledgeFile.file_type == 1,
                Knowledge.tenant_id == (get_current_tenant_id() or 1),
                KnowledgeFile.tenant_id == (get_current_tenant_id() or 1),
                KnowledgeSpaceScope.tenant_id == (get_current_tenant_id() or 1),
                KnowledgeSpaceScope.level.in_(["public", "department", "team", "team_ks"]),
            )
            .execution_options(yield_per=1000)
        )
        with get_sync_db_session() as session:
            return {
                int(file_id): key
                for file_id, doc_id in session.execute(statement)
                if (key := document_identity(file_id, doc_id)) in identities
            }

    @staticmethod
    def identities(file_ids: list[int]) -> dict[int, str]:
        if not file_ids:
            return {}
        version = (
            select(KnowledgeDocumentVersion.document_id)
            .where(KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .correlate(KnowledgeFile)
            .scalar_subquery()
        )
        result = {}
        with get_sync_db_session() as session:
            for offset in range(0, len(file_ids), 400):
                rows = session.execute(
                    select(KnowledgeFile.id, func.coalesce(KnowledgeFile.reference_document_id, version)).where(
                        KnowledgeFile.id.in_(file_ids[offset : offset + 400])
                    )
                )
                result.update({int(file_id): document_identity(file_id, doc_id) for file_id, doc_id in rows})
        return result
