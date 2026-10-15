# ruff: noqa: RUF002
"""只读取得当前文件和历史入口的文档身份。"""

from sqlalchemy import func, select

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.domain.constants import (
    get_file_category_code_from_file,
    get_file_category_code_from_split_rule,
    parse_shougang_file_encoding_codes,
)
from bisheng.knowledge.domain.document_identity import document_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.telemetry.domain.repositories.interfaces.knowledge_statistics_repository import (
    KnowledgeStatisticsRepository,
)


class KnowledgeStatisticsRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeStatisticsRepository):
    @staticmethod
    def space_names(space_ids: list[int]) -> dict[int, tuple[int, str]]:
        result = {}
        ids = sorted(set(space_ids))
        if not ids:
            return result
        with get_sync_db_session() as session:
            for offset in range(0, len(ids), 400):
                rows = session.execute(
                    select(Knowledge.id, Knowledge.tenant_id, Knowledge.name).where(
                        Knowledge.id.in_(ids[offset : offset + 400]),
                        Knowledge.type == 3,
                    )
                )
                result.update({int(space_id): (int(tenant_id or 1), name) for space_id, tenant_id, name in rows})
        return result

    @staticmethod
    def category_audit_sources(file_ids: list[int], document_ids: list[int]) -> dict:
        tenant_id = get_current_tenant_id()
        if not tenant_id or tenant_id <= 0:
            raise ValueError("分类审计必须指定租户上下文")
        if len(file_ids) > 400 or len(document_ids) > 400:
            raise ValueError("分类审计每批最多 400 个文件或文档")
        if any(type(value) is not int or value <= 0 for value in [*file_ids, *document_ids]):
            raise ValueError("分类审计 ID 必须是正整数")
        if not file_ids and not document_ids:
            return {"files": {}, "documents": {}, "entries": {}}
        with get_sync_db_session() as session:
            files = list(session.execute(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).scalars())
            files = [row for row in files if int(row.tenant_id or 0) == tenant_id]
            versions = list(
                session.execute(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.knowledge_file_id.in_([row.id for row in files]),
                    )
                ).scalars()
            )
            version_docs = {}
            for row in versions:
                version_docs.setdefault(int(row.knowledge_file_id), set()).add(int(row.document_id))
            identities = {}
            for row in files:
                candidates = version_docs.get(int(row.id), set())
                identities[int(row.id)] = row.reference_document_id or (
                    next(iter(candidates)) if len(candidates) == 1 else None
                )
            wanted = sorted(set(document_ids) | {int(value) for value in identities.values() if value})
            if len(wanted) > 800:
                raise ValueError("分类审计关联文档超过批次预算")
            documents = list(
                session.execute(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(wanted))).scalars()
            )
            documents = [row for row in documents if int(row.tenant_id or 0) == tenant_id]
            primary_ids = [row.primary_version_id for row in documents if row.primary_version_id]
            primary_versions = list(
                session.execute(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.id.in_(primary_ids),
                    )
                ).scalars()
            )
            primary_by_id = {int(row.id): row for row in primary_versions}
            primary_files = {}
            for document in documents:
                version = primary_by_id.get(int(document.primary_version_id or 0))
                if version is not None and int(version.document_id) == int(document.id):
                    primary_files[int(document.id)] = int(version.knowledge_file_id)
            entries = list(
                session.execute(
                    select(KnowledgeFile)
                    .where(
                        KnowledgeFile.reference_document_id.in_(wanted),
                        KnowledgeFile.entry_type.in_(["manager", "publish", "share"]),
                    )
                    .limit(10001)
                ).scalars()
            )
            if len(entries) > 10000:
                raise ValueError("分类审计关联入口超过批次预算")

            def snapshot(row: KnowledgeFile, document_id: int | None) -> dict:
                explicit = get_file_category_code_from_split_rule(row.split_rule)
                encoded = parse_shougang_file_encoding_codes(row)[0]
                return {
                    "file_id": int(row.id),
                    "space_id": int(row.knowledge_id),
                    "tenant_id": int(row.tenant_id),
                    "knowledge_identity": document_identity(row.id, document_id),
                    "reference_document_id": row.reference_document_id,
                    "version_document_ids": sorted(version_docs.get(int(row.id), set())),
                    "entry_type": row.entry_type,
                    "entry_status": row.entry_status,
                    "active": row.deleted_at is None
                    and row.file_type == 1
                    and row.status == 2
                    and row.entry_status in {None, "active"}
                    and row.entry_type in {None, "manager", "publish", "share"},
                    "file_category_code": get_file_category_code_from_file(row),
                    "split_rule_category": explicit,
                    "encoding_category": encoded or None,
                    "category_source": "split_rule" if explicit else "file_encoding" if encoded else "missing",
                    "update_time": row.update_time.isoformat() if row.update_time else None,
                    "desired_content_generation": row.desired_content_generation,
                    "desired_entry_generation": row.desired_entry_generation,
                }

            grouped = {}
            for row in entries:
                if int(row.tenant_id or 0) == tenant_id:
                    grouped.setdefault(int(row.reference_document_id), []).append(
                        snapshot(row, row.reference_document_id)
                    )
            return {
                "files": {int(row.id): snapshot(row, identities[int(row.id)]) for row in files},
                "documents": {
                    int(row.id): {
                        "document_id": int(row.id),
                        "tenant_id": int(row.tenant_id),
                        "lifecycle_status": row.lifecycle_status,
                        "primary_version_id": row.primary_version_id,
                        "primary_version_file_id": primary_files.get(int(row.id)),
                        "content_generation": row.content_generation,
                    }
                    for row in documents
                },
                "entries": grouped,
            }

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
