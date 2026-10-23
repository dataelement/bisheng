from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.worker.information import knowledge_delivery as worker_mod


async def test_route_task_visits_each_tenant_and_publishes_config_with_tenant_payload():
    service = AsyncMock()

    @asynccontextmanager
    async def _service_for_current_tenant(*args, **kwargs):
        yield service

    with (
        patch.object(worker_mod, "_active_tenant_ids", new=AsyncMock(return_value=[1, 2])),
        patch.object(worker_mod, "_service_session", _service_for_current_tenant),
        patch.object(worker_mod.deliver_information_articles_to_config, "apply_async") as apply_async,
    ):
        await worker_mod._route_new_information_articles_async("source-A", ["article-1"], 100)
        assert service.route_current_tenant.await_count == 2
        callbacks = [call.args[3] for call in service.route_current_tenant.await_args_list]
        await callbacks[0]("config-1", ["article-1"], 100)
        await callbacks[1]("config-2", ["article-1"], 100)
        assert apply_async.call_args_list[0].kwargs["args"][:2] == (1, "config-1")
        assert apply_async.call_args_list[1].kwargs["args"][:2] == (2, "config-2")


def test_config_task_rejects_header_payload_mismatch():
    token = set_current_tenant_id(2)
    try:
        fake_task = SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 2}))
        with pytest.raises(worker_mod.InformationTaskTenantContextError):
            worker_mod.deliver_information_articles_to_config.run(fake_task, 3, "config", ["article"], 100)
    finally:
        current_tenant_id.reset(token)
