"""旧重建入口必须复用批量核验, 不能在默认 Worker 解析原文件。"""

import asyncio
import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.main",
        SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda **kwargs: lambda function: function),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker._asyncio_utils",
        SimpleNamespace(
            run_async_task=lambda function: asyncio.run(function()),
        ),
    )
    path = Path(__file__).resolve().parents[2] / "bisheng/worker/knowledge/rebuild_knowledge_worker.py"
    spec = importlib.util.spec_from_file_location("shared_rebuild_worker_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("outcome", ["ready", "rebuild_queued", "not_claimed", "exhausted_unclaimed"])
async def test_old_single_file_entry_uses_probe_without_forcing_parse(worker, monkeypatch, outcome):
    events = []
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))

    @asynccontextmanager
    async def session_context():
        yield session

    async def execute(tenant_id, ids, owner, **kwargs):
        assert events == ["commit"]
        assert (tenant_id, ids) == (7, [11])
        assert not kwargs.get("allow_content_rebuild", False)
        return {"results": {11: "not_claimed" if outcome == "exhausted_unclaimed" else outcome}}

    repository = SimpleNamespace(
        request_projection_checks=AsyncMock(),
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=11,
                    projection_status="failed" if outcome == "exhausted_unclaimed" else "pending",
                )
            ]
        ),
    )
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", session_context)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl.KnowledgeFileRepositoryImpl",
        lambda _: repository,
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.document_projection",
        SimpleNamespace(
            _process_projection_batch_async=AsyncMock(side_effect=execute),
            _build_document_projection_service=AsyncMock(side_effect=AssertionError("must not force original parsing")),
        ),
    )
    if outcome == "exhausted_unclaimed":
        with pytest.raises(RuntimeError, match="projection check failed"):
            await worker._rebuild_shared_file(SimpleNamespace(id=11, tenant_id=7))
    else:
        result = await worker._rebuild_shared_file(SimpleNamespace(id=11, tenant_id=7))
        assert result["results"] == {11: outcome}
    repository.request_projection_checks.assert_awaited_once_with([11])


def test_single_file_task_keeps_original_parse_status_on_projection_failure(worker, monkeypatch):
    file = SimpleNamespace(id=11, reference_document_id=91, knowledge_id=20, tenant_id=7)
    monkeypatch.setattr(worker.KnowledgeFileDao, "query_by_id_sync", lambda _: file)
    monkeypatch.setattr(
        worker.KnowledgeDao, "query_by_id", lambda _: SimpleNamespace(type=worker.KnowledgeTypeEnum.SPACE.value)
    )
    monkeypatch.setattr(worker, "_rebuild_shared_files", AsyncMock(side_effect=RuntimeError("projection failed")))
    update = MagicMock()
    monkeypatch.setattr(worker.KnowledgeFileDao, "update_file_status", update)
    with pytest.raises(RuntimeError, match="projection failed"):
        worker.rebuild_knowledge_file_chunk(11)
    update.assert_not_called()


@pytest.mark.parametrize("outcome,expected_state", [("ready", 1), ("rebuild_queued", 3), ("not_claimed", 3)])
def test_space_rebuild_uses_one_batch_and_waits_for_content(worker, monkeypatch, outcome, expected_state):
    from bisheng.knowledge.rag import shared_space_storage

    knowledge = SimpleNamespace(id=20, tenant_id=7, type=worker.KnowledgeTypeEnum.SPACE.value, state=3)
    files = [
        SimpleNamespace(id=i, reference_document_id=100 + i // 2, entry_status="active", deleted_at=None)
        for i in range(1, 5)
    ]
    monkeypatch.setattr(worker.KnowledgeDao, "query_by_id", lambda _: knowledge)
    monkeypatch.setattr(worker.KnowledgeDao, "update_one", MagicMock())
    monkeypatch.setattr(worker.KnowledgeFileDao, "get_files_by_multiple_status", lambda *_: files)
    monkeypatch.setattr(
        shared_space_storage, "resolve_space_shared_routing", lambda *_: SimpleNamespace(embedding_model_id=9)
    )
    execute = AsyncMock(return_value={"results": {row.id: outcome for row in files}})
    monkeypatch.setattr(worker, "_rebuild_shared_files", execute, raising=False)
    monkeypatch.setattr(worker, "_rebuild_shared_file", AsyncMock(side_effect=AssertionError("must batch all entries")))
    message = worker.rebuild_knowledge_celery(20, 9, 10)
    execute.assert_awaited_once_with(7, [1, 2, 3, 4])
    assert knowledge.state == expected_state
    assert ("completed" in message) == (outcome == "ready")


@pytest.mark.parametrize("operation", ["rename", "alias"])
@pytest.mark.parametrize("logical", [True, False])
async def test_rename_enqueues_only_one_projection_path(worker, monkeypatch, operation, logical):
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    file = SimpleNamespace(
        id=11,
        tenant_id=7,
        knowledge_id=20,
        reference_document_id=91 if logical else None,
        file_name="old.pdf",
        alias_name="new.pdf",
        file_source=0,
        user_metadata={},
        file_level_path="/20",
        status=worker.KnowledgeFileStatus.SUCCESS.value,
    )
    service = object.__new__(module.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=1, user_name="test")
    for name in (
        "_require_permission_id",
        "update_folder_update_time",
        "_notify_favorite_source_changed",
        "_enqueue_document_distribution_projection",
    ):
        setattr(service, name, AsyncMock())
    service._get_file_for_action = AsyncMock(return_value=file)
    service._require_document_content_manager = AsyncMock(return_value=object() if logical else None)
    service._ensure_space_async_task_tenant_consistency = MagicMock()
    service._check_filename_sensitive_words = MagicMock()
    service.document_distribution_service = SimpleNamespace(rename_manager_document=AsyncMock(return_value=file))
    monkeypatch.setattr(module, "_require_not_write_frozen", AsyncMock())
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=20)))
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    monkeypatch.setattr(module.KnowledgeFileDao, "async_update", AsyncMock(return_value=file))
    monkeypatch.setattr(module.SpaceFileDao, "count_file_by_name", AsyncMock(return_value=0))
    monkeypatch.setattr(module.KnowledgeSpaceContentStat, "enqueue_file_stat_async", AsyncMock())
    delay = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.rebuild_knowledge_worker",
        SimpleNamespace(
            rebuild_knowledge_file_chunk=SimpleNamespace(delay=delay),
        ),
    )
    if operation == "rename":
        await service.rename_file(11, "new.pdf")
    else:
        await service._apply_accept_alias_rename(file, "new.pdf", resolved=object() if logical else None, file_id=11)
    assert file.file_name == "new.pdf"
    module.KnowledgeSpaceContentStat.enqueue_file_stat_async.assert_awaited_once_with([11])
    service._notify_favorite_source_changed.assert_awaited_once_with(
        source_space_id=20,
        source_file_id=11,
        file_name="new.pdf",
        action_code=module.FAVORITE_SOURCE_RENAMED,
        before_value="old.pdf",
        after_value="new.pdf",
    )
    if logical:
        service._enqueue_document_distribution_projection.assert_awaited_once_with(tenant_id=7, entry_ids=None)
        delay.assert_not_called()
    else:
        service._enqueue_document_distribution_projection.assert_not_awaited()
        delay.assert_called_once_with(file_id=11)
