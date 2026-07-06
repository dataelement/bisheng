"""收藏源文件变更 → 站内信 的单元测试。

覆盖：
  - 逐收藏者发送、排除编辑者本人、按用户去重、跳转到各自的收藏库。
  - message_service 缺失时不发送、不查库。
  - 单条发送异常被吞掉，不影响其它收藏者、不向上抛。
  - DAO 反查的 JSON 匹配（int/str 混存、缺字段）。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services import favorite_notify
from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_RENAMED,
    notify_favorite_source_changed,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao


def _ref(user_id, knowledge_id, file_name="源文件.pdf"):
    return SimpleNamespace(user_id=user_id, knowledge_id=knowledge_id, file_name=file_name)


def _business_url(items):
    return next(i for i in items if i.get("type") == "business_url")


@pytest.mark.asyncio
async def test_notify_sends_to_each_favoriter_except_editor():
    ms = SimpleNamespace(send_generic_notify=AsyncMock())
    referrers = [
        _ref(user_id=11, knowledge_id=201),  # 收藏者 A -> 自己的收藏库 201
        _ref(user_id=12, knowledge_id=202),  # 收藏者 B -> 自己的收藏库 202
        _ref(user_id=7, knowledge_id=207),   # 编辑者本人 -> 排除
    ]
    with patch.object(favorite_notify.KnowledgeFileDao, "aget_favorite_referrers",
                      new=AsyncMock(return_value=referrers)):
        await notify_favorite_source_changed(
            ms,
            source_file_id=999,
            file_name="季度报告.pdf",
            action_code=FAVORITE_SOURCE_RENAMED,
            actor_user_id=7,
            actor_user_name="张三",
        )

    assert ms.send_generic_notify.await_count == 2  # 编辑者被排除
    calls = ms.send_generic_notify.await_args_list
    receivers = sorted(c.kwargs["receiver_user_ids"][0] for c in calls)
    assert receivers == [11, 12]

    space_ids = set()
    for c in calls:
        assert c.kwargs["action_code"] == FAVORITE_SOURCE_RENAMED
        assert c.kwargs["sender"] == 7
        bu = _business_url(c.kwargs["content_item_list"])
        # 跳转到收藏者自己的收藏库
        space_ids.add(bu["metadata"]["data"]["knowledge_space_id"])
        # 展示文本用变更后的文件名
        assert "季度报告.pdf" in bu["content"]
    assert space_ids == {"201", "202"}


@pytest.mark.asyncio
async def test_notify_noop_when_message_service_missing():
    with patch.object(favorite_notify.KnowledgeFileDao, "aget_favorite_referrers",
                      new=AsyncMock()) as dao:
        await notify_favorite_source_changed(
            None,
            source_file_id=1,
            file_name="x",
            action_code=FAVORITE_SOURCE_RENAMED,
            actor_user_id=7,
        )
        dao.assert_not_awaited()  # 连库都不查


@pytest.mark.asyncio
async def test_notify_dedups_same_user_multiple_refs():
    ms = SimpleNamespace(send_generic_notify=AsyncMock())
    referrers = [_ref(11, 201), _ref(11, 201)]  # 同一用户两条引用
    with patch.object(favorite_notify.KnowledgeFileDao, "aget_favorite_referrers",
                      new=AsyncMock(return_value=referrers)):
        await notify_favorite_source_changed(
            ms,
            source_file_id=5,
            file_name="a",
            action_code=FAVORITE_SOURCE_RENAMED,
            actor_user_id=7,
        )
    assert ms.send_generic_notify.await_count == 1


@pytest.mark.asyncio
async def test_notify_no_referrers_sends_nothing():
    ms = SimpleNamespace(send_generic_notify=AsyncMock())
    with patch.object(favorite_notify.KnowledgeFileDao, "aget_favorite_referrers",
                      new=AsyncMock(return_value=[])):
        await notify_favorite_source_changed(
            ms,
            source_file_id=5,
            file_name="a",
            action_code=FAVORITE_SOURCE_RENAMED,
            actor_user_id=7,
        )
    ms.send_generic_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_send_error_is_swallowed_and_continues():
    ms = SimpleNamespace(send_generic_notify=AsyncMock(side_effect=[RuntimeError("boom"), None]))
    referrers = [_ref(11, 201), _ref(12, 202)]
    with patch.object(favorite_notify.KnowledgeFileDao, "aget_favorite_referrers",
                      new=AsyncMock(return_value=referrers)):
        # 第一条抛错不应中断，也不应向上抛
        await notify_favorite_source_changed(
            ms,
            source_file_id=5,
            file_name="a",
            action_code=FAVORITE_SOURCE_RENAMED,
            actor_user_id=7,
        )
    assert ms.send_generic_notify.await_count == 2  # 第二条仍被尝试


# ── DAO 反查的 JSON 匹配 ───────────────────────────────────────────────────

def _row(meta):
    return SimpleNamespace(user_metadata=meta)


def test_match_favorite_referrer_int_and_str():
    assert KnowledgeFileDao._match_favorite_referrer(
        _row({"favorite_reference": {"source_file_id": 42}}), 42) is True
    # JSON 里以字符串存
    assert KnowledgeFileDao._match_favorite_referrer(
        _row({"favorite_reference": {"source_file_id": "42"}}), 42) is True


def test_match_favorite_referrer_mismatch_and_missing():
    assert KnowledgeFileDao._match_favorite_referrer(
        _row({"favorite_reference": {"source_file_id": 43}}), 42) is False
    assert KnowledgeFileDao._match_favorite_referrer(_row({}), 42) is False
    assert KnowledgeFileDao._match_favorite_referrer(_row(None), 42) is False
    assert KnowledgeFileDao._match_favorite_referrer(
        _row({"favorite_reference": {"source_file_id": "abc"}}), 42) is False
