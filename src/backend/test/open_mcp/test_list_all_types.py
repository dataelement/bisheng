"""省略 type 时合并列出文档库和知识空间；显式传 type 的行为保持不变。

覆盖四个点：两类都返回、显式 type 不变、翻页不漏不重、游标隔离。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.open_mcp import application
from bisheng.open_mcp.contracts import KnowledgeListInput


def _patch(monkeypatch, doc_page, space_page):
    user = SimpleNamespace(user_id=7, user_name="tester")
    get_knowledge = AsyncMock(return_value=doc_page)
    list_spaces = AsyncMock(return_value=space_page)
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application.KnowledgeService, "get_knowledge", get_knowledge)
    monkeypatch.setattr(
        application,
        "_space_service",
        lambda *args: SimpleNamespace(alist_mine_and_joined_cursor=list_spaces),
    )
    return get_knowledge, list_spaces


async def _run(command):
    return await application.list_knowledge(
        request=application.current_request(),
        command=command,
        version_repo=object(),
        doc_repo=object(),
    )


@pytest.mark.asyncio
async def test_omitting_type_returns_document_bases_and_spaces(monkeypatch):
    get_knowledge, list_spaces = _patch(
        monkeypatch,
        {"data": [{"id": 1, "type": 0}], "has_more": False, "next_cursor": None},
        {"data": [{"id": 2, "type": 3}], "has_more": False, "next_cursor": None},
    )

    result = await _run(KnowledgeListInput(page_size=5))

    assert [item["id"] for item in result["data"]] == [1, 2]
    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert get_knowledge.await_count == 1
    assert list_spaces.await_count == 1


@pytest.mark.asyncio
async def test_explicit_type_behaviour_is_unchanged(monkeypatch):
    get_knowledge, list_spaces = _patch(
        monkeypatch,
        {"data": [{"id": 1, "type": 0}], "has_more": False, "next_cursor": None},
        {"data": [{"id": 2, "type": 3}], "has_more": False, "next_cursor": None},
    )

    result = await _run(KnowledgeListInput(type=0, page_size=5))

    assert result == {"data": [{"id": 1, "type": 0}], "has_more": False, "next_cursor": None}
    assert get_knowledge.await_count == 1
    assert list_spaces.await_count == 0


@pytest.mark.asyncio
async def test_merged_cursor_carries_both_sub_cursors_and_does_not_duplicate(monkeypatch):
    get_knowledge, list_spaces = _patch(
        monkeypatch,
        {"data": [{"id": 1, "type": 0}], "has_more": True, "next_cursor": "doc-cursor"},
        {"data": [{"id": 2, "type": 3}], "has_more": True, "next_cursor": "space-cursor"},
    )

    first = await _run(KnowledgeListInput(page_size=5))
    assert first["has_more"] is True
    cursor = first["next_cursor"]
    assert cursor and cursor.startswith("mcp_all:")

    # 同一页里两类各一条，没有重复
    assert [item["id"] for item in first["data"]] == [1, 2]

    # 第二页：两个子游标分别传回各自的列表实现
    get_knowledge.reset_mock()
    list_spaces.reset_mock()
    get_knowledge.return_value = {"data": [{"id": 3, "type": 0}], "has_more": False, "next_cursor": None}
    list_spaces.return_value = {"data": [{"id": 4, "type": 3}], "has_more": False, "next_cursor": None}

    second = await _run(KnowledgeListInput(page_size=5, cursor=cursor))

    assert get_knowledge.await_args.kwargs["cursor"] == "doc-cursor"
    assert list_spaces.await_args.kwargs["cursor"] == "space-cursor"
    assert [item["id"] for item in second["data"]] == [3, 4]
    assert second["has_more"] is False
    assert second["next_cursor"] is None


@pytest.mark.asyncio
async def test_cursor_from_another_mode_is_rejected(monkeypatch):
    get_knowledge, list_spaces = _patch(
        monkeypatch,
        {"data": [{"id": 1, "type": 0}], "has_more": True, "next_cursor": "doc-cursor"},
        {"data": [{"id": 2, "type": 3}], "has_more": True, "next_cursor": "space-cursor"},
    )
    merged = (await _run(KnowledgeListInput(page_size=5)))["next_cursor"]

    # 合并游标不能传给单类列表
    with pytest.raises(HTTPException) as excinfo:
        await _run(KnowledgeListInput(type=0, page_size=5, cursor=merged))
    assert excinfo.value.error_code_class.Code == 26051

    # 单类游标也不能当合并游标用
    with pytest.raises(HTTPException) as excinfo:
        await _run(KnowledgeListInput(page_size=5, cursor="doc-cursor"))
    assert excinfo.value.error_code_class.Code == 26051
