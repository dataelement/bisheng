"""来源清理校验容忍可见性延迟, 不掩盖真实索引或权限残留。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from test.scripts.test_merge_personal_knowledge_spaces import file, m, space


@pytest.mark.parametrize("mode", ["settled", "delay", "refresh", "es", "milvus", "permissions", "refresh_error"])
async def test_verify_completed_rechecks_deleted_source(monkeypatch, mode):
    source = file()
    source_space = space()
    target = m.TargetContext(1, space(20), None, SimpleNamespace(user_id=7), "", 0)
    unit = m.MigrationUnit("file:101", "file", (source,), target, "", "", "", "")
    operations = m.GuardedOperations(1, {10: source_space})
    operations.target_files_by_source_id[source.id] = source.model_copy(update={"id": 201})
    operations.verify_target = AsyncMock()

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(get=AsyncMock(return_value=None))

    monkeypatch.setattr(m, "get_async_db_session", session)
    monkeypatch.setattr(m, "_storage_exists", lambda *args: {})
    monkeypatch.setattr(m, "_tag_snapshot", AsyncMock(return_value=m.TagSnapshot()))
    monkeypatch.setattr(m.asyncio, "sleep", AsyncMock())
    calls = 0
    refreshed = False

    def snapshot(*args):
        nonlocal calls
        calls += 1
        es = 27 if mode in {"delay", "refresh", "es", "refresh_error"} else 0
        if (mode == "delay" and calls > 1) or (mode == "refresh" and refreshed):
            es = 0
        return m.IndexSnapshot(27 if mode == "milvus" else 0, es)

    def refresh(*args):
        nonlocal refreshed
        if mode == "refresh_error":
            raise RuntimeError("refresh unavailable")
        refreshed = True

    refresh_mock = Mock(side_effect=refresh)
    monkeypatch.setattr(m, "_index_snapshot", snapshot)
    monkeypatch.setattr(m, "_refresh_es_after_delete", refresh_mock)
    monkeypatch.setattr(
        m, "_read_permission_tuples", AsyncMock(return_value=({"relation": "owner"},) if mode == "permissions" else ())
    )
    errors = {
        "es": "es_count=27",
        "milvus": "milvus_count=27",
        "permissions": "permission_count=1",
        "refresh_error": "refresh unavailable",
    }
    if mode in errors:
        with pytest.raises(RuntimeError, match=errors[mode]):
            await m.MigrationBackend.verify_completed(None, unit, operations, [])
    else:
        await m.MigrationBackend.verify_completed(None, unit, operations, [])
    assert refresh_mock.call_count == int(mode in {"refresh", "es", "refresh_error"})
    if mode == "settled":
        assert calls == 1
        m.asyncio.sleep.assert_not_called()
