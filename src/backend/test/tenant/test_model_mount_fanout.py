"""One provider failure must retain its traceback and not skip later providers."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.core import database
from bisheng.database.models.tenant import TenantDao
from bisheng.llm.application import model_mount_sharing
from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService


async def test_mount_fanout_continues_after_provider_failure(monkeypatch, caplog):
    operator = object()
    child = SimpleNamespace(root_dept_id=338, tenant_code="t338", tenant_name="Child")
    monkeypatch.setattr(
        TenantDao,
        "aget_by_id",
        AsyncMock(side_effect=lambda tid: SimpleNamespace(share_default_to_children=True) if tid == 1 else child),
    )
    monkeypatch.setattr(ResourceShareService, "distribute_to_child", AsyncMock())
    monkeypatch.setattr(TenantMountService, "_list_root_shared_resources", AsyncMock(return_value=[]))
    result = MagicMock()
    result.all.return_value = [(12,), (335,), (358,)]

    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(exec=AsyncMock(return_value=result))

    monkeypatch.setattr(database, "get_async_db_session", sessions)
    sharing = SimpleNamespace(ashare=AsyncMock(side_effect=[RuntimeError("original sharing failure"), None, None]))
    monkeypatch.setattr(model_mount_sharing, "get_model_mount_sharing_application", AsyncMock(return_value=sharing))
    await TenantMountService._on_child_mounted(69, auto_distribute=True, operator=operator)
    assert [call.kwargs["server_id"] for call in sharing.ashare.await_args_list] == [12, 335, 358]
    assert all(
        call.kwargs["identity"] is operator and call.kwargs["child_id"] == 69 for call in sharing.ashare.await_args_list
    )
    assert "original sharing failure" in caplog.text
    assert "not all arguments converted" not in caplog.text
    assert any(record.exc_info for record in caplog.records if "provider mount sharing" in record.getMessage())


@pytest.mark.parametrize(("auto_distribute", "root_shared"), [(False, True), (True, False)])
async def test_explicitly_disabled_mount_does_not_distribute_models(monkeypatch, auto_distribute, root_shared):
    distribute = AsyncMock()
    application = AsyncMock()
    monkeypatch.setattr(ResourceShareService, "distribute_to_child", distribute)
    monkeypatch.setattr(model_mount_sharing, "get_model_mount_sharing_application", application)
    monkeypatch.setattr(
        TenantDao, "aget_by_id", AsyncMock(return_value=SimpleNamespace(share_default_to_children=root_shared))
    )
    monkeypatch.setattr(TenantMountService, "_list_root_shared_resources", AsyncMock(return_value=[]))
    assert await TenantMountService._on_child_mounted(69, auto_distribute=auto_distribute, operator=object()) == []
    assert distribute.await_count == int(auto_distribute)
    application.assert_not_called()
