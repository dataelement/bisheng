"""Scoped SQL provenance reads and index adapters for robot retrieval."""

from langchain_core.documents import Document
from sqlalchemy import func
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.eplus.domain.schemas.knowledge import RobotFileSource
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus


class DatabaseRobotDocumentStateReader:
    async def search_file_sources(
        self, *, tenant_id: int, space_ids: tuple[int, ...], keywords: tuple[str, ...], limit: int = 50
    ) -> dict[int, RobotFileSource]:
        if not keywords or any(not term.strip() for term in keywords):
            raise ValueError("filename search requires nonblank keywords")
        if not space_ids:
            return {}
        statement = (
            select(KnowledgeFile.id, KnowledgeFile.file_name, Knowledge.id, Knowledge.name)
            .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
            .where(
                KnowledgeFile.tenant_id == tenant_id,
                Knowledge.tenant_id == tenant_id,
                col(Knowledge.id).in_(space_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                *(func.lower(KnowledgeFile.file_name).contains(term.casefold(), autoescape=True) for term in keywords),
            )
            .order_by(KnowledgeFile.id)
            .limit(max(1, min(int(limit), 50)))
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return {int(fid): RobotFileSource(int(fid), name, int(sid), space_name) for fid, name, sid, space_name in rows}

    async def file_sources(
        self,
        *,
        tenant_id: int,
        space_ids: tuple[int, ...],
        file_ids: set[int] | None = None,
        file_name: str | None = None,
    ) -> dict[int, RobotFileSource]:
        if not space_ids or file_ids == set():
            return {}
        if file_ids is None and file_name is None:
            raise ValueError("robot source lookup requires file ids or an exact filename")
        statement = (
            select(KnowledgeFile.id, KnowledgeFile.file_name, Knowledge.id, Knowledge.name)
            .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
            .where(
                KnowledgeFile.tenant_id == tenant_id,
                Knowledge.tenant_id == tenant_id,
                col(Knowledge.id).in_(space_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            )
            .order_by(KnowledgeFile.id)
        )
        if file_ids is not None:
            statement = statement.where(col(KnowledgeFile.id).in_(file_ids))
        if file_name is not None:
            statement = statement.where(KnowledgeFile.file_name == file_name)
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        # SQL collation can be case-insensitive; enforce exact spelling in Python too.
        return {
            int(fid): RobotFileSource(int(fid), name, int(sid), space_name)
            for fid, name, sid, space_name in rows
            if file_name is None or name == file_name
        }


class DatabaseRobotRetrievalBackend:
    async def retrieve_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        query: str,
        invoke_user_id: int,
        max_content: int,
        sort_by_source_and_index: bool,
        file_ids: tuple[int, ...] | None = None,
    ) -> list[Document]:
        if file_ids == ():
            return []
        async with get_async_db_session() as session:
            statement = select(Knowledge).where(
                Knowledge.tenant_id == tenant_id,
                Knowledge.id == space_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            space = (await session.exec(statement)).first()
        if space is None:
            return []
        vector_store = await KnowledgeRag.init_knowledge_milvus_vectorstore(invoke_user_id, knowledge=space)
        elastic_store = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        vector_kwargs, elastic_kwargs = {}, {}
        if file_ids is not None:
            ids = sorted({int(fid) for fid in file_ids})
            vector_kwargs["expr"] = f"document_id in {ids}"
            elastic_kwargs["filter"] = [{"terms": {"metadata.document_id": ids}}]
        # Keep bounded index top-k candidates, but defer all character trimming
        # until every bound space has contributed to the global fusion.
        vector_docs = await vector_store.as_retriever(search_kwargs=vector_kwargs).ainvoke(query)
        elastic_docs = await elastic_store.as_retriever(search_kwargs=elastic_kwargs).ainvoke(query)
        candidates, scores = {}, {}
        for channel in (vector_docs, elastic_docs):
            seen = set()
            for rank, doc in enumerate(channel, 1):
                key = (
                    str(doc.metadata.get("document_id")),
                    str(doc.metadata.get("chunk_index") or 0),
                    doc.page_content,
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.setdefault(key, doc)
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        # Preserve support from both recall channels without comparing their
        # raw scores or merging equal text belonging to different files.
        ordered = sorted(candidates, key=lambda key: (-scores[key], key))
        return [
            Document(
                page_content=candidates[key].page_content,
                metadata={**candidates[key].metadata, "robot_recall_rank": rank},
            )
            for rank, key in enumerate(ordered, 1)
        ]
