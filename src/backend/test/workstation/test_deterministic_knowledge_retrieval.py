from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
