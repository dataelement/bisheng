from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.repositories.interfaces.knowledge_mcp_repository import KnowledgeMcpRepository
from bisheng.knowledge.rag.shared_space_storage import aresolve_space_shared_routing


class KnowledgeMcpRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeMcpRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeFile)

    async def get_space(self, knowledge_id: int) -> Knowledge | None:
        return await self.session.get(Knowledge, knowledge_id)

    async def find_by_id(self, entity_id: int) -> KnowledgeFile | None:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.id == entity_id,
                KnowledgeFileDao.active_inventory_predicate(),
                or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(statement)).first()

    async def spaces(
        self, ids: list[int], *, name: str | None = None, after: list | None = None, limit: int = 100
    ) -> list[Knowledge]:
        if not ids:
            return []
        statement = select(Knowledge).where(
            col(Knowledge.id).in_(ids),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.state != KnowledgeState.DELETING.value,
        )
        if name:
            statement = statement.where(col(Knowledge.name).contains(name, autoescape=True))
        if after:
            statement = statement.where(
                or_(Knowledge.name > after[0], and_(Knowledge.name == after[0], Knowledge.id > after[1]))
            )
        return list((await self.session.exec(statement.order_by(Knowledge.name, Knowledge.id).limit(limit))).all())

    async def scan_files(
        self,
        space_ids: list[int],
        *,
        file_type: int,
        parent_path: str | None = None,
        recursive: bool = False,
        statuses: list[int] | None = None,
        after: list | None = None,
        sort_by: str = "update_time",
        order: str = "desc",
        limit: int = 100,
    ) -> list[KnowledgeFile]:
        if not space_ids:
            return []
        if sort_by not in {"file_name", "update_time"} or order not in {"asc", "desc"}:
            raise ValueError("invalid file order")
        statement = select(KnowledgeFile).where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == file_type,
            KnowledgeFileDao.active_inventory_predicate(),
            or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
        )
        path = func.coalesce(KnowledgeFile.file_level_path, "")
        if parent_path is not None:
            predicate = path == parent_path
            if recursive:
                predicate = or_(predicate, path.startswith(parent_path + "/", autoescape=True))
            statement = statement.where(predicate)
        if statuses is not None:
            statement = statement.where(col(KnowledgeFile.status).in_(statuses))
        value = (
            func.coalesce(KnowledgeFile.file_name, "")
            if sort_by == "file_name"
            else func.coalesce(KnowledgeFile.update_time, KnowledgeFile.create_time, datetime(1970, 1, 1))
        )
        if after:
            key = after[0] if sort_by == "file_name" else datetime.fromisoformat(after[0])
            statement = statement.where(
                or_(
                    value > key if order == "asc" else value < key,
                    and_(value == key, KnowledgeFile.id > after[1] if order == "asc" else KnowledgeFile.id < after[1]),
                )
            )
        ordering = (value.asc(), KnowledgeFile.id.asc()) if order == "asc" else (value.desc(), KnowledgeFile.id.desc())
        return list((await self.session.exec(statement.order_by(*ordering).limit(min(max(limit, 1), 100)))).all())

    async def content_refs(self, files: list[KnowledgeFile]) -> dict[int, tuple[int, int, int]]:
        if not files:
            return {}
        statement = (
            select(
                KnowledgeFile.id,
                KnowledgeDocument.id,
                KnowledgeDocument.primary_version_id,
                KnowledgeDocument.content_generation,
            )
            .outerjoin(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id
                == func.coalesce(
                    KnowledgeFile.reference_document_id,
                    KnowledgeDocumentVersion.document_id,
                ),
            )
            .where(col(KnowledgeFile.id).in_([f.id for f in files]), KnowledgeDocument.lifecycle_status == "active")
        )
        rows = (await self.session.exec(statement)).all()
        return {
            int(file_id): (int(doc_id), int(version_id), int(generation))
            for file_id, doc_id, version_id, generation in rows
            if version_id is not None
        }

    @staticmethod
    def _filters(file: KnowledgeFile, ref: tuple[int, int, int]) -> list[dict]:
        return [
            {"term": {"metadata.knowledge_ids": int(file.knowledge_id)}},
            {"term": {"metadata.canonical_document_id": ref[0]}},
            {"term": {"metadata.canonical_version_id": ref[1]}},
            {"term": {"metadata.content_generation": ref[2]}},
        ]

    @staticmethod
    async def _route(files: list[KnowledgeFile]) -> Any:
        tenant_ids = {int(f.tenant_id or 1) for f in files}
        if len(tenant_ids) != 1:
            raise ValueError("cross-tenant content scope")
        route = await aresolve_space_shared_routing(next(iter(tenant_ids)), KnowledgeTypeEnum.SPACE.value)
        if route is None:
            raise ValueError("knowledge content storage unavailable")
        return route

    async def content_matches(self, files: list[KnowledgeFile], keyword: str) -> set[int]:
        if not files:
            return set()
        if len(files) > 100:
            raise ValueError("content candidate batch too large")
        route = await self._route(files)
        refs = await self.content_refs(files)
        filters = {str(f.id): {"bool": {"filter": self._filters(f, refs[f.id])}} for f in files if f.id in refs}
        if not filters:
            return set()
        client = await get_es_connection()
        result = await client.search(
            index=route.index_name,
            size=0,
            query={
                "bool": {
                    "must": [{"match_phrase": {"text": keyword}}],
                    "filter": [{"terms": {"metadata.knowledge_ids": sorted({f.knowledge_id for f in files})}}],
                }
            },
            aggs={"entries": {"filters": {"filters": filters}}},
        )
        return {
            int(key)
            for key, bucket in result.get("aggregations", {}).get("entries", {}).get("buckets", {}).items()
            if bucket.get("doc_count", 0) > 0
        }

    async def chunks(
        self, file: KnowledgeFile, ref: tuple[int, int, int], *, from_index: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        route = await self._route([file])
        client = await get_es_connection()
        response = await client.search(
            index=route.index_name,
            size=min(limit, 101),
            query={
                "bool": {
                    "filter": [*self._filters(file, ref), {"range": {"metadata.chunk_index": {"gte": from_index}}}]
                }
            },
            sort=[{"metadata.chunk_index": "asc"}],
        )
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
