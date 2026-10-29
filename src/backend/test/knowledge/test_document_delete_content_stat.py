"""文档入口删除后要把文件 id 送进知识空间内容统计投影."""

import pytest

from test.knowledge.test_knowledge_document_distribution_delete import (
    _publish_command,
    _seed_manager,
    _service,
)


@pytest.fixture(autouse=True)
def tenant_scope(tenant_context):
    tenant_context(7)


@pytest.mark.asyncio
async def test_removing_publish_entry_enqueues_content_stat(async_db_session, monkeypatch):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    published = await service.publish_approved(
        _publish_command(
            approval_instance_id=7001,
            source_space=10,
            target_space=20,
            target_path="/18",
        )
    )
    enqueued: list[int] = []

    async def capture_content_stat(file_ids):
        enqueued.extend(int(file_id) for file_id in file_ids)
        return True

    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.KnowledgeSpaceContentStat.enqueue_file_stat_async",
        capture_content_stat,
    )

    await service.remove_publish_entry(
        tenant_id=7,
        document_id=91,
        publish_entry_id=published.publish_entry_id,
    )

    assert enqueued == [published.publish_entry_id]


@pytest.mark.asyncio
async def test_recycling_manager_enqueues_every_left_file(async_db_session, monkeypatch):
    await _seed_manager(async_db_session)
    service = _service(async_db_session)
    enqueued: list[int] = []

    async def capture_content_stat(file_ids):
        enqueued.extend(int(file_id) for file_id in file_ids)
        return True

    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.knowledge_space_content.KnowledgeSpaceContentStat.enqueue_file_stat_async",
        capture_content_stat,
    )

    result = await service.delete_manager(
        tenant_id=7,
        document_id=91,
        manager_file_id=100,
        actor_id=11,
        actor_name="管理员甲",
    )

    assert result.action == "recycle"
    assert enqueued == [100]
