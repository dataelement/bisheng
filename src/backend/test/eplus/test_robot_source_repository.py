"""Real SQL provenance reads must stay inside the robot's tenant and spaces."""

from contextlib import asynccontextmanager

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.eplus.infrastructure import robot_retrieval
from bisheng.eplus.infrastructure.robot_retrieval import DatabaseRobotDocumentStateReader, DatabaseRobotRetrievalBackend
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


@pytest.fixture
async def source_reader(monkeypatch):
    token = current_tenant_id.set(73)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: SQLModel.metadata.create_all(conn, tables=[Knowledge.__table__, KnowledgeFile.__table__])
            )

        @asynccontextmanager
        async def session_factory():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        monkeypatch.setattr(robot_retrieval, "get_async_db_session", session_factory)
        async with session_factory() as session:
            session.add_all(
                [
                    Knowledge(id=11, name="部门一", tenant_id=73, type=3),
                    Knowledge(id=12, name="部门二", tenant_id=73, type=3),
                    Knowledge(id=13, name="普通知识库", tenant_id=73, type=0),
                    Knowledge(id=99, name="未绑定空间", tenant_id=73, type=3),
                    Knowledge(id=100, name="其他租户", tenant_id=74, type=3),
                ]
            )
            session.add_all(
                [
                    KnowledgeFile(
                        id=fid, file_name="same.csv", knowledge_id=sid, tenant_id=tenant, status=status, file_type=kind
                    )
                    for fid, sid, tenant, status, kind in [
                        (101, 11, 73, 2, 1),
                        (102, 12, 73, 2, 1),
                        (103, 99, 73, 2, 1),
                        (104, 11, 73, 3, 1),
                        (105, 11, 73, 2, 0),
                        (106, 11, 74, 2, 1),
                        (107, 100, 73, 2, 1),
                        (108, 13, 73, 2, 1),
                    ]
                ]
            )
            await session.commit()
        yield DatabaseRobotDocumentStateReader()
    finally:
        await engine.dispose()
        current_tenant_id.reset(token)


async def test_exact_lookup_keeps_same_name_files_separate_and_excludes_invalid_sources(source_reader):
    sources = await source_reader.file_sources(tenant_id=73, space_ids=(11, 12, 13, 100), file_name="same.csv")
    assert set(sources) == {101, 102}
    assert (sources[101].file_name, sources[101].space_id, sources[101].space_name) == ("same.csv", 11, "部门一")
    assert (sources[102].file_name, sources[102].space_id, sources[102].space_name) == ("same.csv", 12, "部门二")


async def test_postfilter_requires_current_file_row_not_just_index_metadata(source_reader):
    sources = await source_reader.file_sources(tenant_id=73, space_ids=(11,), file_ids=set(range(101, 110)))
    assert set(sources) == {101}


async def test_no_unbounded_directory_read_is_available(source_reader):
    with pytest.raises(ValueError):
        await source_reader.file_sources(tenant_id=73, space_ids=(11,))
    assert await source_reader.file_sources(tenant_id=73, space_ids=(11,), file_ids=set()) == {}
    assert await source_reader.file_sources(tenant_id=73, space_ids=(), file_name="same.csv") == {}
    assert await source_reader.file_sources(tenant_id=73, space_ids=(11,), file_name="Same.csv") == {}
    assert await source_reader.file_sources(tenant_id=73, space_ids=(11,), file_name="%.csv") == {}


async def test_exact_filename_also_constrains_the_postfilter(source_reader):
    assert await source_reader.file_sources(tenant_id=73, space_ids=(11,), file_ids={101}, file_name="wrong.csv") == {}


async def test_filename_keywords_are_bounded_literal_and_scope_checked(source_reader):
    sources = await source_reader.search_file_sources(
        tenant_id=73, space_ids=(11, 12, 13, 100), keywords=("same", "csv")
    )
    assert set(sources) == {101, 102}
    assert await source_reader.search_file_sources(tenant_id=73, space_ids=(11, 12), keywords=("%",)) == {}
    assert await source_reader.search_file_sources(tenant_id=73, space_ids=(11, 12), keywords=("_",)) == {}
    with pytest.raises(ValueError):
        await source_reader.search_file_sources(tenant_id=73, space_ids=(11,), keywords=())
    assert (
        len(await source_reader.search_file_sources(tenant_id=73, space_ids=(11, 12), keywords=("same",), limit=1)) == 1
    )


async def test_exact_search_applies_file_ids_to_both_index_queries(source_reader, monkeypatch):
    class Retriever(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager):
            return [Document(page_content="answer", metadata={"document_id": 101, "knowledge_id": 11})]

    class Store:
        def __init__(self):
            self.options = None

        def as_retriever(self, *, search_kwargs):
            self.options = search_kwargs
            return Retriever()

    vector, elastic = Store(), Store()

    async def init_vector(*args, **kwargs):
        return vector

    async def init_elastic(*args, **kwargs):
        return elastic

    monkeypatch.setattr(robot_retrieval.KnowledgeRag, "init_knowledge_milvus_vectorstore", init_vector)
    monkeypatch.setattr(robot_retrieval.KnowledgeRag, "init_knowledge_es_vectorstore", init_elastic)
    result = await DatabaseRobotRetrievalBackend().retrieve_space(
        tenant_id=73,
        space_id=11,
        query="query",
        invoke_user_id=9,
        max_content=15000,
        sort_by_source_and_index=False,
        file_ids=(101,),
    )

    assert [d.page_content for d in result] == ["answer"]
    assert vector.options == {"expr": "document_id in [101]"}
    assert elastic.options == {"filter": [{"terms": {"metadata.document_id": [101]}}]}


async def test_hybrid_rank_keeps_both_channels_without_local_trimming(source_reader, monkeypatch):
    def doc(fid):
        return Document(page_content="same body", metadata={"document_id": fid, "knowledge_id": 11})

    class Retriever(BaseRetriever):
        documents: list[Document]

        def _get_relevant_documents(self, query, *, run_manager):
            return self.documents

    class Store:
        def __init__(self, ids):
            self.ids = ids

        def as_retriever(self, *, search_kwargs):
            return Retriever(documents=[doc(fid) for fid in self.ids])

    async def vector(*args, **kwargs):
        return Store([101, 102, 103, 104])

    async def elastic(*args, **kwargs):
        return Store([104, 105])

    monkeypatch.setattr(robot_retrieval.KnowledgeRag, "init_knowledge_milvus_vectorstore", vector)
    monkeypatch.setattr(robot_retrieval.KnowledgeRag, "init_knowledge_es_vectorstore", elastic)
    result = await DatabaseRobotRetrievalBackend().retrieve_space(
        tenant_id=73, space_id=11, query="query", invoke_user_id=9, max_content=1, sort_by_source_and_index=False
    )
    assert result[0].metadata["document_id"] == 104
    assert {d.metadata["document_id"] for d in result} == {101, 102, 103, 104, 105}
    assert all(d.page_content == "same body" for d in result)
    assert [d.metadata["robot_recall_rank"] for d in result] == list(range(1, 6))
