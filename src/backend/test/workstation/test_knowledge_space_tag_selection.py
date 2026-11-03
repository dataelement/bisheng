"""User-selected tags constrain retrieval before candidate ranking."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from bisheng.workstation.domain.schemas.chat import UseKnowledgeBaseParam


def test_tag_filter_round_trip():
    params = UseKnowledgeBaseParam.model_validate(
        {"knowledge_space_ids": [7], "knowledge_space_tag_filters": {"7": 11}}
    )
    assert params.knowledge_space_tag_filters == {7: 11}
    assert UseKnowledgeBaseParam().knowledge_space_tag_filters == {}


@pytest.mark.parametrize("filters", [{8: 11}, {7: 0}, {7: -1}, {7: True}, {0: 11}, {7: 1.5}, {7.0: 11}, {"7.0": 11}])
def test_tag_filter_rejects_invalid_selection(filters):
    with pytest.raises(ValidationError):
        UseKnowledgeBaseParam(knowledge_space_ids=[7], knowledge_space_tag_filters=filters)


async def test_tag_scope_reuses_primary_and_visibility_prefilter(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
        IndexFilter,
        KnowledgeFileVisibilityService,
    )
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService

    repo = SimpleNamespace(
        tag_belongs_to_space=AsyncMock(return_value=True), list_tagged_file_ids=AsyncMock(return_value=[40, 41])
    )
    expected = IndexFilter(
        strategy="in", milvus_expr="document_id in [40]", es_filter=[{"terms": {"metadata.document_id": [40]}}]
    )
    build = AsyncMock(return_value=expected)
    monkeypatch.setattr(KnowledgeFileVisibilityService, "build_index_prefilter", build)
    assert await KnowledgeSpaceTagFilterService(repo).build_index_prefilter(7, 11, MagicMock()) is expected
    build.assert_awaited_once_with(7, candidate_file_ids=[40, 41])


async def test_invalid_or_empty_tag_never_widens_scope(monkeypatch):
    from bisheng.common.errcode.tag import TagNotExistError
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService

    repo = SimpleNamespace(
        tag_belongs_to_space=AsyncMock(return_value=False), list_tagged_file_ids=AsyncMock(return_value=[])
    )
    service = KnowledgeSpaceTagFilterService(repo)
    with pytest.raises(TagNotExistError):
        await service.build_index_prefilter(7, 11, MagicMock())
    repo.list_tagged_file_ids.assert_not_awaited()
    repo.tag_belongs_to_space.return_value = True
    build = AsyncMock()
    monkeypatch.setattr(KnowledgeFileVisibilityService, "build_index_prefilter", build)
    assert (await service.build_index_prefilter(7, 11, MagicMock())).is_empty
    build.assert_not_awaited()


@pytest.mark.parametrize("tagged", [False, True, "empty", "error"])
async def test_both_indexes_receive_scope_before_retrieval(monkeypatch, tagged):
    from langchain_core.documents import Document

    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService
    from bisheng.workstation.domain.services import workstation_service as module

    calls = []

    def retriever(**kwargs):
        calls.append(kwargs["search_kwargs"][0])
        return MagicMock()

    monkeypatch.setattr(module, "MultiRetriever", retriever)
    monkeypatch.setattr(
        module,
        "KnowledgeRetrieverTool",
        lambda **kwargs: SimpleNamespace(
            ainvoke=AsyncMock(return_value=[Document(page_content="tagged hit", metadata={"document_id": 40})])
        ),
    )
    monkeypatch.setattr(
        module.WorkStationService,
        "_filter_visible_space_kb_ids",
        AsyncMock(return_value={"space_kb_ids": [7], "org_kb_ids": []}),
    )
    monkeypatch.setattr(
        module.KnowledgeRag,
        "get_multi_knowledge_vectorstore",
        AsyncMock(
            return_value={7: {"milvus": MagicMock(), "es": MagicMock(), "knowledge": SimpleNamespace(name="space")}}
        ),
    )
    post_filter = AsyncMock(side_effect=lambda **kwargs: kwargs["docs"])
    monkeypatch.setattr(module.WorkStationService, "_post_filter_kb_docs_by_view_file", post_filter)
    scope = IndexFilter(
        strategy="in", milvus_expr="document_id in [40]", es_filter=[{"terms": {"metadata.document_id": [40]}}]
    )
    if tagged == "empty":
        scope = IndexFilter(strategy="empty")
    prefilter = AsyncMock(return_value=scope)
    if tagged == "error":
        prefilter.side_effect = ValueError("Tag selection could not be resolved")
    monkeypatch.setattr(KnowledgeSpaceTagFilterService, "build_index_prefilter", prefilter)
    _, docs, failures = await module.WorkStationService.queryChunksFromDB(
        "question",
        UseKnowledgeBaseParam(knowledge_space_ids=[7], knowledge_space_tag_filters={7: 11} if tagged else {}),
        1000,
        MagicMock(),
    )
    if tagged in ("empty", "error"):
        assert docs == []
        assert len(failures) == (1 if tagged == "error" else 0)
        assert calls == []
        post_filter.assert_not_awaited()
        return
    assert len(docs) == 1 and failures == []
    post_filter.assert_awaited_once()
    if tagged:
        assert calls[0]["expr"] == scope.milvus_expr
        assert calls[1]["filter"] == scope.es_filter
        prefilter.assert_awaited_once()
    else:
        assert "expr" not in calls[0] and "filter" not in calls[1]
        prefilter.assert_not_awaited()


async def test_daily_tool_freezes_user_tag_and_drops_it_for_unselected_subset(monkeypatch):
    from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
    from bisheng.workstation.domain.services import chat_service as module

    query = AsyncMock(return_value=([], [], []))
    monkeypatch.setattr(module.WorkStationService, "queryChunksFromDB", query)
    tool = await module._build_knowledge_search_tool(
        [{"id": 7, "source": "space", "selected_tag_id": 11}, {"id": 8, "source": "space"}],
        SimpleNamespace(user_id=42),
        1000,
        CitationRegistryCollector(),
    )
    await tool.ainvoke(
        {
            "knowledge_base_ids": ["7"],
            "query": "Q",
            "filters": {"knowledge_base_filters": [{"knowledge_base_id": "7", "tags": ["other tag"]}]},
        }
    )
    params = query.await_args.kwargs["use_knowledge_param"]
    assert params.knowledge_space_tag_filters == {7: 11}
    await tool.ainvoke({"knowledge_base_ids": ["8"], "query": "Q"})
    assert query.await_args.kwargs["use_knowledge_param"].knowledge_space_tag_filters == {}


async def test_repository_checks_tag_owner_type_and_space_file_links(monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.database.models.group_resource import ResourceTypeEnum
    from bisheng.knowledge.domain.repositories import knowledge_space_tag_repository as module

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        for statement in [
            "CREATE TABLE tag (id INTEGER PRIMARY KEY, business_type TEXT, business_id TEXT, tenant_id INTEGER)",
            "CREATE TABLE taglink (id INTEGER PRIMARY KEY, tag_id INTEGER, resource_type INTEGER, resource_id TEXT, tenant_id INTEGER)",
            "CREATE TABLE knowledgefile (id INTEGER PRIMARY KEY, knowledge_id INTEGER, tenant_id INTEGER)",
            "INSERT INTO tag VALUES (11, 'knowledge_space', '7', 1), (12, 'knowledge_space', '8', 1), (13, 'knowledge', '7', 1)",
            "INSERT INTO knowledgefile VALUES (40, 7, 1), (41, 8, 1), (42, 7, 1)",
        ]:
            await connection.execute(text(statement))
        await connection.execute(
            text(
                "INSERT INTO taglink VALUES (1, 11, :space, '40', 1), (2, 11, :space, '41', 1), (3, 11, :org, '42', 1), (4, 11, :space, 'not-an-id', 1)"
            ),
            {"space": ResourceTypeEnum.SPACE_FILE.value, "org": ResourceTypeEnum.KNOWLEDGE_FILE.value},
        )

    @asynccontextmanager
    async def session_scope():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(module, "get_async_db_session", session_scope)
    try:
        repository = module.KnowledgeSpaceTagRepository()
        assert await repository.tag_belongs_to_space(7, 11)
        assert not await repository.tag_belongs_to_space(7, 12)
        assert not await repository.tag_belongs_to_space(7, 13)
        assert not await repository.tag_belongs_to_space(7, 999)
        assert await repository.list_tagged_file_ids(7, 11) == [40]
    finally:
        await engine.dispose()


async def test_daily_selection_preserves_fixed_tag_metadata(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService
    from bisheng.workstation.domain.services import chat_service as module

    validate = AsyncMock()
    monkeypatch.setattr(KnowledgeSpaceTagFilterService, "validate_selection", validate)
    monkeypatch.setattr(
        module.KnowledgeDao,
        "aget_list_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id=7, name="space", description="")]),
    )
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_filters", AsyncMock(return_value=[]))
    result = await module._resolve_user_kb_selection(
        SimpleNamespace(
            use_knowledge_base=UseKnowledgeBaseParam(knowledge_space_ids=[7], knowledge_space_tag_filters={7: 11})
        )
    )
    assert result[0]["selected_tag_id"] == 11 and result[0]["source"] == "space"
    validate.assert_awaited_once_with({7: 11})
