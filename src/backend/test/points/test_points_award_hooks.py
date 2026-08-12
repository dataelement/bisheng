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


@pytest.mark.asyncio
async def test_notify_space_files_ready_enqueues_one_task_per_file():
    """异步开启时一文件一 Celery 任务。"""
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
    assert enqueue.call_count == 2
    first = enqueue.call_args_list[0].args[0]
    assert first["event_type"] == "space_file_ready"
    assert first["file_id"] == 100
    assert first["space_manager_ids"] == [9]


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
