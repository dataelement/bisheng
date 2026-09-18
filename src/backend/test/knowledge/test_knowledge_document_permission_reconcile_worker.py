"""Aged F059 permission states must be redispatched from durable facts."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.approval.domain.models.approval_instance import (
    ApprovalOutboxStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)

_BACKEND = Path(__file__).resolve().parents[2]
if "bisheng.worker" in sys.modules:
    sys.modules["bisheng.worker"].__path__ = [
        str(_BACKEND / "bisheng/worker")
    ]
if "bisheng.worker.knowledge" in sys.modules:
    sys.modules["bisheng.worker.knowledge"].__path__ = [
        str(_BACKEND / "bisheng/worker/knowledge")
    ]

projection_worker = importlib.import_module(
    "bisheng.worker.knowledge.document_projection"
)


def _entry(
    entry_id: int,
    *,
    approval_instance_id: int | None,
    status: str = KnowledgeFileEntryStatus.PREPARING.value,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=entry_id,
        tenant_id=7,
        knowledge_id=20,
        file_name=f"{entry_id}.pdf",
        file_type=1,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        entry_status=status,
        approval_instance_id=approval_instance_id,
    )


async def test_permission_reconcile_redispatches_pending_failed_and_inconsistent_success() -> None:
    moving_manager = _entry(6, approval_instance_id=101)
    moving_manager.entry_type = KnowledgeFileEntryType.MANAGER.value
    candidates = [
        _entry(1, approval_instance_id=101),
        moving_manager,
        _entry(2, approval_instance_id=102),
        _entry(3, approval_instance_id=103),
        _entry(4, approval_instance_id=None),
        _entry(
            5,
            approval_instance_id=105,
            status=KnowledgeFileEntryStatus.DELETING.value,
        ),
    ]
    outboxes = {
        101: [
            SimpleNamespace(
                id=1001,
                status=ApprovalOutboxStatus.PENDING,
            )
        ],
        102: [
            SimpleNamespace(
                id=1002,
                status=ApprovalOutboxStatus.FAILED,
            )
        ],
        103: [
            SimpleNamespace(
                id=1003,
                status=ApprovalOutboxStatus.SUCCESS,
            )
        ],
    }

    with (
        patch.object(
            projection_worker.ApprovalInstanceRepository,
            "list_outbox",
            new=AsyncMock(
                side_effect=lambda instance_id: outboxes.get(instance_id, [])
            ),
        ),
        patch.object(
            projection_worker.execute_approval_outbox,
            "apply_async",
            new=MagicMock(),
        ) as execute,
        patch.object(
            projection_worker.retry_approval_outbox,
            "apply_async",
            new=MagicMock(),
        ) as retry,
    ):
        dispatched = await projection_worker._reconcile_permission_candidates(
            tenant_id=7,
            candidates=candidates,
        )

    assert dispatched == 3
    assert execute.call_args.kwargs["kwargs"] == {"outbox_id": 1001}
    assert [call.kwargs["kwargs"] for call in retry.call_args_list] == [
        {"outbox_id": 1002},
        {"outbox_id": 1003},
    ]
    for call in [execute.call_args, *retry.call_args_list]:
        assert call.kwargs["headers"] == {"tenant_id": 7}


async def test_rollback_reconcile_dispatches_from_preparing_tombstone() -> None:
    tombstone = _entry(7, approval_instance_id=None)
    tombstone.entry_type = (
        KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
    )
    tombstone.reference_document_id = 91
    tombstone.projection_previous_file_id = 100

    with patch.object(
        projection_worker.reconcile_document_rollback,
        "apply_async",
        new=MagicMock(),
    ) as task:
        dispatched = (
            await projection_worker._reconcile_rollback_candidates(
                tenant_id=7,
                candidates=[tombstone, tombstone],
            )
        )

    assert dispatched == 1
    assert task.call_args.kwargs == {
        "kwargs": {
            "tenant_id": 7,
            "document_id": 91,
            "manager_file_id": 100,
        },
        "headers": {"tenant_id": 7},
        "queue": projection_worker.DEFAULT_QUEUE,
    }


def test_final_document_delete_waits_for_every_entry_cleanup() -> None:
    ready = _entry(
        10,
        approval_instance_id=110,
        status=KnowledgeFileEntryStatus.DELETING.value,
    )
    ready.projection_status = KnowledgeFileProjectionStatus.READY.value
    processing = _entry(
        11,
        approval_instance_id=111,
        status=KnowledgeFileEntryStatus.DELETING.value,
    )
    processing.projection_status = (
        KnowledgeFileProjectionStatus.PROCESSING.value
    )

    projection_worker._require_entries_ready_for_document_delete([ready])

    try:
        projection_worker._require_entries_ready_for_document_delete(
            [ready, processing]
        )
    except RuntimeError as exc:
        assert "finish cleanup" in str(exc)
    else:
        raise AssertionError(
            "final delete must not race an entry projection cleanup"
        )


async def test_scan_visits_aged_rollback_beyond_full_deleting_page(async_db_session, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta

    old = datetime.now() - timedelta(hours=1)
    for i in range(101):
        row = _entry(1000 + i, approval_instance_id=None, status="deleting" if i < 100 else "preparing")
        row.entry_type = "projection_tombstone"
        row.projection_previous_file_id = 100
        row.projection_status = "failed"
        row.projection_retry_count = 8
        row.update_time = old
        async_db_session.add(row)
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    monkeypatch.setattr("bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf", lambda: SimpleNamespace(projection_max_retries=8))
    task = MagicMock()
    monkeypatch.setattr(projection_worker.reconcile_document_rollback, "apply_async", task)
    assert await projection_worker._scan_tenant_projection_async(7) == 0
    task.assert_called_once()
    assert task.call_args.kwargs["kwargs"]["document_id"] == 91


async def test_finalizer_rejects_changed_lease_before_permission_delete(async_db_session, monkeypatch):
    from contextlib import asynccontextmanager

    import pytest

    row = _entry(101, approval_instance_id=None, status="deleting")
    row.projection_status = "ready"
    row.projection_lease_owner = "new-worker"
    snapshot = row.model_copy(update={"projection_lease_owner": "old-worker"})
    async_db_session.add(row)
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        yield async_db_session

    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    permissions = AsyncMock()
    monkeypatch.setattr(projection_worker, "_delete_entry_permissions", permissions)
    with pytest.raises(RuntimeError, match="cleanup state changed"):
        await projection_worker._finalize_deleting_entry(snapshot)
    permissions.assert_not_awaited()


async def test_real_finalizer_retry_deletes_only_logical_entry(async_db_session, async_db_engine, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import datetime, timedelta

    import pytest
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from test.knowledge.test_knowledge_document_projection_service import _seed_entries, _service

    await _seed_entries(async_db_session)
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    row = await repo.find_by_id(101)
    row.entry_type = "projection_tombstone"
    row.entry_status = "deleting"
    await async_db_session.commit()

    @asynccontextmanager
    async def db():
        async with AsyncSession(async_db_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    permissions = AsyncMock(side_effect=[RuntimeError("FGA unavailable"), None])
    monkeypatch.setattr(projection_worker, "_delete_entry_permissions", permissions)
    service = _service(async_db_session, finalizer=projection_worker._finalize_deleting_entry)
    now = datetime.now()
    with pytest.raises(RuntimeError, match="FGA unavailable"):
        await service.process_entry(tenant_id=7, entry_id=101, lease_owner="first", now=now)
    row = await repo.find_by_id(101)
    assert row.projection_retry_count == 1
    assert row.projection_status == "failed"
    result = await service.process_entry(tenant_id=7, entry_id=101, lease_owner="second", now=row.projection_next_retry_at + timedelta(seconds=1))
    assert result.status == "cleaned"
    assert await repo.find_by_id(101) is None
    assert (await repo.find_by_id(100)).object_name == "tenant/7/manager.pdf"
    assert await repo.find_by_id(102) is not None
    assert permissions.await_count == 2
