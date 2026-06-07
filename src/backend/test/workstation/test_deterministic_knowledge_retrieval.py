from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.workstation.domain.services import chat_service


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=7, user_name='tester')


def _selected_kbs() -> list[dict]:
    return [
        {
            'id': 3476,
            'name': '首钢知识空间',
            'description': '',
            'tags': [],
            'source': 'space',
        }
    ]


def test_build_user_content_includes_pre_retrieved_knowledge_context():
    content = chat_service._build_user_content(
        question='总结一下知识库中的文档内容是什么？',
        knowledge_bases_info=_selected_kbs(),
        retrieved_knowledge_context='[file name]:制度.doc\n[file content begin]\n固体废物鉴别标准\n[file content end]',
    )

    assert '<retrieved_knowledge_context>' in content
    assert '固体废物鉴别标准' in content
    assert 'search_knowledge_bases' not in content


@pytest.mark.asyncio
async def test_prepare_tools_does_not_expose_selected_kbs_as_model_tool():
    tools, failures = await chat_service._prepare_tools(
        tool_payloads=[],
        login_user=_login_user(),
        ws_config=SimpleNamespace(maxTokens=15000),
        citation_collector=MagicMock(),
        knowledge_bases_info=_selected_kbs(),
    )

    assert failures == []
    assert [tool.name for tool in tools] == []


def test_split_selected_knowledge_ids_prefers_database_type_over_request_source():
    selected_kbs = [
        {
            'id': 9,
            'source': 'organization',
            'type': KnowledgeTypeEnum.SPACE.value,
        },
        {
            'id': 8,
            'source': 'space',
            'type': KnowledgeTypeEnum.NORMAL.value,
        },
    ]

    space_ids, organization_ids = chat_service._split_selected_knowledge_ids(selected_kbs)

    assert space_ids == [9]
    assert organization_ids == [8]


@pytest.mark.asyncio
async def test_pre_retrieve_routes_knowledge_space_by_database_type_when_request_source_is_wrong(monkeypatch):
    query_chunks = AsyncMock(return_value=([], [], []))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        'queryChunksFromDB',
        query_chunks,
        raising=False,
    )

    await chat_service._retrieve_selected_knowledge_context(
        question='总结公共知识空间',
        knowledge_bases_info=[
            {
                'id': 9,
                'source': 'organization',
                'type': KnowledgeTypeEnum.SPACE.value,
            },
            {
                'id': 8,
                'source': 'space',
                'type': KnowledgeTypeEnum.NORMAL.value,
            },
        ],
        max_token=15000,
        login_user=_login_user(),
        citation_collector=MagicMock(),
    )

    use_knowledge_param = query_chunks.await_args.kwargs['use_knowledge_param']
    assert use_knowledge_param.knowledge_space_ids == [9]
    assert use_knowledge_param.organization_knowledge_ids == [8]
