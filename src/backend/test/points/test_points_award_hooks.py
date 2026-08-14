"""积分旁路 hooks：同步路径、异步投递与 enqueue fallback。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.config.celery_queues import POINTS_AWARD_QUEUE
from bisheng.points.domain.services import points_award_hooks as hooks


@pytest.mark.asyncio
async def test_notify_space_files_ready_sync_when_async_disabled():
    """award_async_enabled=false 时走同一会话 Facade。"""
    award = AsyncMock(return_value=SimpleNamespace(skipped=True, reason="points_disabled"))
    facade = SimpleNamespace(on_space_file_ready=award)

    async def fake_run(action):
        await action(facade)

    with (
        patch.object(hooks, "_award_async_enabled", return_value=False),
        patch.object(hooks, "_run_with_facade", side_effect=fake_run),
        patch.object(hooks, "resolve_space_level", AsyncMock(return_value="public")),
        patch.object(hooks, "resolve_space_manager_ids", AsyncMock(return_value=frozenset())),
    ):
        await hooks.notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=100)],
            uploader_id=4,
            is_favorite_space=False,
        )
    award.assert_awaited_once()
    assert award.await_args.args[0].publisher_id == 4
    assert award.await_args.args[0].uploader_id == 4


@pytest.mark.asyncio
async def test_notify_space_files_ready_enqueues_one_task_per_upload():
    """异步开启时一次上传只投一个 Celery 任务，携带全部 file_ids。"""
    enqueue = MagicMock()
    with (
        patch.object(hooks, "_award_async_enabled", return_value=True),
        patch.object(hooks, "resolve_space_level", AsyncMock(return_value="public")),
        patch.object(hooks, "resolve_space_manager_ids", AsyncMock(return_value=frozenset({9}))),
        patch.object(hooks, "_enqueue_award_event", enqueue),
    ):
        await hooks.notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=100), SimpleNamespace(id=101)],
            uploader_id=4,
            is_favorite_space=False,
            space_level="public",
        )
    enqueue.assert_called_once()
    body = enqueue.call_args.args[0]
    assert body["event_type"] == "space_file_ready"
    assert body["file_ids"] == [100, 101]
    assert body["space_manager_ids"] == [9]
    assert body["publisher_id"] == 4


@pytest.mark.asyncio
async def test_notify_space_files_ready_keeps_explicit_publisher_id():
    """审批发布显式传入的 publisher_id 不得被上传人覆盖。"""
    enqueue = MagicMock()
    with (
        patch.object(hooks, "_award_async_enabled", return_value=True),
        patch.object(hooks, "resolve_space_level", AsyncMock(return_value="public")),
        patch.object(hooks, "resolve_space_manager_ids", AsyncMock(return_value=frozenset())),
        patch.object(hooks, "_enqueue_award_event", enqueue),
    ):
        await hooks.notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=100)],
            uploader_id=4,
            publisher_id=8,
            is_favorite_space=False,
            space_level="public",
        )
    assert enqueue.call_args.args[0]["publisher_id"] == 8
    assert enqueue.call_args.args[0]["uploader_id"] == 4


@pytest.mark.asyncio
async def test_notify_space_files_ready_skips_enqueue_for_personal_space():
    """个人库整批不入队。"""
    enqueue = MagicMock()
    with (
        patch.object(hooks, "_award_async_enabled", return_value=True),
        patch.object(hooks, "_enqueue_award_event", enqueue),
    ):
        await hooks.notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=100), SimpleNamespace(id=101)],
            uploader_id=4,
            is_favorite_space=False,
            space_level="personal",
        )
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_sync_when_enqueue_fails():
    """Broker 投递失败时同步入账，不丢事件。"""
    sync = AsyncMock()
    with (
        patch.object(hooks, "_award_async_enabled", return_value=True),
        patch.object(hooks, "_run_payload_sync", sync),
        patch.object(hooks, "_enqueue_award_event", side_effect=RuntimeError("broker down")),
    ):
        await hooks._dispatch(
            "answer_adopted",
            {"tenant_id": 1, "question_id": 9, "answer_id": 2, "answerer_id": 4},
        )
    sync.assert_awaited_once()
    assert sync.await_args.args[0]["event_type"] == "answer_adopted"
    assert sync.await_args.args[0]["question_id"] == 9


def test_resolve_award_queue_defaults_to_points_award_celery(monkeypatch):
    """未设 POINTS_AWARD_CELERY_QUEUE 时解析为正式发分队列。"""
    monkeypatch.delenv("POINTS_AWARD_CELERY_QUEUE", raising=False)
    assert hooks._resolve_award_queue() == POINTS_AWARD_QUEUE


def test_resolve_award_queue_respects_env_override(monkeypatch):
    """POINTS_AWARD_CELERY_QUEUE 可覆盖正式队列名（压测隔离）。"""
    monkeypatch.setenv("POINTS_AWARD_CELERY_QUEUE", "points_award_local")
    assert hooks._resolve_award_queue() == "points_award_local"


@pytest.mark.asyncio
async def test_notify_space_files_ready_swallows_errors():
    with (
        patch.object(hooks, "_award_async_enabled", return_value=False),
        patch.object(hooks, "_run_with_facade", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await hooks.notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=1)],
            uploader_id=4,
            is_favorite_space=False,
            space_level="public",
        )


@pytest.mark.asyncio
async def test_notify_document_shared_builds_g7_event():
    award = AsyncMock()
    facade = SimpleNamespace(on_document_shared=award)

    async def fake_run(action):
        await action(facade)

    with (
        patch.object(hooks, "_award_async_enabled", return_value=False),
        patch.object(hooks, "_run_with_facade", side_effect=fake_run),
        patch.object(hooks, "resolve_space_manager_ids", AsyncMock(return_value=frozenset({9}))),
    ):
        await hooks.notify_document_shared(
            tenant_id=1,
            share_entry_id=77,
            source_space_id=1,
            target_space_id=2,
            uploader_id=4,
            sharer_id=5,
        )
    event = award.await_args.args[0]
    assert event.share_entry_id == 77
    assert event.related_manager_ids == frozenset({9})


@pytest.mark.asyncio
async def test_run_payload_sync_space_file_ready_maps_event():
    """Worker/fallback 共用的 payload 分发能还原 Facade 事件。"""
    award = AsyncMock()
    facade = SimpleNamespace(on_space_file_ready=award)

    async def fake_run(action):
        await action(facade)

    with patch.object(hooks, "_run_with_facade", side_effect=fake_run):
        await hooks._run_payload_sync(
            {
                "event_type": "space_file_ready",
                "tenant_id": 1,
                "space_id": 10,
                "space_level": "public",
                "file_id": 100,
                "uploader_id": 4,
                "publisher_id": None,
                "is_favorite_space": False,
                "space_manager_ids": [9],
            }
        )
    award.assert_awaited_once()
    event = award.await_args.args[0]
    assert event.file_id == 100
    assert event.space_manager_ids == frozenset({9})
    assert event.publisher_id == 4


@pytest.mark.asyncio
async def test_run_payload_sync_space_file_ready_processes_file_ids_in_order():
    """新 payload 的 file_ids 在同一会话按顺序逐个入账。"""
    award = AsyncMock()
    facade = SimpleNamespace(on_space_file_ready=award)

    async def fake_run(action):
        await action(facade)

    with patch.object(hooks, "_run_with_facade", side_effect=fake_run):
        await hooks._run_payload_sync(
            {
                "event_type": "space_file_ready",
                "tenant_id": 1,
                "space_id": 10,
                "space_level": "public",
                "file_ids": [100, 101, 100],
                "uploader_id": 4,
                "is_favorite_space": False,
                "space_manager_ids": [],
            }
        )
    assert [call.args[0].file_id for call in award.await_args_list] == [100, 101]
    assert all(call.args[0].publisher_id == 4 for call in award.await_args_list)


def test_space_file_ids_from_payload_prefers_file_ids():
    assert hooks._space_file_ids_from_payload({"file_ids": [2, 3], "file_id": 1}) == [2, 3]
    assert hooks._space_file_ids_from_payload({"file_id": 9}) == [9]
