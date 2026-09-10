"""目标索引复查容忍短暂不可见, 不放过真实数据缺失。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test.scripts.test_merge_personal_knowledge_spaces import file, m, space


@pytest.mark.parametrize("mode", ["delay", "refresh", "missing"])
async def test_target_index_visibility(monkeypatch, mode):
    source = file(101, "")
    copied = source.model_copy(update={"id": 201, "knowledge_id": 20})
    target = m.TargetContext(1, space(20), None, SimpleNamespace(user_id=7), "", 0)
    op = m.GuardedOperations(1, {10: space()})
    op.snapshots[101] = m.SourceSnapshot(m.TagSnapshot(), (), m.IndexSnapshot(58, 58), {})
    monkeypatch.setattr(m.KnowledgeFileDao, "query_by_id", AsyncMock(return_value=copied))
    monkeypatch.setattr(m, "_storage_exists", lambda *args: {})
    monkeypatch.setattr(m, "_tag_snapshot", AsyncMock(return_value=m.TagSnapshot()))
    monkeypatch.setattr(m, "_read_permission_tuples", AsyncMock(return_value=m._target_permission_rows(copied, target)))
    monkeypatch.setattr(m.asyncio, "sleep", AsyncMock())
    attempts = 0
    refreshed = False

    def counts(*args):
        nonlocal attempts
        attempts += 1
        visible = (mode == "delay" and attempts > 1) or (mode == "refresh" and refreshed)
        return m.IndexSnapshot(58, 58 if visible else 0)

    def refresh(*args):
        nonlocal refreshed
        refreshed = True

    monkeypatch.setattr(m, "_index_snapshot", counts)
    refresh_mock = Mock(side_effect=refresh)
    monkeypatch.setattr(m, "_refresh_es_after_delete", refresh_mock)
    if mode == "missing":
        with pytest.raises(RuntimeError, match="Elasticsearch count mismatch: source=58 target=0"):
            await op.verify_target(source, copied, target)
    else:
        await op.verify_target(source, copied, target)
    assert refresh_mock.call_count == int(mode != "delay")
