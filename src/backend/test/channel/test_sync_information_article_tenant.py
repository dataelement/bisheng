"""Public article ingestion still refreshes tenant-scoped channel display data."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.core.context.tenant import current_tenant_id
from bisheng.worker.information import article, reconcile


async def test_active_tenant_ids_single_tenant_fallback():
    settings = SimpleNamespace(multi_tenant=SimpleNamespace(enabled=False))
    with patch("bisheng.common.services.config_service.settings", settings):
        assert await reconcile._active_tenant_ids() == [reconcile.DEFAULT_TENANT_ID]


async def test_active_tenant_ids_includes_every_active_depth():
    settings = SimpleNamespace(multi_tenant=SimpleNamespace(enabled=True))
    with (
        patch("bisheng.common.services.config_service.settings", settings),
        patch("bisheng.database.models.tenant.TenantDao.aget_active_ids", AsyncMock(return_value={7, 1, 3})),
    ):
        assert await reconcile._active_tenant_ids() == [1, 3, 7]


async def test_display_refresh_isolates_tenant_failure_and_restores_context():
    seen = []
    before = current_tenant_id.get()

    @asynccontextmanager
    async def session():
        yield SimpleNamespace()

    async def channels(source_id):
        assert source_id == "source-A"
        seen.append(current_tenant_id.get())
        if current_tenant_id.get() == 3:
            raise RuntimeError("tenant unavailable")
        return [f"channel-{current_tenant_id.get()}"]

    update = AsyncMock()
    with (
        patch.object(reconcile, "_active_tenant_ids", AsyncMock(return_value=[1, 3, 7])),
        patch("bisheng.core.database.get_async_db_session", session),
        patch(
            "bisheng.channel.domain.repositories.implementations.channel_repository_impl."
            "ChannelRepositoryImpl.find_channels_referencing_source",
            side_effect=channels,
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.ChannelService.update_channels_latest_article_time",
            update,
        ),
    ):
        await article._update_channel_display_time("source-A", SimpleNamespace())

    assert seen == [1, 3, 7]
    assert [call.args[0] for call in update.await_args_list] == [["channel-1"], ["channel-7"]]
    assert current_tenant_id.get() == before
