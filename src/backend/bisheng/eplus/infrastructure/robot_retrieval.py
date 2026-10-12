"""Scoped SQL provenance reads and index adapters for robot retrieval."""

from langchain_core.documents import Document
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.eplus.domain.schemas.knowledge import RobotFileSource
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool


class DatabaseRobotDocumentStateReader:
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
        retriever = KnowledgeRetrieverTool(
            vector_retriever=vector_store.as_retriever(search_kwargs=vector_kwargs),
            elastic_retriever=elastic_store.as_retriever(search_kwargs=elastic_kwargs),
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
            rrf_weights=[0.5, 0.5],
            rrf_remove_zero_score=True,
        )
        return await retriever._arun(query)
