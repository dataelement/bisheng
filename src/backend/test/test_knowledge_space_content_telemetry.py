from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeAsyncIndexClient:
    def __init__(self):
        self.index_calls = []
        self.indices = SimpleNamespace(exists=AsyncMock(return_value=True))

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)
        return {"result": "created"}


class _FakeSyncIndexClient:
    def __init__(self):
        self.deleted_queries = []
        self.indices = SimpleNamespace(exists=lambda **kwargs: True)

    def delete_by_query(self, **kwargs):
        self.deleted_queries.append(kwargs)
        return {"deleted": 3}


@pytest.mark.asyncio
async def test_knowledge_space_content_log_preview_success_builds_preview_record(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeAsyncIndexClient()

    async def fake_get_es_connection():
        return fake_client

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection", fake_get_es_connection)
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "_get_user_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "generate_uuid", lambda: "event-1")

    file_record = SimpleNamespace(
        id=11,
        user_id=7,
        user_name="上传人",
        file_name="方案.pdf",
        file_type=1,
    )
    space = SimpleNamespace(id=3, name="知识空间")

    await module.KnowledgeSpaceContentStat.log_preview_success(
        file_record=file_record,
        space=space,
        viewer_user_id=9,
        viewer_user_name="查看人",
    )

    assert fake_client.index_calls
    call = fake_client.index_calls[0]
    assert call["index"] == "mid_knowledge_space_content_stat"
    assert call["id"] == "preview_event-1"
    assert call["document"]["record_type"] == "preview"
    assert call["document"]["event_id"] == "event-1"
    assert call["document"]["space_id"] == 3
    assert call["document"]["file_id"] == 11
    assert call["document"]["viewer_user_id"] == 9
    assert call["document"]["action_result"] == "success"


def test_knowledge_space_content_delete_stale_file_records_uses_sync_run_id(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake_client = _FakeSyncIndexClient()

    monkeypatch.setattr("bisheng.telemetry.domain.mid_table.base.get_es_connection_sync", lambda: fake_client)

    deleted = module.KnowledgeSpaceContentStat().delete_stale_file_records_sync("run-1")

    assert deleted == 3
    call = fake_client.deleted_queries[0]
    assert call["index"] == "mid_knowledge_space_content_stat"
    assert call["refresh"] is True
    assert call["body"]["query"]["bool"]["filter"] == [{"term": {"record_type": "file"}}]
    assert call["body"]["query"]["bool"]["must_not"] == [{"term": {"sync_run_id": "run-1"}}]
