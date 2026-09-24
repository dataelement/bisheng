from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.schemas.knowledge_recycle import RecyclePurgeRequest
from bisheng.knowledge.domain.services import knowledge_recycle_service as recycle
from bisheng.knowledge.domain.services.knowledge_file_cleanup_policy import needs_legacy_file_cleanup


@pytest.mark.parametrize(
    ("knowledge_type", "file_ids", "clear_minio", "files", "pdfs", "expected"),
    [
        (KnowledgeTypeEnum.SPACE.value, [101], True, None, None, False),
        (KnowledgeTypeEnum.SPACE.value, [101], True, [{"id": 101}], None, True),
        (KnowledgeTypeEnum.SPACE.value, [101], True, None, [{"object_name": "preview.pdf"}], True),
        (KnowledgeTypeEnum.SPACE.value, [101], False, [{"id": 101}], None, False),
        (KnowledgeTypeEnum.NORMAL.value, [101], False, None, None, True),
        (KnowledgeTypeEnum.NORMAL.value, [], True, None, None, False),
        (None, [101], True, None, None, False),
        (None, [], True, [{"id": 101}], None, True),
    ],
)
def test_cleanup_policy_preserves_snapshot_cleanup(knowledge_type, file_ids, clear_minio, files, pdfs, expected):
    knowledge = None if knowledge_type is None else SimpleNamespace(type=knowledge_type)
    assert (
        needs_legacy_file_cleanup(
            knowledge,
            file_ids,
            clear_minio=clear_minio,
            knowledge_file_snapshots=files,
            pdf_artifact_snapshots=pdfs,
        )
        is expected
    )


@pytest.mark.parametrize("knowledge_type", [KnowledgeTypeEnum.SPACE.value, KnowledgeTypeEnum.NORMAL.value, None])
async def test_purge_records_cleanup_intents_before_deleting_parent_rows(monkeypatch, knowledge_type):
    item = SimpleNamespace(
        file_id=101,
        knowledge_id=9,
        tenant_id=7,
        recycle_batch_id="batch-1",
        file_type=FileType.FILE.value,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [item]
    session = AsyncMock()
    session.execute.return_value = result
    session.__aenter__.return_value = session
    monkeypatch.setattr(recycle, "get_async_db_session", lambda: session)
    monkeypatch.setattr(recycle, "_plan_canonical_purge", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(recycle, "_apply_canonical_purge_plan", AsyncMock())
    monkeypatch.setattr(recycle, "request_file_delete_intents", AsyncMock())
    monkeypatch.setattr(recycle.KnowledgeSpaceContentStat, "enqueue_file_stat_async", AsyncMock())
    knowledge = [] if knowledge_type is None else [SimpleNamespace(id=9, type=knowledge_type)]
    monkeypatch.setattr(recycle.KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=knowledge))
    dispatch = MagicMock()
    file_worker = import_module("bisheng.worker.knowledge.file_worker")
    monkeypatch.setattr(file_worker.delete_knowledge_file_celery, "apply_async", dispatch)
    from bisheng.knowledge.domain.services import knowledge_pdf_artifact_service as pdf_service
    monkeypatch.setattr(pdf_service, "get_pdf_artifact_deletion_snapshots", AsyncMock(return_value=[]))
    session.run_sync.return_value = []
    user = SimpleNamespace(tenant_id=7, is_admin=lambda: True)

    assert await recycle.KnowledgeRecycleService(user).purge(RecyclePurgeRequest(all=True)) == {"purged": 1}

    dispatch.assert_not_called()
    assert session.run_sync.await_count == 2
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("knowledge_type", [KnowledgeTypeEnum.SPACE.value, KnowledgeTypeEnum.NORMAL.value])
@pytest.mark.parametrize("broker_down", [False, True])
def test_file_delete_keeps_delayed_snapshot_cleanup(monkeypatch, knowledge_type, broker_down):
    from bisheng.knowledge.domain.services import knowledge_pdf_artifact_service as pdf_service
    from bisheng.knowledge.domain.services import knowledge_service as service

    knowledge = SimpleNamespace(id=9, user_id=1, tenant_id=7, type=knowledge_type)
    file = SimpleNamespace(id=101, knowledge_id=9, tenant_id=7, file_name="report.pdf", object_name="original/101.pdf")
    monkeypatch.setattr(service.KnowledgeDao, "query_by_id", lambda _: knowledge)
    monkeypatch.setattr(service.KnowledgeFileDao, "select_list", lambda _: [file])
    monkeypatch.setattr(pdf_service, "get_pdf_artifact_deletion_snapshots_sync", lambda *_: [])
    monkeypatch.setattr(service, "delete_knowledge_file_vectors", MagicMock())
    cls = service.KnowledgeService
    monkeypatch.setattr(cls, "permission_service", MagicMock())
    monkeypatch.setattr(cls, "audit_telemetry_service", MagicMock())
    monkeypatch.setattr(cls, "_delete_knowledge_file_rows_atomic", AsyncMock())
    monkeypatch.setattr(cls, "delete_knowledge_file_hook", MagicMock())
    worker = import_module("bisheng.worker.knowledge.file_worker")
    monkeypatch.setattr(import_module("bisheng.worker.knowledge"), "file_worker", worker)
    dispatch = MagicMock(side_effect=RuntimeError("broker unavailable") if broker_down else None)
    monkeypatch.setattr(worker.delete_knowledge_file_celery, "apply_async", dispatch)

    assert cls.delete_knowledge_file(None, SimpleNamespace(user_id=1, user_name="admin"), [101]) is True

    dispatch.assert_called_once()
    message = dispatch.call_args.kwargs
    assert message["headers"] == {"tenant_id": 7}
    assert message["countdown"] == 300
    assert message["args"][:4] == ([101], 9, True, [])
    assert message["args"][4][0]["object_name"] == "original/101.pdf"
