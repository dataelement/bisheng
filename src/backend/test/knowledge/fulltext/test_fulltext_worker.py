import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.services.knowledge_fulltext_dispatch_service import (
    dispatch_knowledge_fulltext_outbox_async,
)


def test_fulltext_dispatcher_schedule_uses_module_constants():
    assert constants.KNOWLEDGE_FULLTEXT_DISPATCH_TASK == "bisheng.worker.knowledge.fulltext_index.dispatch"
    assert constants.KNOWLEDGE_FULLTEXT_DISPATCH_INTERVAL_SECONDS == 300.0
    assert constants.KNOWLEDGE_FULLTEXT_RETRY_BASE_SECONDS == 300


def test_runtime_guard_allows_single_tenant_and_rejects_multi_tenant():
    constants.ensure_runtime_compatible(multi_tenant_enabled=False)
    with pytest.raises(ValueError, match="multi-tenant"):
        constants.ensure_runtime_compatible(multi_tenant_enabled=True)


async def test_dispatcher_sends_only_minimal_outbox_identity_and_revision():
    repository = AsyncMock()
    repository.list_dispatchable.return_value = [
        MagicMock(id=3, desired_revision=7, tenant_id=1),
    ]
    sender = MagicMock()

    count = await dispatch_knowledge_fulltext_outbox_async(
        multi_tenant_enabled=False,
        repository=repository,
        sender=sender,
    )

    assert count == 1
    sender.assert_called_once_with(outbox_id=3, revision=7)
    assert not {"content", "document"}.intersection(sender.call_args.kwargs)


async def test_dispatcher_rejects_multi_tenant_without_reading_outbox():
    repository = AsyncMock()
    sender = MagicMock()

    with pytest.raises(ValueError, match="multi-tenant"):
        await dispatch_knowledge_fulltext_outbox_async(
            multi_tenant_enabled=True,
            repository=repository,
            sender=sender,
        )
    repository.list_dispatchable.assert_not_awaited()
    sender.assert_not_called()


def test_auto_repair_worker_keeps_minimal_message_cas_and_retry_lifecycle_contract():
    source = (Path(__file__).resolve().parents[3] / "bisheng/worker/knowledge/fulltext_index.py").read_text(
        encoding="utf-8"
    )
    publisher = source.split("def publish_knowledge_fulltext_auto_repair", 1)[1].split("async def _dispatch", 1)[0]
    runner = source.split("def _run_auto_repair", 1)[1]

    assert 'name="bisheng.worker.knowledge.fulltext_index.repair_source"' in source
    assert '"outbox_id": outbox_id' in publisher
    assert '"revision": revision' in publisher
    assert '"fingerprint": fingerprint' in publisher
    assert '"tenant_id":' not in publisher
    assert "claim_auto_repair" in source
    assert "if row is None:" in runner
    assert "run_retry_knowledge_parse_lifecycle(file_id)" in runner


def test_auto_repair_routes_share_entry_to_projection_without_reparse(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge_file import (
        KnowledgeFileDao,
        KnowledgeFileEntryType,
        KnowledgeFileStatus,
    )
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
        KnowledgeFulltextAutoRepairSource,
    )
    from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import (
        KnowledgeFulltextAutoRepairService,
    )
    from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
        KnowledgeFulltextProjectionAction,
    )

    celery_stub = MagicMock()
    celery_stub.task = lambda *args, **kwargs: lambda function: function
    worker_main_stub = ModuleType("bisheng.worker.main")
    worker_main_stub.bisheng_celery = celery_stub
    asyncio_utils_stub = ModuleType("bisheng.worker._asyncio_utils")
    asyncio_utils_stub.run_async_task = MagicMock()
    file_worker_stub = ModuleType("bisheng.worker.knowledge.file_worker")
    file_worker_stub.run_retry_knowledge_parse_lifecycle = MagicMock()
    monkeypatch.setitem(sys.modules, "bisheng.worker.main", worker_main_stub)
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", asyncio_utils_stub)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.file_worker",
        file_worker_stub,
    )
    worker_path = Path(__file__).resolve().parents[3] / "bisheng/worker/knowledge/fulltext_index.py"
    spec = importlib.util.spec_from_file_location(
        "test_fulltext_index_under_test",
        worker_path,
    )
    fulltext_index = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fulltext_index)

    source = KnowledgeFulltextAutoRepairSource(
        file_id=830,
        knowledge_id=45,
        object_name=None,
        desired_content_generation=0,
    )
    fingerprint = KnowledgeFulltextAutoRepairService.fingerprint(source)
    entry = SimpleNamespace(
        id=830,
        tenant_id=1,
        status=KnowledgeFileStatus.SUCCESS.value,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        object_name=None,
    )
    projection_repair = AsyncMock(return_value=True)
    parse_repair = MagicMock()
    update_status = MagicMock()

    monkeypatch.setattr(
        fulltext_index,
        "run_async_task",
        lambda coroutine_factory: asyncio.run(coroutine_factory()),
    )
    monkeypatch.setattr(
        fulltext_index,
        "_claim_auto_repair",
        AsyncMock(return_value=SimpleNamespace(aggregate_id=830)),
    )
    monkeypatch.setattr(
        fulltext_index,
        "_load_auto_repair_context",
        AsyncMock(return_value=(source, MagicMock())),
    )
    monkeypatch.setattr(
        fulltext_index.KnowledgeFulltextDocumentService,
        "decide",
        MagicMock(return_value=KnowledgeFulltextProjectionAction.UPSERT),
    )
    monkeypatch.setattr(
        fulltext_index,
        "_finish_auto_repair",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        fulltext_index,
        "_run_logical_entry_projection_repair",
        projection_repair,
        raising=False,
    )
    monkeypatch.setattr(KnowledgeFileDao, "get_file_by_ids", MagicMock(return_value=[entry]))
    monkeypatch.setattr(KnowledgeFileDao, "update_file_status", update_status)
    monkeypatch.setattr(
        file_worker_stub,
        "run_retry_knowledge_parse_lifecycle",
        parse_repair,
    )

    assert fulltext_index._run_auto_repair(
        outbox_id=76,
        revision=1,
        fingerprint=fingerprint,
    )
    projection_repair.assert_awaited_once()
    assert projection_repair.await_args.kwargs["file_id"] == 830
    assert projection_repair.await_args.kwargs["tenant_id"] == 1
    update_status.assert_not_called()
    parse_repair.assert_not_called()
