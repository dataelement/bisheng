"""积分旁路 hooks 的轻量单测：开关关闭时不写账本。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.points.domain.services import points_award_hooks as hooks


@pytest.mark.asyncio
async def test_notify_space_files_ready_noop_when_disabled():
    award = AsyncMock(return_value=SimpleNamespace(skipped=True, reason="points_disabled"))
    facade = SimpleNamespace(on_space_file_ready=award)

    async def fake_run(action):
        await action(facade)

    with (
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
async def test_notify_space_files_ready_swallows_errors():
    with patch.object(hooks, "_run_with_facade", AsyncMock(side_effect=RuntimeError("boom"))):
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
